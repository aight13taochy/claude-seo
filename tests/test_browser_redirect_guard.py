"""
End-to-end: a refused redirect hop never leaves Chromium.

Playwright calls a ``page.route()`` handler for the first URL of a request
only, so before ``guard_browser`` Chromium followed a 30x to any address and
the render was discarded only after the request had been sent. These tests
run real Chromium against two local HTTP servers: the audited one, named in
``CLAUDE_SEO_LOCAL_TARGETS``, redirects to the other, which must never see a
request.

Skipped when Playwright or a launchable Chromium is missing (CI installs
neither).
"""

from __future__ import annotations

import http.server
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

sync_api = pytest.importorskip("playwright.sync_api")


def _chromium_launches() -> bool:
    try:
        with sync_api.sync_playwright() as p:
            p.chromium.launch(headless=True).close()
    except Exception:
        return False
    return True


pytestmark = pytest.mark.skipif(not _chromium_launches(), reason="Chromium cannot launch here")


class _Server:
    """A loopback HTTP server that records every path it is asked for."""

    def __init__(self, routes: dict) -> None:
        self.hits: list[str] = []
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args) -> None:
                pass

            def do_GET(self) -> None:  # noqa: N802 (http.server API)
                server.hits.append(self.path)
                location, body = routes.get(self.path, (None, b"<html><body>ok</body></html>"))
                if location:
                    self.send_response(302)
                    self.send_header("Location", location)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(body)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def servers(monkeypatch):
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY",
                 "all_proxy", "CLAUDE_SEO_TRUST_PROXY"):
        monkeypatch.delenv(name, raising=False)
    target = _Server({})
    audited = _Server({
        "/redirect": (f"http://localhost:{target.port}/hit", None),
        "/image": (None, b'<html><body>page<img src="/redirect"></body></html>'),
    })
    monkeypatch.setenv("CLAUDE_SEO_LOCAL_TARGETS", f"localhost:{audited.port}")
    yield audited, target
    audited.close()
    target.close()


def test_a_document_redirect_to_another_port_is_never_sent(servers, tmp_path) -> None:
    import capture_screenshot

    audited, target = servers
    shot = tmp_path / "shot.png"
    result = capture_screenshot.capture_screenshot(
        f"http://localhost:{audited.port}/redirect", str(shot), timeout=10000
    )
    assert result["success"] is False
    assert target.hits == []
    assert not shot.exists()


def test_a_subresource_redirect_is_blocked_and_the_page_still_renders(servers, tmp_path) -> None:
    import capture_screenshot

    audited, target = servers
    shot = tmp_path / "shot.png"
    result = capture_screenshot.capture_screenshot(
        f"http://localhost:{audited.port}/image", str(shot), timeout=10000
    )
    assert result["error"] is None
    assert result["success"] is True
    assert "/redirect" in audited.hits
    assert target.hits == []


def test_the_allowlisted_page_itself_renders(servers) -> None:
    import render_page

    audited, target = servers
    result = render_page.render_page(
        f"http://localhost:{audited.port}/", mode="always", extract_content=False
    )
    assert result["error"] is None
    assert result["mode_used"] == "rendered"
    assert "ok" in result["content"]
    assert target.hits == []
