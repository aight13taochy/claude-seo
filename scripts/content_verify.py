#!/usr/bin/env python3
"""
Claim extractor + citation-gap detector.

Surfaces *verifiable claims* in a body of text and reports which ones
lack a nearby citation marker. Designed for the v2 ``/seo content
verify`` workflow: a fact-check pass on drafts before publish.

What counts as a claim
======================
- Statistical:  "47% of marketers report …"
- Quantitative: "200 million users", "$3.2 billion in revenue"
- Authority:    "according to a Stanford study"
- Temporal:     "in 2025, …", "by 2030 …"
- Comparative:  "twice as effective", "3x faster"

What counts as a citation marker
================================
A marker counts only inside the claim's own sentence, or in a
"Source:"/"Via:"/"Cited in" line that directly follows it. A link two
sentences away does not cite the claim.

- A markdown/HTML link: `[Source](https://…)`
- A footnote-style reference: `[^1]` or `[1]`
- An inline attribution to a named source: "per Gartner", "according to
  Forrester", "according to a Stanford study" (a capitalised name must
  follow, after an optional article; "according to a survey" and "per day"
  do not count)
- A schema.org Citation block (rough detection of `@type`: `"Citation"`);
  like every marker it must sit in the claim's sentence, so a JSON-LD block
  elsewhere on the page does not cite anything

Output JSON::

    {
      "claims": [
        {
          "text": "…",
          "kind": "statistic|quantity|authority|temporal|comparative",
          "position": <char offset>,
          "has_citation": bool,
          "nearby_citation": "…" or None
        },
        …
      ],
      "claim_count": int,
      "uncited_count": int,
      "uncited_ratio": 0..1,
      "coverage":      present only for CJK-dominant or other non-Latin-
                       alphabetic-dominant text (Greek, Cyrillic, ...), e.g.
                       {"script": "cjk"|"non_latin_alphabetic",
                        "claim_patterns": "english_only"}: the claim
                       patterns above key on English words ("of", "million",
                       "in 2025", "times") or Latin-cased attribution
                       ("Per Gartner"), so a low claim_count in one of these
                       scripts means this tool found nothing to check, not
                       that the draft has no unsupported claims.
    }

The script is *advisory*: it does not check whether a citation actually
exists. The signal is whether the author bothered to anchor each
claim. The uncited_ratio field is this tool's internal heuristic,
inspired by QRG trust expectations, not a Google rater metric.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Claim patterns. Each is (regex, label). Order matters: first match
# wins per substring so a "47% of users" doesn't double-count as both
# statistic and quantity. Trailing-word groups are restricted to
# [a-zA-Z]+ so a greedy match cannot cross a sentence boundary into the
# next claim (e.g. "47% of marketers do X. 60%" must not collapse to a
# single match).
_CLAIM_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\b\d+(?:\.\d+)?\s*%\s+of\s+[a-zA-Z]+(?:\s+[a-zA-Z]+){0,4}",
                re.IGNORECASE),
     "statistic"),
    # "%" is not a word character, so a trailing \b never matched before a
    # space or period: "rose 40% per year." produced no claim at all.
    (re.compile(r"\b\d+(?:\.\d+)?\s*%(?!\w)"), "statistic"),
    (re.compile(r"\$\s?\d+(?:\.\d+)?\s*(?:million|billion|trillion|k|M|B)\b",
                re.IGNORECASE), "quantity"),
    (re.compile(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\s+\w+", re.IGNORECASE),
     "quantity"),
    (re.compile(r"\b\d+(?:\.\d+)?\s*(?:million|billion|trillion)\b",
                re.IGNORECASE), "quantity"),
    # Keywords are case-insensitive so a sentence-initial "According to" or
    # "In 2025," is caught; the institution name stays capitalised.
    (re.compile(
        r"(?i:\baccording\s+to\s+(?:an?\s+|the\s+)?)(?:[A-Z][a-z]+\s+){1,4}"
        r"(?i:study|report|survey|analysis|paper)\b"),
     "authority"),
    (re.compile(
        r"\b(?:Forrester|Gartner|McKinsey|Pew|Nielsen|Statista|Deloitte|Edelman|MIT|Stanford|Harvard|Wharton)\s+(?:said|reports?|found|noted)",
        re.IGNORECASE), "authority"),
    (re.compile(r"(?i:\bin)\s+(?:19|20)\d{2}\b"), "temporal"),
    (re.compile(r"(?i:\bby)\s+20\d{2}\b"), "temporal"),
    (re.compile(r"\b\d+(?:\.\d+)?\s*(?:x|times)\s+(?:more|less|faster|slower|higher|lower|better|worse)\b",
                re.IGNORECASE), "comparative"),
    (re.compile(r"\b(?:twice|thrice|half)\s+as\s+\w+", re.IGNORECASE),
     "comparative"),
)


# Citation markers looked for in the claim's sentence (see _citation_for).
# Standalone "see" and "per" are NOT triggers because they are common English
# words ("see growth", "per page"). We require the attribution form
# ("Source:", "Per Gartner", "according to Forrester") or an explicit
# hyperlink / footnote. Only the keyword is case-insensitive: the name after
# "per"/"according to" must start with a capital letter. A blanket IGNORECASE
# here used to turn "[A-Z]" into any letter, so "per day" and "according to a"
# counted as citations.
_CITATION_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\[[^\]]+\]\(https?://[^)]+\)"),  # markdown link
    re.compile(r"<a\s+[^>]*href=[\"']https?://[^\"']+[\"']", re.IGNORECASE),  # HTML link
    re.compile(r"\[\^?\d+\]"),  # footnote-style [1] or [^1]
    re.compile(r"@type[\"']?\s*:\s*[\"']Citation[\"']"),  # schema.org Citation
    re.compile(r"(?i:\b(?:source|sources|via|see\s+also)\s*:)\s*\S"),
    re.compile(r"(?i:\bcited\s+(?:in|by))\s+\S"),
    re.compile(r"(?i:\b(?:according\s+to|per))\s+(?:(?i:the|an?)\s+)?[A-Z][A-Za-z]"),
)

# A line that opens with one of these labels attributes the sentence just
# before it ("47% of buyers churn.\nSource: Gartner 2025", "... churned. Per
# Gartner."). The colon is required for source/via so "Via the app, ..." is
# not taken for an attribution line, and "per"/"according to" need the
# capitalised name ("Per week." attributes nothing).
_SOURCE_LINE_RE = re.compile(
    r"(?i:\s*(?:(?:source|sources|via)\s*:|cited\s+(?:in|by)\b))\s*\S"
    r"|(?i:\s*(?:per|according\s+to))\s+(?:(?i:the|an?)\s+)?[A-Z][A-Za-z]")

# Sentence boundaries: end punctuation followed by whitespace and a capital,
# digit, quote, or bracket-free opener. A footnote marker after the period
# ("growth. [1]") stays with its sentence because "[" is not an opener.
# Paragraph breaks and list items always end a sentence; a single hard line
# break inside a paragraph does not, since drafts are often hard-wrapped.
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
_BLOCK_BREAK_RE = re.compile(r"\n\s*\n|\n(?=\s*(?:[-*+]|\d+[.)]|#{1,6})\s)")


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    """Split ``text`` into (start, end) spans of sentences."""
    spans: list[tuple[int, int]] = []
    block_start = 0
    blocks = [m.start() for m in _BLOCK_BREAK_RE.finditer(text)] + [len(text)]
    for block_end in blocks:
        start = block_start
        for m in _SENTENCE_END_RE.finditer(text, block_start, block_end):
            spans.append((start, m.start()))
            start = m.end()
        spans.append((start, block_end))
        block_start = block_end
    return [(s, e) for s, e in spans if text[s:e].strip()]


def _first_citation(snippet: str) -> str | None:
    for pattern in _CITATION_PATTERNS:
        m = pattern.search(snippet)
        if m:
            return m.group(0)[:80]
    return None


def _citation_for(text: str, spans: list[tuple[int, int]], position: int) -> str | None:
    """Return the citation for the claim at ``position``, or None.

    Looks in the claim's own sentence, then in the next sentence only when
    that sentence is a "Source:"-style attribution line.
    """
    for i, (start, end) in enumerate(spans):
        if start <= position < end:
            found = _first_citation(text[start:end])
            if found:
                return found
            if i + 1 < len(spans):
                nxt = text[spans[i + 1][0]:spans[i + 1][1]]
                if _SOURCE_LINE_RE.match(nxt):
                    return nxt.strip()[:80]
            return None
    return None


def extract_claims(text: str) -> list[dict]:
    """Find every claim-like span; mark whether each has a nearby citation."""
    found_spans: list[tuple[int, int, str]] = []
    for pattern, label in _CLAIM_PATTERNS:
        for m in pattern.finditer(text):
            # Skip if an earlier (more specific) pattern already covered
            # this span; prevents 47% double-counting as statistic + quantity.
            if any(s <= m.start() < e or s < m.end() <= e for s, e, _ in found_spans):
                continue
            found_spans.append((m.start(), m.end(), label))

    sentences = _sentence_spans(text)
    claims: list[dict] = []
    for start, end, label in sorted(found_spans):
        cite = _citation_for(text, sentences, start)
        claims.append({
            "text": text[start:end].strip(),
            "kind": label,
            "position": start,
            "has_citation": cite is not None,
            "nearby_citation": cite,
        })
    return claims


# Used only to flag that the claim patterns above are English-pattern-only
# (they key on English words like "of", "million", "in", "by", "times",
# "as", or Latin-cased proper nouns), not to detect a language. Same
# approach as content_quality.py's script coverage note, duplicated here
# rather than imported: each script in this repo is independently
# invocable, with no cross-script imports.
_CJK_CHAR_RE = re.compile(r"[가-힣ぁ-ゖァ-ヺー㐀-䶿一-鿿]")
# ASCII letters plus the accented Latin blocks, so French or Vietnamese text
# counts as Latin (same class as content_quality.py).
_LATIN_CHAR_RE = re.compile(
    r"[A-Za-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u024f\u1e00-\u1eff]"
)
_ALPHA_CHAR_RE = re.compile(r"[^\W\d_]")


def _detect_script(text: str) -> str | None:
    """Return "cjk", "non_latin_alphabetic", or None for the dominant script.

    A zero ``claim_count`` found in Greek, Cyrillic, Arabic, Hebrew, CJK or
    any other non-Latin-alphabetic text does not mean the draft has no
    unsupported claims: it means these English-word-keyed patterns (and the
    Latin-cased "Per Gartner"-style attribution check) found nothing to look
    at, because the claim is phrased in a script or wording they don't
    recognise. ``verify()`` adds a ``coverage`` note for the caller to
    surface that distinction rather than reporting a false "no issues".
    """
    cjk_chars = len(_CJK_CHAR_RE.findall(text))
    latin_chars = len(_LATIN_CHAR_RE.findall(text))
    if cjk_chars and cjk_chars >= latin_chars:
        return "cjk"
    other_alpha_chars = len(_ALPHA_CHAR_RE.findall(text)) - cjk_chars - latin_chars
    if other_alpha_chars > 0 and other_alpha_chars >= latin_chars:
        return "non_latin_alphabetic"
    return None


def verify(text: str) -> dict:
    claims = extract_claims(text)
    uncited = [c for c in claims if not c["has_citation"]]
    result = {
        "claims": claims,
        "claim_count": len(claims),
        "uncited_count": len(uncited),
        "uncited_ratio": round(len(uncited) / len(claims), 3) if claims else 0.0,
    }
    script = _detect_script(text)
    if script in ("cjk", "non_latin_alphabetic"):
        result["coverage"] = {
            "script": script,
            "claim_patterns": "english_only",
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Claim + citation-gap detector for content drafts."
    )
    parser.add_argument("source", nargs="?", default="-",
                        help="File path or '-' for stdin (default '-').")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.4,
        help="Exit non-zero if uncited_ratio > threshold (default 0.4).",
    )
    args = parser.parse_args()

    text = sys.stdin.read() if args.source == "-" else \
        Path(args.source).read_text(encoding="utf-8", errors="replace")

    result = verify(text)

    if args.json:
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"Claims:          {result['claim_count']}")
        print(f"Uncited:         {result['uncited_count']}")
        print(f"Uncited ratio:   {result['uncited_ratio']:.2f}")
        for c in result["claims"]:
            mark = "✓" if c["has_citation"] else "✗"
            print(f"  [{mark} {c['kind']:<11}] {c['text']!r}")
        if result.get("coverage"):
            script_label = {
                "cjk": "CJK",
                "non_latin_alphabetic": "non-Latin-script",
            }.get(result["coverage"]["script"], result["coverage"]["script"])
            print(
                f"  Note: {script_label} text detected. The claim patterns "
                "above are English-word-keyed heuristics, so a low claim "
                "count here does not mean the draft has no unsupported "
                "claims -- it means this tool could not look for them in "
                "this script/wording."
            )

    return 0 if result["uncited_ratio"] <= args.threshold else 1


if __name__ == "__main__":
    sys.exit(main())
