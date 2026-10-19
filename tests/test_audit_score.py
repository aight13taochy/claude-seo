"""SEO Health Score recompute (scripts/audit_score.py) and its report wiring."""

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
import google_report  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "audit_score.py"

FULL = [
    {"name": "Technical SEO", "score": 80},
    {"name": "Content Quality", "score": 60},
    {"name": "On-Page SEO", "score": 70},
    {"name": "Schema / Structured Data", "score": 50},
    {"name": "Performance (CWV)", "score": 90},
    {"name": "AI Search Readiness", "score": 40},
    {"name": "Images", "score": 100},
]
# 80*22 + 60*23 + 70*20 + 50*10 + 90*10 + 40*10 + 100*5 = 6840 -> 68.4
FULL_SCORE = 68


def _run(path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(path), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_weights_sum_to_100() -> None:
    assert sum(audit_score.WEIGHTS.values()) == 100


def test_full_coverage_is_the_weighted_mean() -> None:
    result = audit_score.compute_health_score(FULL)
    assert result["raw_score"] == 68.4
    assert result["health_score"] == FULL_SCORE
    assert result["coverage"] == 1.0
    assert result["missing"] == []


def test_report_style_names_match_the_weighted_categories() -> None:
    # The report template says "Schema & Structured Data" and "Performance";
    # agents write "Schema / Structured Data". All must land on one weight.
    result = audit_score.compute_health_score([
        {"name": "Schema & Structured Data", "score": 50},
        {"name": "Performance", "score": 90},
        {"name": "on-page seo", "score": 70},
    ])
    assert [item["name"] for item in result["used"]] == [
        "Schema / Structured Data", "Performance (CWV)", "On-Page SEO",
    ]


def test_missing_category_rescales_and_reports_coverage() -> None:
    result = audit_score.compute_health_score([
        {"name": "Technical SEO", "score": 74},
        {"name": "Content Quality", "score": 68},
    ])
    # (74*22 + 68*23) / 45 = 70.93
    assert result["health_score"] == 71
    assert result["coverage"] == 0.45
    assert "On-Page SEO" in result["missing"]


def test_unusable_scores_are_left_out_with_a_reason() -> None:
    result = audit_score.compute_health_score([
        {"name": "Technical SEO", "score": 80},
        {"name": "Content Quality", "score": "N/A"},
        {"name": "On-Page SEO", "score": True},
        {"name": "Images", "score": 120},
        {"name": "AI Search Readiness"},
    ])
    assert result["health_score"] == 80
    reasons = {item["name"]: item["reason"] for item in result["invalid"]}
    assert reasons == {
        "Content Quality": "not a number",
        "On-Page SEO": "missing",
        "Images": "outside 0-100",
        "AI Search Readiness": "missing",
    }


def test_unweighted_categories_do_not_move_the_score() -> None:
    result = audit_score.compute_health_score(
        FULL + [{"name": "Backlink Profile", "score": 0}, {"name": "Search Experience", "score": 0}]
    )
    assert result["health_score"] == FULL_SCORE
    assert result["unweighted"] == ["Backlink Profile", "Search Experience"]


def test_a_duplicate_category_counts_once() -> None:
    result = audit_score.compute_health_score([
        {"name": "Technical SEO", "score": 80},
        {"name": "Technical SEO", "score": 0},
    ])
    assert result["health_score"] == 80
    assert result["invalid"] == [{"name": "Technical SEO", "reason": "duplicate category"}]


def test_half_points_round_up() -> None:
    result = audit_score.compute_health_score([{"name": "Technical SEO", "score": 72.5}])
    assert result["health_score"] == 73


def test_check_declared_statuses() -> None:
    assert audit_score.check_declared({"summary": {"health_score": 70}, "categories": FULL})["status"] == "match"
    mismatch = audit_score.check_declared({"summary": {"health_score": 82}, "categories": FULL})
    assert mismatch["status"] == "mismatch"
    assert mismatch["delta"] == 13.6
    assert audit_score.check_declared({"categories": FULL})["status"] == "no_declared"
    assert audit_score.check_declared({"summary": {"health_score": 50}})["status"] == "no_categories"


def test_cli_exit_codes_and_write(tmp_path: Path) -> None:
    path = tmp_path / "audit-data.json"
    path.write_text(json.dumps({"summary": {"health_score": 82}, "categories": FULL}), encoding="utf-8")

    checked = _run(path, "--json")
    assert checked.returncode == 1
    assert json.loads(checked.stdout)["status"] == "mismatch"

    written = _run(path, "--write")
    assert written.returncode == 0, written.stderr
    assert json.loads(path.read_text(encoding="utf-8"))["summary"]["health_score"] == FULL_SCORE
    assert _run(path).returncode == 0

    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"summary": {}, "categories": []}), encoding="utf-8")
    assert _run(empty, "--write").returncode == 2
    assert json.loads(empty.read_text(encoding="utf-8")) == {"summary": {}, "categories": []}


def _skill_weights(relative: str) -> dict:
    text = (REPO_ROOT / relative).read_text(encoding="utf-8")
    return {
        name.strip(): int(weight)
        for name, weight in re.findall(r"^\| ([^|]+?) \| (\d+)% \|$", text, re.MULTILINE)
    }


def test_skill_weight_tables_match_the_script() -> None:
    for relative in ("skills/seo-audit/SKILL.md", "skills/seo/SKILL.md"):
        assert _skill_weights(relative) == audit_score.WEIGHTS, relative


def test_report_warns_on_a_mismatch_and_keeps_the_declared_score(tmp_path: Path) -> None:
    data = {"summary": {"health_score": 82}, "categories": FULL}
    result = google_report.generate_report("full", data, "example.com", tmp_path, output_format="html")
    assert result["score_check"]["status"] == "mismatch"
    assert "category scores give 68" in result["warnings"][0]
    html = Path(result["files"][0]).read_text(encoding="utf-8")
    assert "82/100" in html
    assert data["summary"]["health_score"] == 82


def test_report_fills_a_missing_score_from_the_categories(tmp_path: Path) -> None:
    data = {"summary": {"business_type": "SaaS"}, "categories": FULL}
    result = google_report.generate_report("full", data, "example.com", tmp_path, output_format="html")
    assert result["score_check"]["status"] == "no_declared"
    assert "warnings" not in result
    assert f"{FULL_SCORE}/100" in Path(result["files"][0]).read_text(encoding="utf-8")
    assert "health_score" not in data["summary"]
