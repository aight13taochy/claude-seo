#!/usr/bin/env python3
"""
Apply the automated content signals to a Content Quality score, once.

The seo-content agent scores a page by reading it (the E-E-A-T rows, 0-100
in total). ``content_quality.py`` and ``content_verify.py`` then measure
filler, AI-typical phrasing, repetition, information density and uncited
claims. This script is the single place those measurements move the
number: it takes the agent's reading score as the base and subtracts a
bounded, itemised penalty. The agent must not also deduct for them in the
E-E-A-T rows, or the same signal would count twice.

Rules (the reasons are in skills/seo-audit/references/score-criteria.md)
==========================================================================
- Penalty only. A detector never raises a score: its phrase lists have
  known false negatives, so a clean result proves nothing, and text written
  to dodge the lists must not earn points.
- Capped at ``MAX_PENALTY`` points in total, so heuristic false positives
  cannot outweigh the reading. The score never drops below 0.
- Gated where the signal is noise: the phrase lists are English-only, so
  a non-English page (``--lang``) or CJK text (``coverage`` in the quality
  JSON) gets no penalty; per-1000-token rates are skipped under
  ``MIN_TOKENS`` tokens; the uncited share is skipped under ``MIN_CLAIMS``
  claims.
- Thin content is not penalised here: the agent already judges length
  against the page type's minimum.
- Every applied or skipped penalty is listed with its reason and fix.

Usage:
    python content_score.py --base 78 --quality quality.json --verify verify.json --json
    python content_score.py --base 78 --quality quality.json --lang fr

Exit codes: 0 on success, 2 on unusable input.
"""

from __future__ import annotations

import argparse
import json
import math
import sys

MAX_PENALTY = 15
MIN_TOKENS = 300
MIN_CLAIMS = 3

# flag from content_quality.py -> (points, reason, fix)
FLAG_PENALTIES = {
    "ai-patterns": (
        4,
        "AI-typical phrasing above the threshold (QRG: scaled or low-effort main content).",
        "Rewrite the matched phrases with specific, first-hand detail.",
    ),
    "filler": (
        3,
        "Filler phrases above the threshold (QRG: little-to-no value padding).",
        "Cut the padding phrases listed under matches.filler.",
    ),
    "repetitive": (
        3,
        "Repeated sentences or n-grams (QRG: repetitive, low-effort content).",
        "Merge or remove the repeated passages.",
    ),
    "low-density": (
        2,
        "Few named entities or figures per token (generic, unspecific text).",
        "Add concrete names, numbers, dates and examples.",
    ),
}
# (minimum uncited ratio, points); the first match wins.
UNCITED_STEPS = ((0.7, 6), (0.4, 3))
UNCITED_FIX = "Cite a source in the sentence of each uncited claim, or remove the claim."


def _round(value: float) -> int:
    return int(math.floor(value + 0.5))


def adjust(base: float, quality: dict | None = None, verify: dict | None = None,
           lang: str = "en") -> dict:
    """Return the adjusted score and the itemised penalties."""
    applied, skipped = [], []
    english = (lang or "en").lower().split("-")[0] == "en"

    if quality is not None:
        flags = [f for f in quality.get("flags") or [] if f in FLAG_PENALTIES]
        tokens = quality.get("tokens")
        if not english:
            reason = f"page language '{lang}': phrase lists are English-only"
        elif quality.get("coverage"):
            reason = "CJK text: phrase lists and density do not apply"
        elif not isinstance(tokens, int) or tokens < MIN_TOKENS:
            reason = f"{tokens} tokens: under {MIN_TOKENS}, per-1000-token rates are noise"
        else:
            reason = None
        for flag in flags:
            points, why, fix = FLAG_PENALTIES[flag]
            if reason:
                skipped.append({"signal": flag, "reason": reason})
            else:
                applied.append({"signal": flag, "points": points, "reason": why, "fix": fix})

    if verify is not None:
        claims = verify.get("claim_count")
        ratio = verify.get("uncited_ratio")
        points = next((p for floor, p in UNCITED_STEPS
                       if isinstance(ratio, (int, float)) and ratio > floor), 0)
        if points:
            if not english:
                skipped.append({"signal": "uncited-claims",
                                "reason": f"page language '{lang}': claim triggers are English-only"})
            elif not isinstance(claims, int) or claims < MIN_CLAIMS:
                skipped.append({"signal": "uncited-claims",
                                "reason": f"{claims} claims: under {MIN_CLAIMS}, one claim swings the share"})
            else:
                applied.append({
                    "signal": "uncited-claims",
                    "points": points,
                    "reason": f"{verify.get('uncited_count')} of {claims} verifiable claims "
                              f"have no nearby citation (ratio {ratio}).",
                    "fix": UNCITED_FIX,
                })

    raw_penalty = sum(item["points"] for item in applied)
    penalty = min(raw_penalty, MAX_PENALTY)
    return {
        "base_score": base,
        "penalty": penalty,
        "penalty_uncapped": raw_penalty,
        "max_penalty": MAX_PENALTY,
        "adjusted_score": max(0, _round(base - penalty)),
        "applied": applied,
        "skipped": skipped,
        "method": "deterministic",
    }


def _read_json(path: str):
    """Load JSON written by a shell redirect: UTF-8, UTF-8 with BOM, or the
    UTF-16 that Windows PowerShell 5.1's ``>`` produces."""
    with open(path, "rb") as handle:
        raw = handle.read()
    encoding = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
    return json.loads(raw.decode(encoding))


def _load(path: str | None):
    if path is None:
        return None
    data = _read_json(path)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply content_quality/content_verify penalties to a Content Quality score."
    )
    parser.add_argument("--base", type=float, required=True,
                        help="Content Quality score from reading the page (0-100).")
    parser.add_argument("--quality", help="content_quality.py --json output.")
    parser.add_argument("--verify", help="content_verify.py --json output.")
    parser.add_argument("--lang", default="en",
                        help="Page language (html lang), e.g. en, en-GB, fr. Default en.")
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout.")
    args = parser.parse_args()

    if math.isnan(args.base) or not 0 <= args.base <= 100:
        print("Error: --base must be between 0 and 100.", file=sys.stderr)
        return 2
    try:
        quality, verify = _load(args.quality), _load(args.verify)
    except (OSError, ValueError) as exc:
        print(f"Error: cannot read detector output: {exc}", file=sys.stderr)
        return 2

    result = adjust(args.base, quality, verify, args.lang)
    if args.json:
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"Content Quality: {result['adjusted_score']}/100 "
              f"(base {result['base_score']:g}, penalty {result['penalty']}"
              f"{' capped' if result['penalty_uncapped'] > result['penalty'] else ''})")
        for item in result["applied"]:
            print(f"  -{item['points']} {item['signal']}: {item['reason']} Fix: {item['fix']}")
        for item in result["skipped"]:
            print(f"  skipped {item['signal']}: {item['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
