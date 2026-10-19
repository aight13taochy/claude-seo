"""
The Windows installer smoke workflow tests the code it claims to test.

On a pull request the workflow installs the PR's own head branch. That branch
lives in the repository running CI, which is not upstream on a fork or mirror,
so both the ref check and the installer's clone must target that repository.
Manual runs still install released upstream tags.

``install.ps1`` accepts the source through ``CLAUDE_SEO_REPO_URL``, restricted
to ``https://github.com/<owner>/claude-seo`` so the override cannot point the
installer at an arbitrary host.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL_PS1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" / "windows-smoke.yml").read_text(encoding="utf-8")


def _override_pattern() -> re.Pattern:
    match = re.search(r"CLAUDE_SEO_REPO_URL -notmatch '([^']+)'", INSTALL_PS1)
    assert match, "install.ps1 must validate CLAUDE_SEO_REPO_URL with -notmatch"
    # .NET's end-of-string anchor is \z; Python 3.10 spells it \Z.
    return re.compile(match.group(1).replace(r"\z", r"\Z"), re.IGNORECASE)


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/AgriciDaniel/claude-seo",
        "https://github.com/aight13taochy/claude-seo",
        "https://github.com/AI-Marketing-Hub/claude-seo",
    ],
)
def test_override_accepts_github_claude_seo_repositories(url: str) -> None:
    assert _override_pattern().match(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/AgriciDaniel/claude-seo",
        "https://github.com.evil.example/x/claude-seo",
        "http://github.com/x/claude-seo",  # no plain HTTP
        "https://github.com/x/other-repo",
        "https://github.com/x/claude-seo/tree/main",
        "https://github.com/x/claude-seo.git",
        "https://github.com/-x/claude-seo",  # owners cannot start with '-'
        "https://github.com/x/claude-seo\n",  # .NET '$' would accept this
        "file:///tmp/claude-seo",
    ],
)
def test_override_refuses_everything_else(url: str) -> None:
    assert not _override_pattern().match(url)


def test_installer_default_source_is_still_upstream() -> None:
    assert '$RepoUrl = "https://github.com/AgriciDaniel/claude-seo"' in INSTALL_PS1


def test_invalid_override_fails_instead_of_falling_back() -> None:
    block = INSTALL_PS1.split("if ($env:CLAUDE_SEO_REPO_URL) {", 1)[1].split("$RepoTag", 1)[0]
    assert "exit 1" in block, "a rejected override must stop the install"


def test_ref_check_targets_the_repository_that_holds_the_ref() -> None:
    assert "https://github.com/AgriciDaniel/claude-seo.git" not in WORKFLOW, (
        "the ls-remote target must come from SOURCE_REPO, not a hard-coded upstream"
    )
    assert re.search(
        r"SOURCE_REPO: \$\{\{ github\.event_name == 'pull_request' && github\.repository"
        r" \|\| 'AgriciDaniel/claude-seo' \}\}",
        WORKFLOW,
    )
    assert 'git ls-remote --exit-code --refs "${repo_url}.git"' in WORKFLOW
    assert "repo_url: ${{ steps.ref.outputs.repo_url }}" in WORKFLOW


def test_every_install_step_receives_the_same_source() -> None:
    install_steps = WORKFLOW.count("CLAUDE_SEO_TAG: ${{ needs.validate-ref.outputs.ref }}")
    repo_urls = WORKFLOW.count(
        "CLAUDE_SEO_REPO_URL: ${{ needs.validate-ref.outputs.repo_url }}"
    )
    assert install_steps == 2, "pwsh and Windows PowerShell 5.1 jobs"
    assert repo_urls == install_steps
