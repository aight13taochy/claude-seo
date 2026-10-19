#!/usr/bin/env python3
"""
Deterministic On-Page SEO and Images scores for full-audit envelopes.

Reads ``parse_html.py --json`` output for the crawled pages and scores the
two health-score categories that no subagent owns: On-Page SEO (20% of the
SEO Health Score) and Images (5%). With ``--write`` it merges both
categories into ``{domain}-audit/audit-data.json`` so ``audit_score.py``
computes the headline from them.

Why a script and not an agent
=============================
Every check below is a fact about the parsed HTML (is there one H1, is the
alt attribute set, is the title unique across the crawl). Counting facts
needs no judgment, so a script does it faster, at no model cost, without
network access, and gives the same score on every run. The criteria, the
weights and the reasons for each are in
``skills/seo-audit/references/score-criteria.md``.

Scoring
=======
Each check has a weight and a pass rate (passed / applicable). A check
that applies to nothing (no images, a single page for the uniqueness
checks) is left out and the other weights are rescaled. The category
score is ``sum(weight * rate) / sum(applicable weights) * 100``, rounded
half up. A category with no applicable check gets ``score: null`` so
``audit_score.py`` reports it as not scored instead of guessing.

Pages whose meta robots carry ``noindex`` are left out of On-Page SEO:
their titles and descriptions never reach a results page. 1x1 images
(tracking pixels) are left out of Images.

Out of scope, on purpose: canonical tags (Technical SEO owns them), image
file size (needs a network fetch; seo-images measures it), and anything
that needs rendering or reading the copy.

Input
=====
One or more JSON files, each holding a ``parse_html.py --json`` object, a
list of them, or ``{"pages": [...]}``. Run ``parse_html.py`` with
``--url`` so links are classified; a page with no classified link and no
``url`` key is not checked for internal links. A page is named by its
``url`` key when present, else by its file name.

Usage:
    python onpage_score.py audit/pages/*.json --json
    python onpage_score.py audit/pages/*.json --write example.com-audit/audit-data.json

Exit codes: 0 on success, 2 when no input file holds a usable page.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from urllib.parse import urlparse

_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import audit_score  # noqa: E402
import metadata_template  # noqa: E402

ONPAGE = "On-Page SEO"
IMAGES = "Images"

# (id, weight, severity, label, recommendation). Weights sum to 100.
ONPAGE_CHECKS = [
    ("title_present", 15, "High", "Missing title tag",
     "Give every indexable page a unique, descriptive <title>."),
    ("title_length", 8, "Low", "Title outside 30-60 characters",
     "Keep titles between 30 and 60 characters (aim for 50-60) so they are "
     "complete and not truncated in results."),
    ("title_unique", 10, "Medium", "Title shared with another page",
     "Rewrite duplicated titles so each page names its own topic."),
    ("description_present", 10, "Medium", "Missing meta description",
     "Write a meta description that summarises the page for searchers."),
    ("description_length", 5, "Low", "Meta description outside 70-160 characters",
     "Keep meta descriptions between 70 and 160 characters (aim for 150-160)."),
    ("description_unique", 7, "Medium", "Meta description shared with another page",
     "Write a distinct description per page instead of a site-wide default."),
    ("single_h1", 12, "Medium", "Page does not have exactly one H1",
     "Use one H1 that states the page topic; demote extra H1s to H2."),
    ("h2_structure", 5, "Low", "Long page without H2 subheadings",
     "Break pages of 300+ words into sections with H2 subheadings."),
    ("metadata_not_templated", 8, "High", "Templated title/description pair",
     "Replace the title echo and stock call to action with a page-specific "
     "summary (see metadata_template.py findings)."),
    ("internal_links", 10, "Medium", "Page has no internal links",
     "Link each page to related pages on the site so crawlers and users can "
     "move on from it."),
    ("open_graph", 10, "Low", "Incomplete Open Graph tags",
     "Set og:title, og:description and og:image so shared links render a card."),
]

IMAGE_CHECKS = [
    ("alt_present", 30, "High", "Image without an alt attribute",
     "Add alt text that describes the image, or alt=\"\" for purely "
     "decorative images."),
    ("alt_length", 15, "Low", "Alt text outside 10-125 characters",
     "Write alt text of 10-125 characters: specific enough to describe the "
     "image, short enough for screen readers."),
    ("dimensions", 20, "Medium", "Image without width and height",
     "Set width and height attributes so the browser reserves space and the "
     "layout does not shift (CLS)."),
    ("modern_format", 15, "Low", "Image not served as WebP, AVIF or SVG",
     "Serve photos as WebP or AVIF (with a fallback where needed). A CDN that "
     "negotiates the format behind a .jpg URL passes in practice; confirm "
     "with the response Content-Type."),
    ("lazy_offscreen", 10, "Low", "Below-the-fold image loaded eagerly",
     "Add loading=\"lazy\" to images further down the page."),
    ("first_image_eager", 5, "Medium", "First image is lazy-loaded",
     "Do not lazy-load the first (likely hero/LCP) image; it delays Largest "
     "Contentful Paint."),
    ("descriptive_filename", 5, "Low", "Non-descriptive image file name",
     "Rename files such as IMG_1234.jpg to words that describe the image."),
]

TITLE_RANGE = (30, 60)
DESCRIPTION_RANGE = (70, 160)
ALT_RANGE = (10, 125)
H2_MIN_WORDS = 300
EAGER_IMAGES = 3  # source-order images assumed near the top of the page
EXAMPLES = 3

_MODERN = {"webp", "avif", "svg"}
_LEGACY = {"jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff"}
_CAMERA_NAME_RE = re.compile(
    r"^(img|image|dsc|dscn|dcim|pxl|photo|pic|picture|screenshot|untitled|"
    r"unnamed|download|file)?[-_ ]?\d+$"
)
_HASH_NAME_RE = re.compile(r"^[0-9a-f]{16,}$")


def _read_json(path: str):
    """Load JSON written by a shell redirect: UTF-8, UTF-8 with BOM, or the
    UTF-16 that Windows PowerShell 5.1's ``>`` produces."""
    with open(path, "rb") as handle:
        raw = handle.read()
    encoding = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
    return json.loads(raw.decode(encoding))


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _norm(value: str) -> str:
    return " ".join(value.lower().split())


def _is_noindex(page: dict) -> bool:
    return "noindex" in _text(page.get("meta_robots")).lower()


def _extension(src: str) -> str:
    path = urlparse(src).path
    _, ext = os.path.splitext(path)
    return ext[1:].lower()


def _filename_stem(src: str) -> str:
    stem, _ = os.path.splitext(os.path.basename(urlparse(src).path))
    return stem.lower()


def _is_pixel(image: dict) -> bool:
    return str(image.get("width")).strip() == "1" and str(image.get("height")).strip() == "1"


def _is_lazy(image: dict) -> bool:
    method = image.get("lazy_method")
    if method is not None:
        return method != "none"
    return _text(image.get("loading")).lower() == "lazy"


class _Tally:
    """Pass/fail counts per check, with a few example failures each."""

    def __init__(self, checks):
        self.checks = checks
        self.counts = {cid: [0, 0] for cid, *_ in checks}
        self.examples = {cid: [] for cid, *_ in checks}

    def record(self, cid: str, passed: bool, where: str) -> None:
        self.counts[cid][1] += 1
        if passed:
            self.counts[cid][0] += 1
        elif len(self.examples[cid]) < EXAMPLES and where not in self.examples[cid]:
            self.examples[cid].append(where)

    def category(self, name: str, unit: str) -> dict:
        checks, findings, what_works = {}, [], []
        weighted, weight_total = 0.0, 0
        for cid, weight, severity, label, recommendation in self.checks:
            passed, applicable = self.counts[cid]
            rate = passed / applicable if applicable else None
            checks[cid] = {"passed": passed, "applicable": applicable,
                           "weight": weight, "rate": None if rate is None else round(rate, 3)}
            if rate is None:
                continue
            weighted += weight * rate
            weight_total += weight
            if passed == applicable:
                what_works.append(f"{cid}: {passed}/{applicable} {unit} pass")
                continue
            failed = applicable - passed
            findings.append({
                "title": label,
                "severity": severity,
                "description": f"{failed} of {applicable} {unit} fail this check "
                               f"(e.g. {', '.join(self.examples[cid])}).",
                "recommendation": recommendation,
                "check": cid,
            })
        score = None
        if weight_total:
            score = int(math.floor(weighted / weight_total * 100 + 0.5))
        return {
            "name": name,
            "score": score,
            "method": "deterministic",
            "score_source": "onpage_score.py",
            "what_works": what_works,
            "findings": findings,
            "checks": checks,
        }


def score_onpage(pages: list[dict]) -> dict:
    """On-Page SEO category from parse_html page dicts (``_label`` names each)."""
    tally = _Tally(ONPAGE_CHECKS)
    indexable = [p for p in pages if not _is_noindex(p)]
    titles, descriptions = {}, {}
    for page in indexable:
        for key, store in (("title", titles), ("meta_description", descriptions)):
            value = _norm(_text(page.get(key)))
            if value:
                store[value] = store.get(value, 0) + 1
    multi = len(indexable) > 1

    for page in indexable:
        where = page["_label"]
        title = _text(page.get("title"))
        description = _text(page.get("meta_description"))
        tally.record("title_present", bool(title), where)
        if title:
            tally.record("title_length", TITLE_RANGE[0] <= len(title) <= TITLE_RANGE[1], where)
            if multi:
                tally.record("title_unique", titles[_norm(title)] == 1, where)
        tally.record("description_present", bool(description), where)
        if description:
            tally.record("description_length",
                         DESCRIPTION_RANGE[0] <= len(description) <= DESCRIPTION_RANGE[1], where)
            if multi:
                tally.record("description_unique", descriptions[_norm(description)] == 1, where)
        if title and description:
            templated = metadata_template.analyse(title, description, page.get("url"))["templated"]
            tally.record("metadata_not_templated", not templated, where)

        h1 = page.get("h1") if isinstance(page.get("h1"), list) else []
        tally.record("single_h1", len(h1) == 1, where)
        words = page.get("word_count")
        if isinstance(words, int) and words >= H2_MIN_WORDS:
            h2 = page.get("h2") if isinstance(page.get("h2"), list) else []
            tally.record("h2_structure", bool(h2), where)

        links = page.get("links") if isinstance(page.get("links"), dict) else {}
        internal = links.get("internal") or []
        external = links.get("external") or []
        if page.get("url") or internal or external:
            tally.record("internal_links", bool(internal), where)

        og = page.get("open_graph") if isinstance(page.get("open_graph"), dict) else {}
        complete = all(_text(og.get(f"og:{k}")) for k in ("title", "description", "image"))
        tally.record("open_graph", complete, where)

    result = tally.category(ONPAGE, "pages")
    result["pages_scored"] = len(indexable)
    result["pages_skipped_noindex"] = len(pages) - len(indexable)
    return result


def score_images(pages: list[dict]) -> dict:
    """Images category from the ``images`` list of each parse_html page dict."""
    tally = _Tally(IMAGE_CHECKS)
    scored = 0
    for page in pages:
        images = [i for i in page.get("images") or [] if isinstance(i, dict) and not _is_pixel(i)]
        for index, image in enumerate(images):
            scored += 1
            src = _text(image.get("src"))
            where = f"{src or '(no src)'} on {page['_label']}"
            alt = image.get("alt")
            tally.record("alt_present", alt is not None, where)
            if isinstance(alt, str) and alt.strip():
                tally.record("alt_length", ALT_RANGE[0] <= len(alt.strip()) <= ALT_RANGE[1], where)
            tally.record("dimensions",
                         bool(_text(str(image.get("width") or ""))) and
                         bool(_text(str(image.get("height") or ""))), where)
            if index == 0:
                tally.record("first_image_eager", not _is_lazy(image), where)
            elif index >= EAGER_IMAGES:
                tally.record("lazy_offscreen", _is_lazy(image), where)
            if not src or src.startswith("data:"):
                continue
            ext = _extension(src)
            if ext in _MODERN or ext in _LEGACY:
                tally.record("modern_format", ext in _MODERN, where)
            stem = _filename_stem(src)
            if stem:
                descriptive = len(stem) >= 3 and not _CAMERA_NAME_RE.match(stem) \
                    and not _HASH_NAME_RE.match(stem)
                tally.record("descriptive_filename", descriptive, where)
    result = tally.category(IMAGES, "images")
    result["images_scored"] = scored
    return result


def load_pages(paths: list[str]) -> tuple[list[dict], list[str]]:
    """Read parse_html JSON files; return labelled pages and per-file errors."""
    pages, errors = [], []
    for path in paths:
        try:
            data = _read_json(path)
        except (OSError, ValueError) as exc:
            errors.append(f"{path}: {exc}")
            continue
        if isinstance(data, dict) and isinstance(data.get("pages"), list):
            data = data["pages"]
        rows = data if isinstance(data, list) else [data]
        usable = [r for r in rows if isinstance(r, dict) and ("title" in r or "images" in r)]
        if not usable:
            errors.append(f"{path}: no parse_html page object")
        for index, row in enumerate(usable):
            label = _text(row.get("url")) or (
                os.path.basename(path) if len(usable) == 1 else f"{os.path.basename(path)}#{index}"
            )
            pages.append({**row, "_label": label})
    return pages, errors


def merge_into(data: dict, categories: list[dict]) -> list[str]:
    """Merge scored categories into an audit-data dict; return the names written.

    An existing category with the same name keeps its other fields and any
    finding this script did not produce (an agent may have measured file
    sizes, say); its score is replaced. A category with no score is not
    written, so ``audit_score.py`` reports it as not scored.
    """
    existing = data.get("categories") if isinstance(data.get("categories"), list) else []
    written = []
    for category in categories:
        if category["score"] is None:
            continue
        key = audit_score._key(category["name"])
        match = next((c for c in existing if isinstance(c, dict)
                      and audit_score._key(c.get("name", "")) == key), None)
        if match is None:
            existing.append(category)
        else:
            ours = {f["title"] for f in category["findings"]}
            kept = [f for f in match.get("findings") or []
                    if isinstance(f, dict) and f.get("title") not in ours]
            match.update({k: v for k, v in category.items() if k != "findings"})
            match["findings"] = kept + category["findings"]
        written.append(category["name"])
    data["categories"] = existing
    return written


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Score On-Page SEO and Images from parse_html.py JSON output."
    )
    parser.add_argument("pages", nargs="+", help="parse_html.py --json output files.")
    parser.add_argument("--write", metavar="AUDIT_DATA",
                        help="Merge both categories into this audit-data.json.")
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout.")
    args = parser.parse_args()

    pages, errors = load_pages(args.pages)
    for error in errors:
        print(f"Warning: {error}", file=sys.stderr)
    if not pages:
        print("Error: no usable parse_html page in the input.", file=sys.stderr)
        return 2

    categories = [score_onpage(pages), score_images(pages)]
    result = {"pages_read": len(pages), "categories": categories, "written": []}

    if args.write:
        try:
            with open(args.write, encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            data = {"summary": {}, "categories": []}
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Error: cannot read {args.write}: {exc}", file=sys.stderr)
            return 2
        if not isinstance(data, dict):
            print("Error: audit data must be a JSON object.", file=sys.stderr)
            return 2
        result["written"] = merge_into(data, categories)
        audit_score._write_json(args.write, data)

    if args.json:
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        for category in categories:
            score = "not scored" if category["score"] is None else f"{category['score']}/100"
            print(f"{category['name']}: {score}")
            for finding in category["findings"]:
                print(f"  [{finding['severity']}] {finding['title']}: {finding['description']}")
        if result["written"]:
            print(f"Written to {args.write}: {', '.join(result['written'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
