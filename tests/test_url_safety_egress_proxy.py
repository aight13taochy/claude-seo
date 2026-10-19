"""
``url_safety.EgressGuardProxy`` lets a browser reach public addresses only.

A browser driven by a third-party tool (unlighthouse's Puppeteer and the
Lighthouse runs attached to it) has no route-handler hook, so its Chromium
sends every request through this proxy. These tests drive it with real
sockets: two loopback servers stand in for the audited (allowlisted) origin
and for an internal service the audited page must not reach.
"""

from __future__ import annotations

import http.server
import socket
import sys
import threading
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import url_safety  # noqa: E402
from url_safety import EgressGuardProxy, URLSafetyError  # noqa: E402


class _Server:
    """A loopback HTTP server that records the paths it was asked for."""

    def __init__(self) -> None:
        hits = self.hits = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args):
                return None

            def do_GET(self):
                hits.append((self.path, self.headers.get("Connection")))
                body = b"ok"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def servers():
    audited, internal = _Server(), _Server()
    yield audited, internal
    audited.close()
    internal.close()


def _get(proxy: EgressGuardProxy, url: str):
    proxies = {scheme: f"http://127.0.0.1:{proxy.port}" for scheme in ("http", "https")}
    session = requests.Session()
    session.trust_env = False  # the test's own proxy settings must not interfere
    try:
        return session.get(url, proxies=proxies, timeout=5, allow_redirects=False)
    except requests.RequestException as exc:
        return exc


def test_audited_origin_is_forwarded_one_request_per_connection(servers):
    audited, internal = servers
    with EgressGuardProxy(f"http://localhost:{audited.port}/", "127.0.0.1") as proxy:
        response = _get(proxy, f"http://localhost:{audited.port}/page?q=1")
    assert response.status_code == 200
    assert response.headers["Connection"] == "close"
    assert audited.hits == [("/page?q=1", "close")]
    assert proxy.refused == []


@pytest.mark.parametrize(
    "url_template",
    [
        "http://127.0.0.1:{internal}/x",       # another local port, as a literal
        "http://localhost:{internal}/x",       # the audited name on another port
        "https://127.0.0.1:{internal}/x",      # an HTTPS tunnel (CONNECT)
        "http://169.254.169.254/latest/",      # cloud metadata
        "http://[::ffff:127.0.0.1]:{internal}/x",
    ],
)
def test_everything_else_non_public_is_refused(servers, url_template):
    audited, internal = servers
    url = url_template.format(internal=internal.port)
    with EgressGuardProxy(f"http://localhost:{audited.port}/", "127.0.0.1") as proxy:
        response = _get(proxy, url)
    if isinstance(response, requests.Response):
        assert response.status_code == 403
    else:  # requests reports a refused CONNECT as a ProxyError
        assert isinstance(response, requests.exceptions.ProxyError)
    assert proxy.refused, "the refusal must be recorded"
    assert internal.hits == []


def test_a_rebinding_hostname_is_refused_before_any_connection(servers, monkeypatch):
    audited, internal = servers
    real = socket.getaddrinfo

    def fake(host, *args, **kwargs):
        if host == "rebind.example":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", internal.port))]
        return real(host, *args, **kwargs)

    monkeypatch.setattr(url_safety.socket, "getaddrinfo", fake)
    with EgressGuardProxy(f"http://localhost:{audited.port}/", "127.0.0.1") as proxy:
        response = _get(proxy, f"http://rebind.example:{internal.port}/x")
    assert response.status_code == 403
    assert internal.hits == []


def test_resolve_policy():
    proxy = EgressGuardProxy("https://example.com/", "93.184.215.14")
    # The audited host never re-resolves, on any port, when its pin is public.
    assert proxy.resolve("example.com", 443) == "93.184.215.14"
    assert proxy.resolve("EXAMPLE.com.", 8443) == "93.184.215.14"
    assert proxy.resolve("1.1.1.1", 443) == "1.1.1.1"
    for host in ("10.0.0.1", "127.0.0.1", "169.254.169.254", "metadata.google.internal"):
        with pytest.raises(URLSafetyError):
            proxy.resolve(host, 80)

    local = EgressGuardProxy("http://localhost:3000/", "127.0.0.1")
    assert local.resolve("localhost", 3000) == "127.0.0.1"
    with pytest.raises(URLSafetyError):
        local.resolve("localhost", 6379)


def test_chromium_args_route_loopback_through_the_proxy():
    with EgressGuardProxy("https://example.com/", "93.184.215.14") as proxy:
        args = proxy.chromium_args()
    assert args[0] == f"--proxy-server=http://127.0.0.1:{proxy.port}"
    assert "--proxy-bypass-list=<-loopback>" in args
