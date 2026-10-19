#!/usr/bin/env python3
"""
Thin wrapper around the Unlighthouse CLI (https://unlighthouse.dev).

Unlighthouse is an MIT-licensed OSS Lighthouse runner that crawls an
entire site and outputs a single aggregate report. It's the closest
free-tier equivalent to running PageSpeed against every URL on a site
and aggregating the results: a workflow PSI's API quota does not
support without a paid Google Cloud bill.

This wrapper:
  - Validates the target via url_safety before any subprocess starts.
  - Pins the audited host to the validated IP in every process that can
    reach the network (see "SSRF and DNS rebinding" below).
  - Invokes ``npx --yes unlighthouse-ci@0.13.5 …`` with sensible
    defaults (mobile form factor, JSON reporter, generated config file).
  - Captures the JSON result the CLI writes and returns it parsed,
    normalized to a flat route list regardless of which reporter shape
    produced it, so claude-seo agents can ingest the result without
    re-running Lighthouse.

Route cap and per-page timeout
===============================
The unlighthouse-ci CLI (a ``cac``-based parser, see
``packages/cli/src/{createCli,ci,util}.ts`` upstream) has no
``--max-routes`` flag and does not read an arbitrary ``--scanner``
argument at all: unrecognised flags are silently dropped by
``pickOptions()``. The only CLI-documented way to reach
``scanner.maxRoutes`` is ``--config-file <path>``, a config module
loaded via c12 (https://unlighthouse.dev/integrations/cli,
https://unlighthouse.dev/api/config). This wrapper generates a small
``unlighthouse.config.mjs`` and passes it with ``--config-file``.

The same generated config sets ``puppeteerClusterOptions.timeout``
(milliseconds), which unlighthouse forwards to ``Cluster.launch()``
(puppeteer-cluster) as the per-page task timeout: a documented pass
-through (https://unlighthouse.dev/api/config#puppeteerclusteroptions).
This guards against a single hung page consuming the whole crawl's
time budget, independent of the subprocess-level ``--timeout``.

SSRF and DNS rebinding
======================
Unlighthouse resolves DNS and follows redirects on its own, in two places
Python's url_safety cannot reach:

- **Chromium** (Puppeteer, and every Lighthouse run, which attaches to the
  same browser through its DevTools port). The generated config passes
  ``puppeteerOptions.args = chromium_launch_args(target, pinned_ip)``,
  forwarded to ``puppeteer.launch()`` via puppeteer-cluster
  (https://unlighthouse.dev/api/config#puppeteeroptions), so the audited
  host always connects to the pre-flight IP.
- **Node** (axios for robots.txt, sitemaps and every crawled route; got for
  sitemaps). ``scripts/node_net_guard.cjs`` is preloaded through
  ``NODE_OPTIONS=--require``: it pins the audited host and refuses any
  connection to a non-public address, including redirects to IP literals
  such as ``169.254.169.254``.

Unlighthouse's own route discovery is switched off. Its crawler queues any
link whose text merely contains the site URL (``https://site@10.0.0.1/``)
or sits on a subdomain, and Lighthouse would load those routes in Chromium,
which has no per-request guard and pins only the audited host. This script
reads the site's sitemaps (or, without one, the target page's links)
through url_safety and passes only URLs with the target's exact scheme,
host and port as the config's ``urls``, which turns off unlighthouse's
sitemap, robots.txt and crawler discovery (``resolveReportableRoutes`` in
@unlighthouse/core 0.13.5).

Residual risk: loopback stays reachable from Node (Puppeteer and Lighthouse
need Chromium's DevTools port on 127.0.0.1), and Chromium follows a
redirect from the audited site, and loads third-party hosts, with no
per-request guard. Every run reports this in ``warnings``. With a trusted proxy
(``CLAUDE_SEO_TRUST_PROXY``) there is no local resolver to rebind and
neither pin is applied, as in the other browser paths.

Prerequisites
=============
Node.js 18+ available on ``$PATH``. The first run downloads
unlighthouse; subsequent runs use the npx cache.

Usage::

    python scripts/unlighthouse_run.py https://example.com
    python scripts/unlighthouse_run.py https://example.com --json
    python scripts/unlighthouse_run.py https://example.com --device desktop --max-routes 50
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
from collections import deque
from pathlib import Path, PurePath
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse

import lxml.html
from lxml import etree

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
from sitemap_discovery import (  # noqa: E402
    MAX_DECLARED,
    MAX_ROBOTS_BYTES,
    MAX_SITEMAP_BYTES,
    _bounded_fetch,
    _robots_sitemaps,
)
from url_safety import (  # noqa: E402
    PROXY_RESOLVES,
    URLSafetyError,
    chromium_launch_args,
    normalize_hostname,
    validate_url_strict,
)

UNLIGHTHOUSE_PIN = "unlighthouse@0.13.5"
NODE_NET_GUARD = Path(_SCRIPTS_DIR) / "node_net_guard.cjs"
MAX_HOMEPAGE_BYTES = 5 * 1024 * 1024

RESIDUAL_RISK_WARNING = (
    "unlighthouse: the audited host is DNS-pinned and only same-origin URLs are "
    "scanned, but Chromium follows a redirect from the site to another host or a "
    "private IP without re-validation, and Node can still reach loopback. Only "
    "audit sites you trust (see SECURITY.md)."
)
# Proxies npm (npx) may connect through; the Node guard must not block them.
# Matched case-insensitively: Windows upper-cases every os.environ key.
_PROXY_ENV_KEYS = frozenset({
    "https_proxy", "http_proxy", "all_proxy", "npm_config_proxy", "npm_config_https_proxy",
})

# Numeric metadata keys that are not per-category scores; excluded from
# aggregate score averaging so a route's `score` (the Lighthouse overall
# score) doesn't get double-counted alongside its category scores.
_NON_CATEGORY_NUMERIC_KEYS = frozenset({"score"})


def _check_node() -> str | None:
    """Return None if Node is OK, else an error message."""
    npx = shutil.which("npx")
    if not npx:
        return ("npx not found on PATH. Install Node.js 18+ "
                "(https://nodejs.org) and re-run.")
    return None


def build_config(
    max_routes: int | None,
    page_timeout_ms: int,
    chromium_args: list[str] | None = None,
    *,
    urls: list[str] | None = None,
) -> dict[str, Any]:
    """Build the object written to the generated unlighthouse config file.

    ``max_routes=None`` maps to ``scanner.maxRoutes: false`` (unlimited),
    matching the documented type ``number | false``. ``chromium_args`` (from
    ``chromium_launch_args``) go to ``puppeteerOptions.args``; ``urls``
    replaces unlighthouse's own route discovery.
    """
    config: dict[str, Any] = {
        "scanner": {"maxRoutes": max_routes if max_routes is not None else False},
        "puppeteerClusterOptions": {"timeout": page_timeout_ms},
    }
    if chromium_args:
        config["puppeteerOptions"] = {"args": list(chromium_args)}
    if urls:
        config["urls"] = list(urls)
    return config


def _origin_key(url: str) -> tuple[str, str, int] | None:
    """(scheme, host, port) of an http(s) URL without userinfo, else None."""
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return None
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https") or not parsed.hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    return scheme, parsed.hostname.rstrip("."), port or (443 if scheme == "https" else 80)


def _sitemap_locs(content: bytes) -> tuple[str | None, list[str]]:
    """Root element name and ``<loc>`` values of a sitemap or sitemap index."""
    if b"<!DOCTYPE" in content.upper():
        return None, []
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, load_dtd=False, recover=False, huge_tree=False,
    )
    try:
        root = etree.fromstring(content, parser=parser)
    except (etree.XMLSyntaxError, ValueError):
        return None, []
    locs = [
        el.text.strip()
        for el in root.iter()
        if isinstance(el.tag, str) and etree.QName(el).localname == "loc" and el.text
    ]
    return etree.QName(root).localname.lower(), locs


def _fetched_ok(result: dict) -> bool:
    status = result["status_code"]
    return not result["error"] and not result["too_large"] and status is not None and 200 <= status < 300


def discover_routes(target: str, max_routes: int | None) -> list[str]:
    """Same-origin URLs to scan, starting with ``target``.

    Reads robots.txt ``Sitemap:`` lines and ``/sitemap.xml`` (following up
    to ``MAX_DECLARED`` sitemap files, including index children), falling
    back to the links on the target page when no sitemap lists a page.
    Every fetch goes through url_safety; only URLs with the target's exact
    scheme, host and port are kept, so unlighthouse never leaves the
    pinned host.
    """
    key = _origin_key(target)
    routes = [target]
    if key is None:
        return routes

    def full() -> bool:
        return max_routes is not None and len(routes) >= max_routes

    def add(url: str) -> None:
        url = urldefrag(url.strip())[0]
        if not full() and _origin_key(url) == key and url not in routes:
            routes.append(url)

    scheme, host, port = key
    default_port = 443 if scheme == "https" else 80
    origin = f"{scheme}://{host}" + ("" if port == default_port else f":{port}")
    queue = deque([f"{origin}/sitemap.xml"])
    robots = _bounded_fetch(f"{origin}/robots.txt", MAX_ROBOTS_BYTES)
    if _fetched_ok(robots):
        declared = [u for u in _robots_sitemaps(robots["content"]) if _origin_key(u) == key]
        queue.extendleft(reversed(declared))

    seen: set[str] = set()
    while queue and not full() and len(seen) < MAX_DECLARED:
        sitemap_url = queue.popleft()
        if sitemap_url in seen:
            continue
        seen.add(sitemap_url)
        fetched = _bounded_fetch(sitemap_url, MAX_SITEMAP_BYTES)
        if not _fetched_ok(fetched):
            continue
        kind, locs = _sitemap_locs(fetched["content"])
        if kind == "sitemapindex":
            queue.extend(loc for loc in locs if _origin_key(loc) == key)
        elif kind == "urlset":
            for loc in locs:
                add(loc)

    if len(routes) == 1 and not full():
        page = _bounded_fetch(target, MAX_HOMEPAGE_BYTES)
        if _fetched_ok(page) and page["content"].strip():
            try:
                hrefs = lxml.html.fromstring(page["content"]).xpath("//a/@href")
            except (etree.ParserError, ValueError):
                hrefs = []
            for href in hrefs:
                add(urljoin(target, str(href)))
    return routes


def node_require_option(path: PurePath) -> str:
    """``--require "<path>"`` quoted the way Node parses NODE_OPTIONS.

    Inside double quotes Node treats a backslash as an escape, so Windows
    paths need their backslashes doubled; spaces stay inside the quotes.
    """
    escaped = str(path).replace("\\", "\\\\").replace('"', '\\"')
    return f'--require "{escaped}"'


def build_guard_env(target: str, pinned_ip: str, base_env: dict[str, str]) -> dict[str, str]:
    """Environment that preloads ``node_net_guard.cjs`` into every Node process.

    Returns ``base_env`` unchanged when a trusted proxy resolves the target
    (``PROXY_RESOLVES``): there is no local resolver to rebind. The proxy
    hosts npm may need are passed as ``CLAUDE_SEO_NET_ALLOW``.
    """
    env = dict(base_env)
    if pinned_ip == PROXY_RESOLVES:
        return env
    host = normalize_hostname(urlparse(target).hostname or "")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        pass
    allow = set()
    for key, value in env.items():
        if key.lower() not in _PROXY_ENV_KEYS or not value:
            continue
        proxy_host = urlparse(value if "://" in value else f"http://{value}").hostname
        if proxy_host:
            allow.add(proxy_host.lower())
    require = node_require_option(NODE_NET_GUARD)
    env["NODE_OPTIONS"] = f"{env.get('NODE_OPTIONS', '')} {require}".strip()
    env["CLAUDE_SEO_NET_GUARD"] = "1"
    env["CLAUDE_SEO_PIN_HOST"] = host
    env["CLAUDE_SEO_PIN_IP"] = pinned_ip
    env["CLAUDE_SEO_NET_ALLOW"] = ",".join(sorted(allow))
    return env


def write_config_file(out_dir: Path, config: dict[str, Any]) -> Path:
    """Write an ESM config module unlighthouse-ci loads via --config-file.

    A ``.mjs`` module (rather than ``.ts``) avoids depending on the TS
    loader unlighthouse's config resolver (c12) pulls in on demand.
    """
    config_path = out_dir / "unlighthouse.config.mjs"
    config_path.write_text(f"export default {json.dumps(config)}\n", encoding="utf-8")
    return config_path


def build_cmd(target: str, *, device: str, out_dir: Path, config_path: Path) -> list[str]:
    """Build the unlighthouse-ci argv. Every flag here is documented in
    ``packages/cli/src/createCli.ts`` and ``packages/cli/src/ci.ts`` upstream.
    """
    return [
        "npx", "--yes", "--package", UNLIGHTHOUSE_PIN, "unlighthouse-ci",
        "--site", target,
        "--desktop" if device == "desktop" else "--mobile",
        "--output-path", str(out_dir),
        "--config-file", str(config_path),
        # The real flag is `--build-static` (ci.ts); the CLI declares it
        # with a required value placeholder, so pass it explicitly.
        "--build-static", "true",
    ]


def _route_scores(route: dict[str, Any]) -> dict[str, float]:
    """Extract per-category numeric scores from one route result.

    Handles both reporter shapes:
      - jsonSimple/json (the CLI default): flat numeric keys alongside
        `path`, e.g. {"path": "/", "score": 0.9, "performance": 0.9, ...}.
      - jsonExpanded: nested {"categories": {key: {"score": 0.9, ...}}}.
    """
    scores: dict[str, float] = {}
    categories = route.get("categories")
    if isinstance(categories, dict):
        for key, cat in categories.items():
            if isinstance(cat, dict) and isinstance(cat.get("score"), (int, float)):
                scores[key] = float(cat["score"])
    for key, value in route.items():
        if key in _NON_CATEGORY_NUMERIC_KEYS or key in ("categories", "metrics", "path"):
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            scores[key] = float(value)
    return scores


def normalize_ci_result(data: Any) -> dict[str, Any]:
    """Normalize a parsed ``ci-result.json`` payload into a stable shape.

    The default unlighthouse-ci reporter (``jsonSimple``, used whenever
    ``--reporter`` isn't passed) writes the file as a flat JSON ARRAY of
    per-route dicts, not an object. A ``jsonExpanded`` reporter instead
    writes ``{"summary": ..., "routes": [...], "metadata": ...}``. Both
    shapes are accepted; anything else degrades to an empty route list
    rather than raising.
    """
    if isinstance(data, list):
        routes = [r for r in data if isinstance(r, dict)]
    elif isinstance(data, dict):
        candidate = data.get("routes")
        routes = [r for r in candidate if isinstance(r, dict)] if isinstance(candidate, list) else []
    else:
        routes = []

    per_category: dict[str, list[float]] = {}
    for route in routes:
        for key, value in _route_scores(route).items():
            per_category.setdefault(key, []).append(value)

    aggregate_scores = {
        key: round(statistics.median(values), 4)
        for key, values in per_category.items()
        if values
    }

    return {
        "routes": routes,
        "route_count": len(routes),
        "aggregate_scores": aggregate_scores,
    }


def run(
    target: str,
    *,
    device: str = "mobile",
    max_routes: int | None = 200,
    output_dir: str | None = None,
    timeout: int = 600,
    page_timeout: int = 60,
) -> dict:
    try:
        target, pinned_ip = validate_url_strict(target)
        chromium_args = chromium_launch_args(target, pinned_ip)
    except URLSafetyError as exc:
        return {"ok": False, "error": f"url_safety: {exc}"}

    node_err = _check_node()
    if node_err:
        return {"ok": False, "error": node_err}

    out_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(
        prefix="claude-seo-unlighthouse-"))
    out_dir.mkdir(parents=True, exist_ok=True)

    urls = discover_routes(target, max_routes)
    config = build_config(max_routes, page_timeout * 1000, chromium_args, urls=urls)
    config_path = write_config_file(out_dir, config)
    cmd = build_cmd(target, device=device, out_dir=out_dir, config_path=config_path)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=build_guard_env(target, pinned_ip, dict(os.environ)),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"unlighthouse timed out after {timeout}s",
                "output_dir": str(out_dir)}
    except FileNotFoundError as exc:
        return {"ok": False, "error": f"npx invocation failed: {exc}"}

    summary_path = out_dir / "ci-result.json"
    normalized: dict[str, Any] = {"routes": [], "route_count": 0, "aggregate_scores": {}}
    raw_summary: Any = None
    if summary_path.is_file():
        try:
            raw_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": f"ci-result.json invalid JSON: {exc}",
                    "output_dir": str(out_dir)}
        normalized = normalize_ci_result(raw_summary)

    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "target": target,
        "output_dir": str(out_dir),
        "summary": raw_summary,
        "routes": normalized["routes"],
        "route_count": normalized["route_count"],
        "aggregate_scores": normalized["aggregate_scores"],
        "stdout_tail": proc.stdout[-2000:] if proc.stdout else "",
        "stderr_tail": proc.stderr[-2000:] if proc.stderr else "",
        "scanned_urls": len(urls),
        "warnings": [RESIDUAL_RISK_WARNING],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Unlighthouse (multi-page Lighthouse) on a site."
    )
    parser.add_argument("target", help="Site URL to crawl (https://example.com).")
    parser.add_argument(
        "--device", choices=("mobile", "desktop"), default="mobile",
    )
    parser.add_argument(
        "--max-routes", type=int, default=200,
        help="Cap the crawl at N URLs (default 200).",
    )
    parser.add_argument(
        "--output-dir", help="Directory for the HTML/JSON report (default temp).",
    )
    parser.add_argument(
        "--timeout", type=int, default=600,
        help="Overall subprocess timeout in seconds (default 600).",
    )
    parser.add_argument(
        "--page-timeout", type=int, default=60,
        help="Per-page Lighthouse task timeout in seconds (default 60). Guards "
             "against one hung page stalling the whole crawl.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = run(
        args.target,
        device=args.device,
        max_routes=args.max_routes,
        output_dir=args.output_dir,
        timeout=args.timeout,
        page_timeout=args.page_timeout,
    )

    for warning in result.get("warnings", []):
        print(f"WARNING: {warning}", file=sys.stderr)

    if args.json:
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        status = "OK" if result["ok"] else "FAIL"
        print(f"Unlighthouse: {status}")
        print(f"  Target:     {result.get('target', args.target)}")
        print(f"  Output dir: {result.get('output_dir')}")
        if result.get("error"):
            print(f"  Error:      {result['error']}")
        else:
            print(f"  Routes:     {result.get('route_count', 0)}")
            for k, v in (result.get("aggregate_scores") or {}).items():
                print(f"  {k:14s} {v}")

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
