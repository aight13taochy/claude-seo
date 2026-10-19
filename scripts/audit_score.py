#!/usr/bin/env python3
"""
SEO Health Score calculator for full-audit envelopes.

Recomputes ``summary.health_score`` in ``{domain}-audit/audit-data.json``
from the per-category scores, using the weights in ``WEIGHTS``. Those
weights are the single source of truth: the tables in
``skills/seo-audit/SKILL.md`` and ``skills/seo/SKILL.md`` restate them,
and a test keeps the three in step.

Why this exists
===============
The audit used to ask the model to "aggregate into SEO Health Score",
and ``google_report.py`` printed whatever number it wrote. Nothing
checked that the headline matched the category scores beneath it, so an
arithmetic slip reached the PDF title page unnoticed. This script makes
the headline a deterministic function of the categories.

Rules
=====
- Only the seven weighted categories count. Category names are matched
  loosely ("Schema & Structured Data" == "Schema / Structured Data",
  "Performance" == "Performance (CWV)").
- A weighted category with no usable score (missing, non-numeric, a bool,
  or outside 0-100) is left out, and the remaining weights are rescaled
  to 100. ``coverage`` reports the share of the weight that was scored,
  so a partial audit is visible instead of silently inflated or deflated.
- Categories without a weight (Backlink Profile, Local SEO, Search
  Experience, ...) are reported under ``unweighted`` and do not move the
  score.
- The score is rounded half up to an integer.

Usage:
    python audit_score.py example.com-audit/audit-data.json
    python audit_score.py audit-data.json --json
    python audit_score.py audit-data.json --write

Exit codes: 0 when the declared score matches (or ``--write`` stored the
computed one), 1 when the declared score differs from the computed one by
more than ``--tolerance`` points, 2 on unreadable input or when no
weighted category has a usable score.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile

WEIGHTS = {
    "Technical SEO": 22,
    "Content Quality": 23,
    "On-Page SEO": 20,
    "Schema / Structured Data": 10,
    "Performance (CWV)": 10,
    "AI Search Readiness": 10,
    "Images": 5,
}

DEFAULT_TOLERANCE = 2


def _key(name: str) -> str:
    """Normalise a category name for matching: drop "(...)", "&", "/", "and"."""
    text = re.sub(r"\([^)]*\)", " ", str(name).lower())
    words = [w for w in re.findall(r"[a-z0-9]+", text) if w != "and"]
    return " ".join(words)


_CANONICAL = {_key(name): name for name in WEIGHTS}


def _usable_score(value):
    """Return ``value`` as a float in 0-100, or a reason string when unusable."""
    if isinstance(value, bool) or value is None:
        return "missing"
    try:
        score = float(value)
    except (TypeError, ValueError):
        return "not a number"
    if math.isnan(score) or not 0 <= score <= 100:
        return "outside 0-100"
    return score


def compute_health_score(categories) -> dict:
    """Weighted health score from an audit-data ``categories`` list."""
    used, unweighted, invalid, seen = [], [], [], set()
    for category in categories if isinstance(categories, list) else []:
        if not isinstance(category, dict):
            continue
        name = category.get("name")
        canonical = _CANONICAL.get(_key(name)) if name is not None else None
        if canonical is None:
            if name is not None:
                unweighted.append(str(name))
            continue
        if canonical in seen:
            invalid.append({"name": str(name), "reason": "duplicate category"})
            continue
        score = _usable_score(category.get("score"))
        if isinstance(score, str):
            invalid.append({"name": str(name), "reason": score})
            continue
        seen.add(canonical)
        used.append({"name": canonical, "score": score, "weight": WEIGHTS[canonical]})

    weight_total = sum(item["weight"] for item in used)
    raw = (
        sum(item["score"] * item["weight"] for item in used) / weight_total
        if weight_total else None
    )
    return {
        "health_score": int(math.floor(raw + 0.5)) if raw is not None else None,
        "raw_score": round(raw, 2) if raw is not None else None,
        "coverage": round(weight_total / sum(WEIGHTS.values()), 2),
        "used": used,
        "missing": [name for name in WEIGHTS if name not in seen],
        "unweighted": unweighted,
        "invalid": invalid,
    }


def check_declared(data, tolerance: float = DEFAULT_TOLERANCE) -> dict:
    """Compare ``summary.health_score`` against the score the categories give."""
    data = data if isinstance(data, dict) else {}
    result = compute_health_score(data.get("categories"))
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    declared = _usable_score(summary.get("health_score"))
    declared = None if isinstance(declared, str) else declared
    result["declared"] = declared
    result["tolerance"] = tolerance
    if result["health_score"] is None:
        result["status"] = "no_categories"
        result["delta"] = None
    elif declared is None:
        result["status"] = "no_declared"
        result["delta"] = None
    else:
        result["delta"] = round(declared - result["raw_score"], 2)
        result["status"] = "mismatch" if abs(result["delta"]) > tolerance else "match"
    return result


def _write_json(path: str, data: dict) -> None:
    """Replace ``path`` atomically so an interrupted write never truncates it."""
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".audit-data.", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recompute the SEO Health Score of an audit-data.json envelope."
    )
    parser.add_argument("audit_data", help="Path to {domain}-audit/audit-data.json.")
    parser.add_argument(
        "--tolerance",
        type=float,
        default=DEFAULT_TOLERANCE,
        help=f"Points of difference allowed before exit 1 (default {DEFAULT_TOLERANCE}).",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Store the computed score in summary.health_score.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout.")
    args = parser.parse_args()

    try:
        with open(args.audit_data, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error: cannot read {args.audit_data}: {exc}", file=sys.stderr)
        return 2
    if not isinstance(data, dict):
        print("Error: audit data must be a JSON object.", file=sys.stderr)
        return 2

    result = check_declared(data, args.tolerance)
    result["written"] = False
    if args.write and result["health_score"] is not None:
        summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        summary["health_score"] = result["health_score"]
        data["summary"] = summary
        _write_json(args.audit_data, data)
        result["written"] = True

    if args.json:
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"Computed score: {result['health_score']} "
              f"(coverage {result['coverage']:.0%} of the weight)")
        print(f"Declared score: {result['declared']}")
        print(f"Status:         {result['status']}"
              + (" (written)" if result["written"] else ""))
        for item in result["used"]:
            print(f"  {item['name']:<26} {item['score']:>6g} x {item['weight']}%")
        if result["missing"]:
            print(f"  Not scored: {', '.join(result['missing'])}")
        for item in result["invalid"]:
            print(f"  Ignored {item['name']}: {item['reason']}")
        if result["unweighted"]:
            print(f"  Unweighted (not in the score): {', '.join(result['unweighted'])}")

    if result["health_score"] is None:
        print("Error: no weighted category has a usable score.", file=sys.stderr)
        return 2
    if result["status"] == "mismatch" and not result["written"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
