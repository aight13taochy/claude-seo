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
  - Builds the route list itself (see "SSRF bounds" below) and invokes
    ``npx --yes --package unlighthouse@0.13.5 unlighthouse-ci …`` with
    sensible defaults (mobile form factor, JSON reporter, generated
    config file).
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

SSRF bounds
===========
Unlighthouse reaches the audited site from two places: Node (axios, for
the start-up site check and each page's HTML) and its own Puppeteer
Chromium, to which every Lighthouse worker attaches by debugging port.
Both would otherwise resolve the host again after ``validate_url_strict``
checked it, and its crawler follows any link whose text merely contains
the site URL (``https://site@10.0.0.1/``) or sits on a subdomain. So:

  - Chromium gets ``url_safety.chromium_launch_args()`` through the
    config's ``puppeteerOptions.args``, which unlighthouse forwards to
    ``Cluster.launch()`` and on to ``puppeteer.launch()``
    (``launchPuppeteerCluster`` in @unlighthouse/core 0.13.5).
  - Node gets the same pin from ``node_dns_pin.cjs``, preloaded with
    ``NODE_OPTIONS=--require`` into every Node process of the run.
  - Unlighthouse never discovers routes. This script reads the site's
    sitemaps (or, without one, the home page's links) through url_safety
    and passes only same-origin URLs as the config's ``urls``, which turns
    off unlighthouse's sitemap, robots.txt and crawler discovery
    (``resolveReportableRoutes`` in @unlighthouse/core 0.13.5).

Residual risk: neither Chromium nor axios inside unlighthouse can be given
a per-request guard, so a redirect from the audited site to another host
or to a private IP literal is followed without re-validation. Every run
reports this in ``warnings``; see SECURITY.md.

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
from pathlib import Path
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
from url_safety import URLSafetyError, chromium_launch_args, validate_url_strict  # noqa: E402

UNLIGHTHOUSE_PIN = "unlighthouse@0.13.5"
NODE_DNS_PIN = os.path.join(_SCRIPTS_DIR, "node_dns_pin.cjs")
MAX_HOMEPAGE_BYTES = 5 * 1024 * 1024

RESIDUAL_RISK_WARNING = (
    "unlighthouse: the audited host is DNS-pinned and only same-origin URLs are "
    "scanned, but unlighthouse's Chromium and Node fetches have no per-request "
    "guard: a redirect from the site to another host or a private IP is followed "
    "without re-validation. Only audit sites you trust (see SECURITY.md)."
)

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
    *,
    urls: list[str] | None = None,
    chromium_args: list[str] | None = None,
) -> dict[str, Any]:
    """Build the object written to the generated unlighthouse config file.

    ``max_routes=None`` maps to ``scanner.maxRoutes: false`` (unlimited),
    matching the documented type ``number | false``. ``urls`` replaces
    unlighthouse's own route discovery; ``chromium_args`` is appended to
    Puppeteer's default Chromium flags.
    """
    config: dict[str, Any] = {
        "scanner": {"maxRoutes": max_routes if max_routes is not None else False},
        "puppeteerClusterOptions": {"timeout": page_timeout_ms},
    }
    if urls:
        config["urls"] = list(urls)
    if chromium_args:
        config["puppeteerOptions"] = {"args": list(chromium_args)}
    return config


def pin_resolution(target: str, pinned_ip: str) -> tuple[list[str], dict[str, str]]:
    """Chromium args and Node environment that pin the audited host.

    Both are empty when there is nothing to pin (an IP-literal target, or
    a trusted proxy resolving it). Raises ``URLSafetyError`` for a host
    that cannot be pinned, so the run fails closed.
    """
    chromium_args = chromium_launch_args(target, pinned_ip)
    if not chromium_args:
        return [], {}
    # "--host-resolver-rules=MAP <host> <ip>": chromium_launch_args has
    # already normalized the host (lowercase, punycode, no trailing dot)
    # and refused any containing a space, so the rule splits cleanly.
    _, host, ip = chromium_args[0].split(" ")
    return chromium_args, {"CLAUDE_SEO_PIN_HOST": host, "CLAUDE_SEO_PIN_IP": ip}


def build_env(pin_env: dict[str, str], base: dict[str, str] | None = None) -> dict[str, str]:
    """Subprocess environment that preloads ``node_dns_pin.cjs`` into Node.

    Any existing ``NODE_OPTIONS`` is kept. The preload path is quoted the
    way Node parses ``NODE_OPTIONS``, so a path with spaces still loads.
    """
    env = dict(os.environ if base is None else base)
    if not pin_env:
        return env
    quoted = NODE_DNS_PIN.replace("\\", "\\\\").replace('"', '\\"')
    env["NODE_OPTIONS"] = f'{env.get("NODE_OPTIONS", "")} --require "{quoted}"'.strip()
    env.update(pin_env)
    return env


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
        chromium_args, pin_env = pin_resolution(target, pinned_ip)
    except URLSafetyError as exc:
        return {"ok": False, "error": f"url_safety: {exc}"}

    node_err = _check_node()
    if node_err:
        return {"ok": False, "error": node_err}

    out_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(
        prefix="claude-seo-unlighthouse-"))
    out_dir.mkdir(parents=True, exist_ok=True)

    urls = discover_routes(target, max_routes)
    config = build_config(max_routes, page_timeout * 1000, urls=urls, chromium_args=chromium_args)
    config_path = write_config_file(out_dir, config)
    cmd = build_cmd(target, device=device, out_dir=out_dir, config_path=config_path)

    try:
        proc = subprocess.run(
            cmd,
            env=build_env(pin_env),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
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
        "scanned_urls": len(urls),
        "warnings": [RESIDUAL_RISK_WARNING],
        "stdout_tail": proc.stdout[-2000:] if proc.stdout else "",
        "stderr_tail": proc.stderr[-2000:] if proc.stderr else "",
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
