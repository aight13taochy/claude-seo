"""Extension mirrors are adaptations of their extension copy, not byte copies.

The plugin ships a core copy of two extensions' skill and agent
(``skills/seo-dataforseo``, ``skills/seo-image-gen`` and their agents) so they
are discoverable without running the extension installer. The installer
copies the extension's own files instead. The two copies are allowed to
differ in wording: the core copy must work with only the MCP server, while
the extension copy may call the extension's scripts.

These tests pin the parts that must not drift: both copies exist under the
same name, the core copy never calls an extension script it cannot assume is
installed, and the Banana reference set is the same file list on both sides.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# (core path, extension path) for every mirrored skill and agent.
MIRRORS = [
    ("skills/seo-dataforseo/SKILL.md", "extensions/dataforseo/skills/seo-dataforseo/SKILL.md"),
    ("agents/seo-dataforseo.md", "extensions/dataforseo/agents/seo-dataforseo.md"),
    ("skills/seo-image-gen/SKILL.md", "extensions/banana/skills/seo-image-gen/SKILL.md"),
    ("agents/seo-image-gen.md", "extensions/banana/agents/seo-image-gen.md"),
]


def _frontmatter_name(path: Path) -> str | None:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", path.read_text(encoding="utf-8"), re.DOTALL)
    if not match:
        return None
    name = re.search(r"^name:\s*(\S+)\s*$", match.group(1), re.MULTILINE)
    return name.group(1) if name else None


@pytest.mark.parametrize(("core", "extension"), MIRRORS)
def test_mirror_pair_exists_under_the_same_name(core: str, extension: str) -> None:
    core_path, extension_path = REPO_ROOT / core, REPO_ROOT / extension
    assert core_path.is_file(), core
    assert extension_path.is_file(), extension
    assert _frontmatter_name(core_path) is not None, core
    assert _frontmatter_name(core_path) == _frontmatter_name(extension_path)


@pytest.mark.parametrize("core", [core for core, _ in MIRRORS])
def test_core_copy_does_not_call_extension_scripts(core: str) -> None:
    # `claude-seo run --extension <name>` only works after the extension
    # installer has run; the core copy must not depend on it.
    assert "--extension" not in (REPO_ROOT / core).read_text(encoding="utf-8"), core


def test_banana_reference_files_match_on_both_sides() -> None:
    core = {p.name for p in (REPO_ROOT / "skills/seo-image-gen/references").glob("*.md")}
    extension = {p.name for p in (REPO_ROOT / "extensions/banana/references").glob("*.md")}
    assert core, "core seo-image-gen ships no reference files"
    assert core == extension, {
        "only in core": sorted(core - extension),
        "only in extension": sorted(extension - core),
    }
