"""
Unlighthouse cannot be steered to private addresses.

``scripts/unlighthouse_run.py`` validates the target once, then hands it to
unlighthouse, which resolves DNS and follows redirects in two places of its
own: Chromium (Puppeteer + Lighthouse) and Node (axios/got for robots.txt,
sitemaps and every crawled route, keeping the HTML in the report). Both now
get the pre-flight pin:

- Chromium via ``puppeteerOptions.args = chromium_launch_args(...)``.
- Node via ``scripts/node_net_guard.cjs`` preloaded with
  ``NODE_OPTIONS=--require``, which pins the audited host and refuses
  connections to non-public addresses (loopback excepted: DevTools).

The Python side is checked with ``subprocess.run`` mocked; the guard itself
runs in a real Node process when ``node`` is on PATH.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import unlighthouse_run as ul  # noqa: E402
from url_safety import PROXY_RESOLVES, URLSafetyError  # noqa: E402

GUARD = ROOT / "scripts" / "node_net_guard.cjs"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not on PATH")


# --------------------------------------------------------------------------
# Python wiring
# --------------------------------------------------------------------------


class _Captured(Exception):
    pass


def _run_captured(monkeypatch, tmp_path, pinned_ip, base_env=None):
    """Run ul.run() up to the subprocess call and return (config, env)."""
    monkeypatch.setattr(ul, "validate_url_strict", lambda url: ("https://example.com/", pinned_ip))
    monkeypatch.setattr(ul, "_check_node", lambda: None)
    for key in list(ul.os.environ):
        if key.startswith("CLAUDE_SEO_") or key.lower() in ul._PROXY_ENV_KEYS or key == "NODE_OPTIONS":
            monkeypatch.delenv(key, raising=False)
    for key, value in (base_env or {}).items():
        monkeypatch.setenv(key, value)
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["env"] = kwargs.get("env")
        raise _Captured

    monkeypatch.setattr(ul.subprocess, "run", fake_run)
    with pytest.raises(_Captured):
        ul.run("https://example.com/", output_dir=str(tmp_path))
    config_text = (tmp_path / "unlighthouse.config.mjs").read_text(encoding="utf-8")
    config = json.loads(config_text.removeprefix("export default ").strip())
    return config, seen["env"]


def test_chromium_gets_the_host_resolver_pin(monkeypatch, tmp_path):
    config, _ = _run_captured(monkeypatch, tmp_path, "93.184.215.14")
    assert config["puppeteerOptions"]["args"] == [
        "--host-resolver-rules=MAP example.com 93.184.215.14"
    ]


def test_node_processes_preload_the_guard(monkeypatch, tmp_path):
    _, env = _run_captured(monkeypatch, tmp_path, "93.184.215.14")
    assert env["CLAUDE_SEO_NET_GUARD"] == "1"
    assert env["CLAUDE_SEO_PIN_HOST"] == "example.com"
    assert env["CLAUDE_SEO_PIN_IP"] == "93.184.215.14"
    assert ul.node_require_option(ul.NODE_NET_GUARD) in env["NODE_OPTIONS"]


def test_existing_node_options_and_proxies_are_kept(monkeypatch, tmp_path):
    _, env = _run_captured(
        monkeypatch, tmp_path, "93.184.215.14",
        base_env={
            "NODE_OPTIONS": "--max-old-space-size=4096",
            "HTTPS_PROXY": "http://proxy.corp.internal:3128",
            "npm_config_proxy": "10.1.2.3:8080",
        },
    )
    assert env["NODE_OPTIONS"].startswith("--max-old-space-size=4096 --require ")
    assert env["CLAUDE_SEO_NET_ALLOW"].split(",") == ["10.1.2.3", "proxy.corp.internal"]


def test_proxy_variables_are_found_whatever_their_case():
    env = ul.build_guard_env("https://example.com/", "93.184.215.14", {
        "NPM_CONFIG_PROXY": "http://upper.example:1",   # how Windows stores it
        "https_proxy": "http://lower.example:2",
        "UNRELATED": "http://not-a-proxy.example",
    })
    assert env["CLAUDE_SEO_NET_ALLOW"] == "lower.example,upper.example"


def test_trusted_proxy_mode_applies_no_pin(monkeypatch, tmp_path):
    config, env = _run_captured(monkeypatch, tmp_path, PROXY_RESOLVES)
    assert "puppeteerOptions" not in config
    assert "CLAUDE_SEO_NET_GUARD" not in env
    assert "--require" not in env.get("NODE_OPTIONS", "")


def test_unpinnable_host_is_refused_before_any_subprocess(monkeypatch, tmp_path):
    monkeypatch.setattr(ul, "validate_url_strict", lambda url: ("https://example.com/", "1.2.3.4"))

    def refuse(url, ip):
        raise URLSafetyError("Hostname cannot be pinned in Chromium")

    monkeypatch.setattr(ul, "chromium_launch_args", refuse)
    monkeypatch.setattr(ul.subprocess, "run", lambda *a, **k: pytest.fail("subprocess started"))
    result = ul.run("https://example.com/", output_dir=str(tmp_path))
    assert result["ok"] is False
    assert result["error"].startswith("url_safety: ")


def test_build_config_without_args_leaves_puppeteer_defaults_alone():
    assert "puppeteerOptions" not in ul.build_config(10, 1000)
    assert "puppeteerOptions" not in ul.build_config(10, 1000, [])


def test_require_option_escapes_for_node_options_parsing():
    posix = ul.node_require_option(PurePosixPath("/a b/g.cjs"))
    assert posix == '--require "/a b/g.cjs"'
    # Node unescapes a backslash inside quotes, so each one is doubled.
    windows = ul.node_require_option(PureWindowsPath("C:\\Users\\A B\\g.cjs"))
    assert windows == '--require "C:\\\\Users\\\\A B\\\\g.cjs"'


@needs_node
def test_node_loads_the_quoted_require_path(tmp_path):
    # On POSIX a backslash is a legal filename character, so the same
    # escaping Windows paths rely on is exercised everywhere.
    name = "dir with space" if sys.platform == "win32" else "dir with space\\and backslash"
    probe_dir = tmp_path / name
    probe_dir.mkdir()
    probe = probe_dir / "probe.cjs"
    probe.write_text("globalThis.__claudeSeoProbe = 'loaded';\n", encoding="utf-8")
    proc = subprocess.run(
        [NODE, "-e", "process.stdout.write(String(globalThis.__claudeSeoProbe))"],
        env={**ul.os.environ, "NODE_OPTIONS": ul.node_require_option(probe)},
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert proc.stdout == "loaded", proc.stderr


# --------------------------------------------------------------------------
# The Node guard itself
# --------------------------------------------------------------------------

# Stubs dns.lookup before the guard captures it, so hostnames can "resolve"
# anywhere without real DNS; connections are judged before any packet leaves.
_PROBE = r"""
const dns = require('dns');
const net = require('net');
const fake = { 'evil.test': '10.0.0.5', 'rebind.test': '127.0.0.1',
               'public.test': '93.184.215.14', 'localhost': '127.0.0.1',
               'proxy.internal': '10.9.9.9' };
dns.lookup = (host, opts, cb) => {
  if (typeof opts === 'function') { cb = opts; opts = {}; }
  const address = net.isIP(host) ? host : fake[host];
  if (!address) return process.nextTick(() => cb(Object.assign(new Error('nx'), { code: 'ENOTFOUND' })));
  const entry = { address, family: net.isIP(address) };
  process.nextTick(() => opts.all ? cb(null, [entry]) : cb(null, address, entry.family));
};
require(process.env.GUARD_PATH).install(process.env);
const lookup = (h) => new Promise((res) => dns.lookup(h, (e, a) => res(e ? e.code : a)));
const connect = (port, host) => new Promise((res) => {
  const s = net.connect(port, host);
  s.on('error', (e) => res(e.code));
  s.on('connect', () => { s.destroy(); res('connected'); });
});
(async () => {
  const server = net.createServer((s) => s.end()).listen(0, '127.0.0.1');
  await new Promise((r) => server.on('listening', r));
  const port = server.address().port;
  const out = {
    pinned: await lookup('audited.test'),
    pinnedPromise: (await dns.promises.lookup('audited.test')).address,
    evil: await lookup('evil.test'),
    rebindToLoopback: await lookup('rebind.test'),
    localhost: await lookup('localhost'),
    public: await lookup('public.test'),
    allowedProxy: await lookup('proxy.internal'),
    metadataLiteral: await connect(80, '169.254.169.254'),
    mappedLiteral: await connect(80, '::ffff:169.254.169.254'),
    rfc1918Literal: await connect(80, '192.168.1.1'),
    loopbackLiteral: await connect(port, '127.0.0.1'),
    metadataLiteralLookup: await lookup('169.254.169.254'),
  };
  server.close();
  process.stdout.write(JSON.stringify(out));
})();
"""


def _run_guard_probe(pin_ip="93.184.215.14"):
    proc = subprocess.run(
        [NODE, "-e", _PROBE],
        env={
            **ul.os.environ,
            "GUARD_PATH": str(GUARD),
            "CLAUDE_SEO_PIN_HOST": "audited.test",
            "CLAUDE_SEO_PIN_IP": pin_ip,
            "CLAUDE_SEO_NET_ALLOW": "proxy.internal",
        },
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@needs_node
def test_guard_pins_the_audited_host_and_blocks_private_resolutions():
    out = _run_guard_probe()
    assert out["pinned"] == "93.184.215.14"
    assert out["pinnedPromise"] == "93.184.215.14"
    assert out["evil"] == "ECLAUDESEOBLOCKED"
    assert out["rebindToLoopback"] == "ECLAUDESEOBLOCKED"
    assert out["localhost"] == "127.0.0.1"
    assert out["public"] == "93.184.215.14"
    assert out["allowedProxy"] == "10.9.9.9"


@needs_node
def test_guard_blocks_private_ip_literals_but_keeps_devtools_loopback():
    out = _run_guard_probe()
    assert out["metadataLiteral"] == "ECLAUDESEOBLOCKED"
    assert out["mappedLiteral"] == "ECLAUDESEOBLOCKED"
    assert out["rfc1918Literal"] == "ECLAUDESEOBLOCKED"
    assert out["loopbackLiteral"] == "connected"
    assert out["metadataLiteralLookup"] == "ECLAUDESEOBLOCKED"


@needs_node
def test_guard_is_inert_without_the_opt_in_flag(tmp_path):
    script = (
        "const dns=require('dns'); const before=dns.lookup;"
        f"require({json.dumps(str(GUARD))});"
        "process.stdout.write(String(dns.lookup===before));"
    )
    env = {k: v for k, v in ul.os.environ.items() if k != "CLAUDE_SEO_NET_GUARD"}
    proc = subprocess.run([NODE, "-e", script], env=env, capture_output=True,
                          text=True, timeout=60, check=False)
    assert proc.stdout == "true", proc.stderr
