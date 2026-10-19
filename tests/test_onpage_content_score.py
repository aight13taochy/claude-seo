"""On-Page SEO / Images scorer (onpage_score.py) and Content Quality adjuster (content_score.py)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import audit_score  # noqa: E402
import content_score  # noqa: E402
import onpage_score  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
CRITERIA = REPO_ROOT / "skills" / "seo-audit" / "references" / "score-criteria.md"


def _page(label: str, **overrides) -> dict:
    page = {
        "_label": label,
        "url": f"https://example.com/{label}",
        "title": f"{label.title()} guide for choosing hiking boots well",
        "meta_description": (
            f"How to pick {label} hiking boots: fit, sole stiffness, waterproofing and "
            "break-in time, compared across twelve models we tested on real trails."
        ),
        "meta_robots": None,
        "h1": [f"{label.title()} boots"],
        "h2": ["Fit", "Soles"],
        "word_count": 900,
        "links": {"internal": [{"href": "https://example.com/"}], "external": []},
        "open_graph": {"og:title": "t", "og:description": "d", "og:image": "i.jpg"},
        "images": [],
    }
    page.update(overrides)
    return page


def _image(src: str, **overrides) -> dict:
    image = {"src": src, "alt": "Brown leather hiking boot, side view",
             "width": "800", "height": "600", "loading": None, "lazy_method": "none"}
    image.update(overrides)
    return image


def test_check_weights_sum_to_100() -> None:
    assert sum(w for _, w, *_ in onpage_score.ONPAGE_CHECKS) == 100
    assert sum(w for _, w, *_ in onpage_score.IMAGE_CHECKS) == 100


def test_clean_pages_score_100() -> None:
    result = onpage_score.score_onpage([_page("alpine"), _page("trail")])
    assert result["score"] == 100
    assert result["findings"] == []


def test_failures_cost_their_weight_share() -> None:
    pages = [_page("alpine"), _page("trail", h1=[], title="Trail guide for choosing hiking boots well")]
    result = onpage_score.score_onpage(pages)
    # single_h1 passes 1 of 2 pages: 12 * 0.5 lost out of 100.
    assert result["score"] == 94
    finding = next(f for f in result["findings"] if f["check"] == "single_h1")
    assert finding["severity"] == "Medium"
    assert "(e.g. trail)" in finding["description"]


def test_duplicate_titles_and_noindex() -> None:
    same = "Hiking boots guide for every kind of trail"
    pages = [_page("a", title=same), _page("b", title=same), _page("c", meta_robots="noindex, follow")]
    result = onpage_score.score_onpage(pages)
    assert result["pages_skipped_noindex"] == 1
    assert result["checks"]["title_unique"] == {"passed": 0, "applicable": 2, "weight": 10, "rate": 0.0}


def test_uniqueness_is_not_judged_on_a_single_page() -> None:
    result = onpage_score.score_onpage([_page("solo")])
    assert result["checks"]["title_unique"]["applicable"] == 0
    assert result["score"] == 100


def test_internal_links_skipped_without_url_or_classified_links() -> None:
    page = _page("x", links={"internal": [], "external": []})
    del page["url"]
    result = onpage_score.score_onpage([page])
    assert result["checks"]["internal_links"]["applicable"] == 0


def test_images_checks() -> None:
    page = _page("gallery", images=[
        _image("https://cdn.example.com/hero-boot.webp"),
        _image("https://cdn.example.com/IMG_1234.jpg", alt=None, width=None),
        _image("https://cdn.example.com/boot-sole.avif", alt=""),
        _image("https://cdn.example.com/boot-lace.webp", lazy_method="native"),
        _image("https://cdn.example.com/pixel.gif", width="1", height="1"),
    ])
    result = onpage_score.score_images([page])
    checks = result["checks"]
    assert result["images_scored"] == 4
    assert checks["alt_present"]["passed"] == 3
    assert checks["alt_length"]["applicable"] == 2  # alt="" and missing alt are not judged
    assert checks["dimensions"]["passed"] == 3
    assert checks["modern_format"] == {"passed": 3, "applicable": 4, "weight": 15, "rate": 0.75}
    assert checks["descriptive_filename"]["passed"] == 3
    assert checks["first_image_eager"]["passed"] == 1
    assert checks["lazy_offscreen"]["passed"] == 1


def test_no_images_is_not_scored() -> None:
    assert onpage_score.score_images([_page("plain")])["score"] is None


def test_write_merges_and_audit_score_reads_it(tmp_path: Path) -> None:
    page_file = tmp_path / "home.json"
    page = _page("home", images=[_image("https://example.com/boot.jpg")])
    del page["_label"]
    page_file.write_text(json.dumps(page), encoding="utf-8")
    audit = tmp_path / "audit-data.json"
    audit.write_text(json.dumps({"summary": {}, "categories": [
        {"name": "Technical SEO", "score": 80},
        {"name": "Images", "score": 10, "findings": [
            {"title": "Oversized hero image", "severity": "High"},
        ]},
    ]}), encoding="utf-8")

    run = subprocess.run(
        [sys.executable, str(Path(_SCRIPTS) / "onpage_score.py"), str(page_file),
         "--write", str(audit), "--json"],
        capture_output=True, text=True, timeout=30,
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["written"] == ["On-Page SEO", "Images"]

    data = json.loads(audit.read_text(encoding="utf-8"))
    images = next(c for c in data["categories"] if c["name"] == "Images")
    assert images["score"] == 83  # .jpg fails modern_format: 75 of 90 applicable weight
    assert images["findings"][0]["title"] == "Oversized hero image"
    assert audit_score.compute_health_score(data["categories"])["missing"] == [
        "Content Quality", "Schema / Structured Data", "Performance (CWV)", "AI Search Readiness",
    ]


def test_utf16_input_from_powershell_redirect(tmp_path: Path) -> None:
    page = _page("ps")
    del page["_label"]
    path = tmp_path / "ps.json"
    path.write_bytes(json.dumps(page).encode("utf-16"))
    pages, errors = onpage_score.load_pages([str(path)])
    assert errors == [] and pages[0]["_label"] == "https://example.com/ps"


def test_unusable_input_exits_2(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("[1, 2]", encoding="utf-8")
    run = subprocess.run([sys.executable, str(Path(_SCRIPTS) / "onpage_score.py"), str(path)],
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 2


QUALITY = {"flags": ["filler", "ai-patterns", "thin-content"], "tokens": 900}
VERIFY = {"claim_count": 10, "uncited_count": 8, "uncited_ratio": 0.8}


def test_content_penalties_are_itemised_and_capped() -> None:
    result = content_score.adjust(80, QUALITY, VERIFY)
    assert [a["signal"] for a in result["applied"]] == ["filler", "ai-patterns", "uncited-claims"]
    assert result["penalty_uncapped"] == 13
    assert result["adjusted_score"] == 67
    capped = content_score.adjust(
        10, {"flags": ["filler", "ai-patterns", "repetitive", "low-density"], "tokens": 900}, VERIFY)
    assert capped["penalty"] == 15 and capped["penalty_uncapped"] == 18
    assert capped["adjusted_score"] == 0


def test_content_penalties_never_raise_the_score() -> None:
    assert content_score.adjust(72, {"flags": [], "tokens": 900},
                                {"claim_count": 5, "uncited_ratio": 0.0})["adjusted_score"] == 72


def test_content_gates() -> None:
    french = content_score.adjust(80, QUALITY, VERIFY, lang="fr-FR")
    assert french["adjusted_score"] == 80 and len(french["skipped"]) == 3
    short = content_score.adjust(80, {"flags": ["filler"], "tokens": 120}, None)
    assert short["adjusted_score"] == 80
    cjk = content_score.adjust(80, {"flags": ["low-density"], "tokens": 900, "coverage": {"script": "cjk"}})
    assert cjk["adjusted_score"] == 80
    few = content_score.adjust(80, None, {"claim_count": 2, "uncited_ratio": 1.0})
    assert few["adjusted_score"] == 80 and few["skipped"][0]["signal"] == "uncited-claims"
    assert content_score.adjust(80, None, {"claim_count": 5, "uncited_ratio": 0.5})["adjusted_score"] == 77


def test_content_cli_rejects_out_of_range_base() -> None:
    run = subprocess.run([sys.executable, str(Path(_SCRIPTS) / "content_score.py"), "--base", "120"],
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 2


def _table_weights(section: str) -> dict:
    text = CRITERIA.read_text(encoding="utf-8").split(f"## {section}", 1)[1].split("\n## ", 1)[0]
    return {cid: int(w) for cid, w in re.findall(r"^\| `([a-z0-9_]+)` \| (\d+) \|", text, re.MULTILINE)}


def test_criteria_reference_matches_the_scripts() -> None:
    assert _table_weights("On-Page SEO") == {c: w for c, w, *_ in onpage_score.ONPAGE_CHECKS}
    assert _table_weights("Images") == {c: w for c, w, *_ in onpage_score.IMAGE_CHECKS}
    text = CRITERIA.read_text(encoding="utf-8")
    for flag, (points, *_rest) in content_score.FLAG_PENALTIES.items():
        assert f"| `{flag}` flag | `content_quality.py` | -{points} |" in text
    assert f"capped at {content_score.MAX_PENALTY} points" in text
