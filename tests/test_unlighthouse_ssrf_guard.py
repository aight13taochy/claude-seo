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
import re
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


def test_chromium_gets_the_host_resolver_pin_and_the_egress_proxy(monkeypatch, tmp_path):
    config, _ = _run_captured(monkeypatch, tmp_path, "93.184.215.14")
    args = config["puppeteerOptions"]["args"]
    assert args[0] == "--host-resolver-rules=MAP example.com 93.184.215.14"
    assert re.fullmatch(r"--proxy-server=http://127\.0\.0\.1:\d+", args[1])
    # Without this, Chromium sends localhost and 127.0.0.1 around the proxy.
    assert "--proxy-bypass-list=<-loopback>" in args
    assert "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in args


def test_node_guard_knows_the_audited_port(monkeypatch, tmp_path):
    _, env = _run_captured(monkeypatch, tmp_path, "93.184.215.14")
    assert env["CLAUDE_SEO_PIN_PORT"] == "443"
    env = ul.build_guard_env("http://localhost:3000/", "127.0.0.1", {})
    assert env["CLAUDE_SEO_PIN_PORT"] == "3000"


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
    assert env["CLAUDE_SEO_NET_ALLOW"].split(",") == ["10.1.2.3:8080", "proxy.corp.internal:3128"]


def test_proxy_variables_are_found_whatever_their_case():
    env = ul.build_guard_env("https://example.com/", "93.184.215.14", {
        "NPM_CONFIG_PROXY": "http://upper.example:1",   # how Windows stores it
        "https_proxy": "http://lower.example:2",
        "UNRELATED": "http://not-a-proxy.example",
    })
    assert env["CLAUDE_SEO_NET_ALLOW"] == "lower.example:2,upper.example:1"


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
# Three real loopback servers stand in for Chromium's DevTools port (named by
# --port=, as a Lighthouse worker gets it), a DevTools port announced on a
# spawned child's stderr (as Chromium announces it to Puppeteer), and an
# unrelated local service a crawled page might redirect to.
_PROBE = r"""
const childProcess = require('child_process');
const dns = require('dns');
const net = require('net');
const fake = { 'evil.test': '10.0.0.5', 'rebind.test': '127.0.0.1',
               'public.test': '93.184.215.14', 'localhost': '127.0.0.1',
               'proxy.internal': '10.9.9.9', 'audited.test': '10.1.1.1' };
dns.lookup = (host, opts, cb) => {
  if (typeof opts === 'function') { cb = opts; opts = {}; }
  const address = net.isIP(host) ? host : fake[host];
  if (!address) return process.nextTick(() => cb(Object.assign(new Error('nx'), { code: 'ENOTFOUND' })));
  const entry = { address, family: net.isIP(address) };
  process.nextTick(() => opts.all ? cb(null, [entry]) : cb(null, address, entry.family));
};
const listen = () => new Promise((res) => {
  const server = net.createServer((s) => s.end()).listen(0, '127.0.0.1', () => res(server));
});
const lookup = (h) => new Promise((res) => dns.lookup(h, (e, a) => res(e ? e.code : a)));
const connect = (port, host) => new Promise((res) => {
  const s = net.connect(port, host);
  s.on('error', (e) => res(e.code));
  s.on('connect', () => { s.destroy(); res('connected'); });
});
(async () => {
  const [argvDevtools, spawnedDevtools, service] = await Promise.all([listen(), listen(), listen()]);
  const port = (server) => server.address().port;
  const pinPort = Number(process.env.PIN_PORT_FROM_SERVICE) ? port(service) : 0;
  require(process.env.GUARD_PATH).install(
    { ...process.env, CLAUDE_SEO_PIN_PORT: String(pinPort) },
    ['node', 'lighthouse.mjs', `--port=${port(argvDevtools)}`],
  );
  const child = childProcess.spawn(process.execPath, ['-e',
    `console.error('DevTools listening on ws://127.0.0.1:${port(spawnedDevtools)}/devtools/browser/x')`]);
  child.stderr.on('data', () => {});
  await new Promise((res) => child.on('close', res));
  const out = {
    pinned: await lookup('audited.test'),
    pinnedPromise: (await dns.promises.lookup('audited.test')).address,
    evil: await lookup('evil.test'),
    public: await lookup('public.test'),
    allowedProxy: await lookup('proxy.internal'),
    metadataLiteral: await connect(80, '169.254.169.254'),
    mappedLiteral: await connect(80, '::ffff:169.254.169.254'),
    rfc1918Literal: await connect(80, '192.168.1.1'),
    metadataLiteralLookup: await lookup('169.254.169.254'),
    devtoolsFromArgv: await connect(port(argvDevtools), '127.0.0.1'),
    devtoolsFromStderr: await connect(port(spawnedDevtools), '127.0.0.1'),
    devtoolsByName: await connect(port(argvDevtools), 'localhost'),
    serviceLiteral: await connect(port(service), '127.0.0.1'),
    serviceByLocalhost: await connect(port(service), 'localhost'),
    serviceByRebind: await connect(port(service), 'rebind.test'),
    serviceMappedV6: await connect(port(service), '::ffff:127.0.0.1'),
    loopbackProxyPort: await connect(Number(process.env.ALLOWED_PROXY_PORT), '127.0.0.1'),
    serviceBesideLoopbackProxy: await connect(port(service), '127.0.0.1'),
  };
  for (const server of [argvDevtools, spawnedDevtools, service]) server.close();
  process.stdout.write(JSON.stringify(out));
})();
"""


# A proxy configured on loopback (as in sandboxes) is allowed on its own
# port; nothing listens there, so an allowed connection reads ECONNREFUSED.
ALLOWED_PROXY_PORT = 9


def _run_guard_probe(pin_ip="93.184.215.14", pin_service_port=False):
    proc = subprocess.run(
        [NODE, "-e", _PROBE],
        env={
            **ul.os.environ,
            "GUARD_PATH": str(GUARD),
            "CLAUDE_SEO_PIN_HOST": "audited.test",
            "CLAUDE_SEO_PIN_IP": pin_ip,
            "CLAUDE_SEO_NET_ALLOW": f"proxy.internal:3128,127.0.0.1:{ALLOWED_PROXY_PORT}",
            "PIN_PORT_FROM_SERVICE": "1" if pin_service_port else "0",
            "ALLOWED_PROXY_PORT": str(ALLOWED_PROXY_PORT),
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
    assert out["public"] == "93.184.215.14"
    assert out["allowedProxy"] == "10.9.9.9"


@needs_node
def test_guard_blocks_private_ip_literals():
    out = _run_guard_probe()
    assert out["metadataLiteral"] == "ECLAUDESEOBLOCKED"
    assert out["mappedLiteral"] == "ECLAUDESEOBLOCKED"
    assert out["rfc1918Literal"] == "ECLAUDESEOBLOCKED"
    assert out["metadataLiteralLookup"] == "ECLAUDESEOBLOCKED"


@needs_node
def test_guard_keeps_only_chromium_devtools_ports_on_loopback():
    """Puppeteer and Lighthouse reach Chromium; a redirect to any other
    local service is refused, by literal, by name, or through rebinding."""
    out = _run_guard_probe()
    assert out["devtoolsFromArgv"] == "connected"
    assert out["devtoolsFromStderr"] == "connected"
    assert out["devtoolsByName"] == "connected"
    assert out["serviceLiteral"] == "ECLAUDESEOBLOCKED"
    assert out["serviceByLocalhost"] == "ECLAUDESEOBLOCKED"
    assert out["serviceByRebind"] == "ECLAUDESEOBLOCKED"
    assert out["serviceMappedV6"] == "ECLAUDESEOBLOCKED"


@needs_node
def test_a_loopback_proxy_opens_its_own_port_only():
    """CLAUDE_SEO_NET_ALLOW is host:port: a proxy on 127.0.0.1 does not open
    every local port (the hole a host-only allowance left)."""
    out = _run_guard_probe()
    assert out["loopbackProxyPort"] == "ECONNREFUSED"  # allowed, nothing listening
    assert out["serviceBesideLoopbackProxy"] == "ECLAUDESEOBLOCKED"


@needs_node
def test_allowlisted_local_target_is_reachable_on_its_own_port_only():
    """A CLAUDE_SEO_LOCAL_TARGETS pin (127.0.0.1) opens that port, nothing else."""
    out = _run_guard_probe(pin_ip="127.0.0.1", pin_service_port=True)
    assert out["serviceLiteral"] == "connected"
    assert out["devtoolsFromArgv"] == "connected"
    no_pin_port = _run_guard_probe(pin_ip="127.0.0.1", pin_service_port=False)
    assert no_pin_port["serviceLiteral"] == "ECLAUDESEOBLOCKED"


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
