"""Unlighthouse extension regressions (issue #189).

Three confirmed bugs in scripts/unlighthouse_run.py and
extensions/unlighthouse/install.sh:

(a) ``--max-routes`` was forwarded as ``--scanner '{"maxRoutes": N}'``, a
    made-up CLI flag unlighthouse-ci's cac-based parser never reads
    (confirmed against packages/cli/src/{createCli,ci,util}.ts upstream).
    The only documented way to reach ``scanner.maxRoutes`` is
    ``--config-file <path>`` pointing at a config module. No per-page
    timeout guard existed at all.
(b) ``ci-result.json`` was parsed assuming a dict; the default
    ``jsonSimple`` reporter (used whenever ``--reporter`` isn't passed)
    writes a flat JSON array of per-route results instead.
(c) install.sh required ``~/.claude/skills/seo`` to exist, which is never
    true for a marketplace/plugin install, so the installer always
    aborted in that path.

These tests exercise the pure argument-builder and JSON-normalization
functions directly with fixture data: no network, no unlighthouse install,
no subprocess execution.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import unlighthouse_run as ul  # noqa: E402

# --------------------------------------------------------------------------
# (a) config / argument builder
# --------------------------------------------------------------------------


def test_build_config_sets_scanner_max_routes_as_number():
    config = ul.build_config(50, 60_000)
    assert config["scanner"]["maxRoutes"] == 50
    assert config["puppeteerClusterOptions"]["timeout"] == 60_000


def test_build_config_none_max_routes_maps_to_false_unlimited():
    config = ul.build_config(None, 30_000)
    assert config["scanner"]["maxRoutes"] is False


def test_write_config_file_emits_valid_esm_default_export(tmp_path):
    config = ul.build_config(25, 45_000)
    path = ul.write_config_file(tmp_path, config)
    assert path.name == "unlighthouse.config.mjs"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("export default ")
    payload = json.loads(text.removeprefix("export default ").strip())
    assert payload == config


def test_build_cmd_never_uses_the_ignored_scanner_json_flag(tmp_path):
    config_path = tmp_path / "unlighthouse.config.mjs"
    cmd = ul.build_cmd(
        "https://example.com", device="mobile", out_dir=tmp_path, config_path=config_path,
    )
    assert "--scanner" not in cmd
    assert "--max-routes" not in cmd


def test_build_cmd_passes_config_file_and_documented_flags(tmp_path):
    config_path = tmp_path / "unlighthouse.config.mjs"
    cmd = ul.build_cmd(
        "https://example.com", device="desktop", out_dir=tmp_path, config_path=config_path,
    )
    assert cmd[0:2] == ["npx", "--yes"]
    assert "--site" in cmd and "https://example.com" in cmd
    assert "--desktop" in cmd and "--device" not in cmd
    assert "--config-file" in cmd
    assert str(config_path) in cmd
    assert "--output-path" in cmd and str(tmp_path) in cmd
    # The real CLI flag (packages/cli/src/ci.ts) is `--build-static`, not
    # the nonexistent `--build-static-files` the old code passed.
    assert "--build-static" in cmd
    assert "--build-static-files" not in cmd


# --------------------------------------------------------------------------
# (b) ci-result.json shape handling
# --------------------------------------------------------------------------

JSON_SIMPLE_FIXTURE = [
    {"path": "/", "score": 0.92, "performance": 0.9, "accessibility": 0.95,
     "best-practices": 1.0, "seo": 0.88},
    {"path": "/about", "score": 0.80, "performance": 0.7, "accessibility": 0.9,
     "best-practices": 0.92, "seo": 0.85},
]

JSON_EXPANDED_FIXTURE = {
    "summary": {"score": 0.86},
    "routes": [
        {
            "path": "/",
            "score": 0.92,
            "categories": {
                "performance": {"key": "performance", "score": 0.9},
                "accessibility": {"key": "accessibility", "score": 0.95},
                "best-practices": {"key": "best-practices", "score": 1.0},
                "seo": {"key": "seo", "score": 0.88},
            },
            "metrics": {},
        },
        {
            "path": "/about",
            "score": 0.80,
            "categories": {
                "performance": {"key": "performance", "score": 0.7},
                "accessibility": {"key": "accessibility", "score": 0.9},
                "best-practices": {"key": "best-practices", "score": 0.92},
                "seo": {"key": "seo", "score": 0.85},
            },
            "metrics": {},
        },
    ],
    "metadata": {},
}


def test_normalize_handles_default_jsonsimple_array_shape():
    normalized = ul.normalize_ci_result(JSON_SIMPLE_FIXTURE)
    assert normalized["route_count"] == 2
    assert normalized["routes"] == JSON_SIMPLE_FIXTURE
    assert normalized["aggregate_scores"]["performance"] == 0.8
    assert normalized["aggregate_scores"]["accessibility"] == pytest.approx(0.925)
    assert normalized["aggregate_scores"]["seo"] == pytest.approx(0.865)


def test_normalize_falls_back_to_object_shape_with_routes_key():
    normalized = ul.normalize_ci_result(JSON_EXPANDED_FIXTURE)
    assert normalized["route_count"] == 2
    assert normalized["aggregate_scores"]["performance"] == 0.8
    assert normalized["aggregate_scores"]["accessibility"] == pytest.approx(0.925)


def test_normalize_tolerates_garbage_input():
    assert ul.normalize_ci_result(None) == {
        "routes": [], "route_count": 0, "aggregate_scores": {},
    }
    assert ul.normalize_ci_result({"unexpected": "shape"}) == {
        "routes": [], "route_count": 0, "aggregate_scores": {},
    }
    assert ul.normalize_ci_result([1, 2, "not-a-dict"]) == {
        "routes": [], "route_count": 0, "aggregate_scores": {},
    }


# --------------------------------------------------------------------------
# (c) installer no longer hard-requires the manual skill directory
# --------------------------------------------------------------------------


def test_installer_detects_plugin_install_paths():
    text = (ROOT / "extensions" / "unlighthouse" / "install.sh").read_text(encoding="utf-8")
    assert "CLAUDE_PLUGIN_ROOT" in text
    assert "plugins/cache" in text
    # The old unconditional abort before any plugin-path check is gone.
    assert '[ ! -d "${SKILL_DIR}/seo" ] && { echo "✗ claude-seo base not installed."; exit 1; }' not in text


# --------------------------------------------------------------------------
# (d) Route discovery stays on the audited origin
# --------------------------------------------------------------------------

import subprocess  # noqa: E402

PIN_RULE = "--host-resolver-rules=MAP example.com 93.184.216.34"


def test_build_config_carries_the_url_list():
    config = ul.build_config(
        10, 60_000, [PIN_RULE], urls=["https://example.com/", "https://example.com/a"],
    )
    assert config["urls"] == ["https://example.com/", "https://example.com/a"]
    assert config["puppeteerOptions"] == {"args": [PIN_RULE]}


def _mock_run_env(monkeypatch, pinned_ip="93.184.216.34"):
    monkeypatch.setattr(ul, "validate_url_strict", lambda url: ("https://example.com/", pinned_ip))
    monkeypatch.setattr(ul, "_check_node", lambda: None)
    monkeypatch.setattr(
        ul, "discover_routes", lambda target, max_routes: [target, "https://example.com/a"],
    )
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(ul.subprocess, "run", fake_run)
    return calls


def test_run_hands_unlighthouse_the_url_list_behind_the_egress_proxy(monkeypatch, tmp_path):
    calls = _mock_run_env(monkeypatch)
    result = ul.run("https://example.com/", output_dir=str(tmp_path), max_routes=5)

    assert len(calls) == 1
    config_text = (tmp_path / "unlighthouse.config.mjs").read_text(encoding="utf-8")
    config = json.loads(config_text.removeprefix("export default ").strip())
    assert config["urls"] == ["https://example.com/", "https://example.com/a"]
    args = config["puppeteerOptions"]["args"]
    assert args[0] == PIN_RULE
    assert any(arg.startswith("--proxy-server=http://127.0.0.1:") for arg in args)
    assert "--proxy-bypass-list=<-loopback>" in args
    assert result["ok"] is True
    assert result["scanned_urls"] == 2
    assert result["warnings"] == []
    assert result["blocked_requests"] == []


def test_run_refuses_an_unpinnable_target_before_any_subprocess(monkeypatch, tmp_path):
    calls = _mock_run_env(monkeypatch, pinned_ip="not-an-ip")
    result = ul.run("https://example.com/", output_dir=str(tmp_path))
    assert result["ok"] is False
    assert result["error"].startswith("url_safety:")
    assert calls == []


def _fake_fetch(pages, fetched):
    def fetch(url, max_bytes):
        fetched.append(url)
        content = pages.get(url)
        return {
            "status_code": 200 if content is not None else 404,
            "content": (content or "").encode("utf-8"),
            "content_type": "",
            "final_url": url,
            "too_large": False,
            "error": None,
        }
    return fetch


def _urlset(*locs):
    body = "".join(f"<url><loc>{loc}</loc></url>" for loc in locs)
    return f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'


def test_discover_routes_keeps_only_exact_same_origin_urls(monkeypatch):
    pages = {
        "https://example.com/robots.txt": (
            "Sitemap: https://example.com/index.xml\n"
            "Sitemap: https://cdn.attacker.example/sitemap.xml\n"
        ),
        "https://example.com/index.xml": (
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<sitemap><loc>https://example.com/pages.xml</loc></sitemap>"
            "<sitemap><loc>http://169.254.169.254/latest/</loc></sitemap>"
            "</sitemapindex>"
        ),
        "https://example.com/pages.xml": _urlset(
            "https://example.com/about#team",
            "https://example.com@10.0.0.1/",  # crawler-bypass shape: host is 10.0.0.1
            "https://internal.example.com/",  # subdomain: not covered by the pin
            "https://example.com:8443/",  # other port
            "http://example.com/plain",  # other scheme
            "https://example.com.attacker.net/",
            "https://example.com/blog",
        ),
    }
    fetched = []
    monkeypatch.setattr(ul, "_bounded_fetch", _fake_fetch(pages, fetched))

    routes = ul.discover_routes("https://example.com/", max_routes=None)

    assert routes == ["https://example.com/", "https://example.com/about", "https://example.com/blog"]
    assert all(url.startswith("https://example.com/") for url in fetched)


def test_discover_routes_respects_max_routes(monkeypatch):
    pages = {
        "https://example.com/sitemap.xml": _urlset(*(f"https://example.com/p{i}" for i in range(10))),
    }
    monkeypatch.setattr(ul, "_bounded_fetch", _fake_fetch(pages, []))
    routes = ul.discover_routes("https://example.com/", max_routes=3)
    assert routes == ["https://example.com/", "https://example.com/p0", "https://example.com/p1"]


def test_discover_routes_falls_back_to_same_origin_links_on_the_page(monkeypatch):
    pages = {
        "https://example.com/": (
            '<html><body><a href="/pricing">p</a><a href="https://other.example/">o</a>'
            '<a href="https://example.com@127.0.0.1/admin">x</a></body></html>'
        ),
    }
    monkeypatch.setattr(ul, "_bounded_fetch", _fake_fetch(pages, []))
    routes = ul.discover_routes("https://example.com/", max_routes=None)
    assert routes == ["https://example.com/", "https://example.com/pricing"]


def test_discover_routes_rejects_doctype_sitemaps(monkeypatch):
    pages = {
        "https://example.com/sitemap.xml": '<!DOCTYPE x [<!ENTITY a "b">]>' + _urlset("https://example.com/a"),
    }
    monkeypatch.setattr(ul, "_bounded_fetch", _fake_fetch(pages, []))
    assert ul.discover_routes("https://example.com/", max_routes=None) == ["https://example.com/"]
