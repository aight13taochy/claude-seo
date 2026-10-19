"""
URL-safety entry points: one canonical module, one rule.

Guards three properties that the docs promise and nothing else enforced:

  - Repository code never takes ``validate_url`` from ``google_auth``. That
    name is a deprecated alias living in the credentials module, which is
    not an SSRF guard; importing it there read as the security entry point.
  - Every script that launches Chromium pins the audited host to the
    pre-flight IP with ``url_safety.chromium_launch_args``, so a
    DNS-rebinding answer cannot steer Chromium's own resolver.
  - ``chromium_launch_args`` builds exactly one resolver rule and refuses
    any hostname that could smuggle in a second one.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

pytest.importorskip("requests")
import google_auth  # noqa: E402
import url_safety  # noqa: E402
from url_safety import PROXY_RESOLVES, URLSafetyError, chromium_launch_args  # noqa: E402

SOURCE_FILES = sorted(
    path
    for path in {
        *SCRIPTS.glob("*.py"),
        *ROOT.glob("extensions/*/scripts/*.py"),
        *ROOT.glob("plugins/*/**/*.py"),
        *ROOT.glob("tests/*.py"),
    }
    # This file exercises the deprecated alias on purpose.
    if path.name != Path(__file__).name
)
LAUNCHING_FILES = sorted({*SCRIPTS.glob("*.py"), *ROOT.glob("extensions/*/scripts/*.py")})


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


# ---------------------------------------------------------------------------
# No code path reaches validate_url through google_auth
# ---------------------------------------------------------------------------


def _uses_google_auth_validate_url(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "google_auth":
            if any(alias.name in ("validate_url", "*") for alias in node.names):
                lines.append(node.lineno)
        elif (
            isinstance(node, ast.Attribute)
            and node.attr == "validate_url"
            and isinstance(node.value, ast.Name)
            and node.value.id == "google_auth"
        ):
            lines.append(node.lineno)
    return lines


def test_no_repository_code_takes_validate_url_from_google_auth() -> None:
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}:{line}"
        for path in SOURCE_FILES
        for line in _uses_google_auth_validate_url(_tree(path))
    ]
    assert not offenders, (
        "import validate_url / validate_url_strict from url_safety, not google_auth: "
        + ", ".join(offenders)
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/page",
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal./",
        "ftp://example.com/",
    ],
)
def test_google_auth_alias_warns_and_matches_url_safety(url: str) -> None:
    with pytest.warns(DeprecationWarning, match="url_safety"):
        got = google_auth.validate_url(url)
    assert got == url_safety.validate_url(url)


# ---------------------------------------------------------------------------
# Every Chromium launch is pinned
# ---------------------------------------------------------------------------


def _chromium_launches(tree: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "launch"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "chromium"
    ]


def test_every_chromium_launch_passes_the_resolver_pin() -> None:
    found = []
    for path in LAUNCHING_FILES:
        tree = _tree(path)
        launches = _chromium_launches(tree)
        if not launches:
            continue
        builds_pin = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "chromium_launch_args"
            for node in ast.walk(tree)
        )
        name = path.relative_to(ROOT).as_posix()
        assert builds_pin, f"{name} launches Chromium without calling chromium_launch_args()"
        for call in launches:
            assert any(kw.arg == "args" for kw in call.keywords), (
                f"{name}:{call.lineno} launches Chromium without args="
            )
            found.append(f"{name}:{call.lineno}")
    # render_page.py, capture_screenshot.py and analyze_visual.py at least.
    assert len(found) >= 3, f"expected the known launch sites, found {found}"


def _calls_named(tree: ast.AST, name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
        )
    ]


def test_every_chromium_launch_guards_routes_and_redirect_hops() -> None:
    """Each route handler knows its top-level URL (the only way a
    CLAUDE_SEO_LOCAL_TARGETS origin can render), and each script watches the
    redirect hops Playwright never routes, then refuses on a bad one."""
    checked = []
    for path in LAUNCHING_FILES:
        tree = _tree(path)
        if not _chromium_launches(tree):
            continue
        name = path.relative_to(ROOT).as_posix()
        factories = _calls_named(tree, "make_safe_playwright_route_handler")
        assert factories, f"{name} launches Chromium without a route handler"
        for call in factories:
            assert any(kw.arg == "top_level_url" for kw in call.keywords), (
                f"{name}:{call.lineno} builds a route handler without top_level_url="
            )
        routes = _calls_named(tree, "route")
        watches = [
            call
            for call in _calls_named(tree, "on")
            if call.args
            and isinstance(call.args[0], ast.Constant)
            and call.args[0].value == "request"
            and isinstance(call.args[1], ast.Attribute)
            and call.args[1].attr == "watch_request"
        ]
        assert routes and len(watches) >= len(routes), (
            f"{name} routes {len(routes)} page(s) but watches redirects on {len(watches)}"
        )
        assert _calls_named(tree, "check_redirects"), (
            f"{name} never calls check_redirects()"
        )
        checked.append(name)
    assert len(checked) >= 3, f"expected the known launch sites, found {checked}"


# ---------------------------------------------------------------------------
# chromium_launch_args
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected_host"),
    [
        ("https://example.com/path?q=1", "example.com"),
        ("https://Example.COM./", "example.com"),  # case + FQDN dot normalized
        ("http://example.com:8080/", "example.com"),  # port is not part of the rule
        ("https://sub_domain.example.com/", "sub_domain.example.com"),
        ("https://bücher.de/", "xn--bcher-kva.de"),  # Chromium resolves punycode
    ],
)
def test_pin_maps_the_audited_host_to_the_preflight_ip(url: str, expected_host: str) -> None:
    assert chromium_launch_args(url, "93.184.216.34") == [
        f"--host-resolver-rules=MAP {expected_host} 93.184.216.34"
    ]


@pytest.mark.parametrize(
    ("url", "pinned_ip"),
    [
        ("https://example.com/", PROXY_RESOLVES),  # a trusted proxy resolves it
        ("http://93.184.216.34/", "93.184.216.34"),  # IPv4 literal: no lookup
        ("http://[2606:2800:220:1::1]/", "93.184.216.34"),  # IPv6 literal
    ],
)
def test_nothing_to_pin_returns_no_args(url: str, pinned_ip: str) -> None:
    assert chromium_launch_args(url, pinned_ip) == []


@pytest.mark.parametrize(
    "url",
    [
        "http://evil.example,MAP*/",  # a comma would start a second rule
        "http://evil.example MAP * 127.0.0.1/",
        "http:///no-host",
    ],
)
def test_unpinnable_hostnames_are_refused(url: str) -> None:
    with pytest.raises(URLSafetyError):
        chromium_launch_args(url, "93.184.216.34")


def test_allowlisted_local_targets_pin_sanely(monkeypatch) -> None:
    """CLAUDE_SEO_LOCAL_TARGETS hands chromium_launch_args a non-public pin:
    localhost is mapped to it, an IP literal needs no rule."""
    monkeypatch.setenv("CLAUDE_SEO_LOCAL_TARGETS", "localhost:8080,127.0.0.1:8080")
    monkeypatch.delenv("CLAUDE_SEO_TRUST_PROXY", raising=False)
    fake = [(url_safety.socket.AF_INET, url_safety.socket.SOCK_STREAM, 6, "", ("127.0.0.1", 8080))]
    with patch.object(url_safety.socket, "getaddrinfo", return_value=fake):
        url, pinned = url_safety.validate_url_strict("http://localhost:8080/")
        assert chromium_launch_args(url, pinned) == [
            "--host-resolver-rules=MAP localhost 127.0.0.1"
        ]
        url, pinned = url_safety.validate_url_strict("http://127.0.0.1:8080/")
        assert chromium_launch_args(url, pinned) == []


def test_non_ip_pinned_address_is_refused() -> None:
    with pytest.raises(URLSafetyError, match="IP literal"):
        chromium_launch_args("https://example.com/", "example.org")


# ---------------------------------------------------------------------------
# The scripts hand the pin to Chromium, and fail closed when they cannot
# ---------------------------------------------------------------------------


class _LaunchCaptured(Exception):
    """Raised by the fake launch() so no further browser calls are needed."""


def _fake_sync_playwright(captured: dict):
    def launch(**kwargs):
        captured.update(kwargs)
        raise _LaunchCaptured

    playwright = SimpleNamespace(chromium=SimpleNamespace(launch=launch))

    class _Manager:
        def __enter__(self):
            return playwright

        def __exit__(self, *_args):
            return False

    return lambda: _Manager()


def _render(url_and_ip: tuple[str, str], captured: dict) -> dict:
    import render_page

    raw = SimpleNamespace(history=[], status_code=200, headers={}, url=url_and_ip[0])
    with patch.object(render_page, "validate_url_strict", return_value=url_and_ip), \
         patch.object(render_page, "safe_requests_get", return_value=raw), \
         patch.object(render_page, "decode_response_text", return_value="<div id=root></div>"), \
         patch.object(render_page, "sync_playwright", _fake_sync_playwright(captured)):
        return render_page.render_page(url_and_ip[0], mode="always", extract_content=False)


def test_render_page_launches_chromium_with_the_pin() -> None:
    captured: dict = {}
    _render(("https://app.example/", "93.184.216.34"), captured)
    assert captured["args"] == ["--host-resolver-rules=MAP app.example 93.184.216.34"]


def test_render_page_refuses_an_unpinnable_host_before_launch() -> None:
    captured: dict = {}
    result = _render(("https://app.example/", "not-an-ip"), captured)
    assert result["error"].startswith("url_safety:")
    assert captured == {}, "Chromium must not start for a host it cannot pin"
    # The raw fetch already succeeded; its answer is kept, as for any render failure.
    assert result["raw_fallback_available"] is True


def test_render_page_raw_mode_never_builds_the_pin() -> None:
    """mode='never' never starts Chromium, so an unpinnable host is no reason to refuse."""
    import render_page

    raw = SimpleNamespace(history=[], status_code=200, headers={}, url="https://app.example/")
    with patch.object(render_page, "validate_url_strict",
                      return_value=("https://app.example/", "not-an-ip")), \
         patch.object(render_page, "safe_requests_get", return_value=raw), \
         patch.object(render_page, "decode_response_text", return_value="<p>hi</p>"):
        result = render_page.render_page("https://app.example/", mode="never",
                                         extract_content=False)
    assert result["error"] is None
    assert result["mode_used"] == "raw"


@pytest.mark.parametrize(
    ("module_name", "call"),
    [
        ("capture_screenshot", lambda m, tmp: m.capture_screenshot(
            "https://app.example/", str(tmp / "shot.png"))),
        ("analyze_visual", lambda m, _tmp: m.analyze_visual("https://app.example/")),
    ],
)
def test_visual_scripts_launch_chromium_with_the_pin(module_name, call, tmp_path) -> None:
    pytest.importorskip("playwright")
    module = __import__(module_name)
    captured: dict = {}
    with patch.object(module, "validate_url_strict",
                      return_value=("https://app.example/", "93.184.216.34")), \
         patch.object(module, "sync_playwright", _fake_sync_playwright(captured)):
        call(module, tmp_path)
    assert captured["args"] == ["--host-resolver-rules=MAP app.example 93.184.216.34"]
