# claude-seo Follow-up Repository Audit

> **Archived snapshot.** Recovered from branch `claude/repo-audit-review-Eg1A7` (last change `47148b5`) before that branch was deleted. It describes the repository as of May 2026 and may be out of date, so check current code before acting on any finding.

**Date:** 2026-05-09 (later same day, post v1.9.8)
**Branch audited:** `main` @ commit `4aa8f03` (v1.9.8 + #91 install-tag bump)
**Audit method:** Four parallel sub-agent passes — fix verification, new-code review, GitHub state, regressions/leftover-bugs
**Author:** Claude Code (audit-only; no code edits, no PR comments)
**Purpose:** Verify the prior audit (`docs/AUDIT-2026-05-09.md`) was correctly addressed and surface any new issues introduced by v1.9.7/v1.9.8.

---

## §1. Headline

**Massive amount of remediation work landed: 19 of 30 prior recommendations FIXED, 5 PARTIAL, 6 MISSED.** Two releases shipped (v1.9.7 marketplace-readiness pass, v1.9.8 manifest-consistency CI guard). 9 of 17 prior open PRs merged. 3 of 4 HIGH-severity issues closed (#60, #68, #72), and the SPA gap (#11) got an explicit Limitations section in the README as a documented mitigation while the architectural fix is deferred.

**However, the same merge wave introduced two HIGH-severity regressions** that the new manifest-consistency CI guard does not catch:

1. The new `seo-content-brief` skill is on disk and counted in the manifest, but it is not routed by the orchestrator and not documented in any user-facing commands table — it is effectively unreachable.
2. The orchestrator references a sub-skill `seo-firecrawl` that does not exist as a directory under `skills/` — only inside `extensions/firecrawl/skills/seo-firecrawl/`. That's a ghost reference in three places.

**And one HIGH carryover:** PR #64's MCP version pinning was applied only to the `.sh` installers; the `.ps1` installers are still unpinned, and `extensions/banana/install.ps1` is still missing entirely (third audit pass flagging this).

### Verification scoreboard for the prior audit's recommendations

| Bucket | Count |
|---|---|
| FIXED | 19 |
| PARTIAL (delivered but with gaps) | 5 |
| MISSED | 6 |

PARTIAL and MISSED items are detailed in §3.

### Top 7 new actions

1. **Add `seo-content-brief` to the orchestrator routing table** in `skills/seo/SKILL.md` (lines 25-53 + 175-199). The skill is shipping but unreachable through documented routing.
2. **Remove or relocate the `seo-firecrawl` ghost reference** in `skills/seo/SKILL.md:21,196,221`. There is no `skills/seo-firecrawl/` directory; only `extensions/firecrawl/skills/seo-firecrawl/`. Choose: delete from the orchestrator, or list it as an extension-only skill.
3. **Finish PR #64 for Windows.** Pin MCP package versions in `extensions/firecrawl/install.ps1` and `extensions/dataforseo/install.ps1`. Create the missing `extensions/banana/install.ps1` and `uninstall.ps1`.
4. **Re-sync extension SKILL.md mirrors to v1.9.8.** They are at `1.9.0` (8 minor versions behind core); PRs #62/#63 only synced to v1.9.0.
5. **Fix release-notes-vs-code discrepancy on `author.email`.** v1.9.8 notes claim it was added to the `marketplace.json` plugin entry; verification (issue #92) shows it is not. Either add the field, or amend the release notes.
6. **Extend the manifest CI guard.** Add: routing-coverage assertion (every skill on disk appears in the orchestrator routing table), extension-installer-parity assertion (`.sh` and `.ps1` pin the same MCP version), and broader doc-coverage scan (current test only checks the first 120 lines of README/CLAUDE.md/AGENTS.md).
7. **Add `tests/test_validate_schema.py`** (still missing, third audit pass flagging this) — `hooks/validate-schema.py` is now 172 lines with zero coverage.

---

## §2. What got fixed (positive ledger)

### Documentation reconciliation (Phase A — landed)

| Item | Where | State |
|---|---|---|
| Skill-count reconciliation | `plugin.json:4`, `marketplace.json:14`, `CLAUDE.md:7`, `AGENTS.md:8`, `README.md:5` | ✓ All read "25 sub-skills (21 core + 1 orchestrator + 1 framework integration + 2 extension mirrors)" |
| CI permissions block | `.github/workflows/ci.yml:9-10` | ✓ `permissions: { contents: read }` |
| Dependabot enabled | `.github/dependabot.yml` | ✓ pip + github-actions ecosystems, weekly |
| pytest job in CI | `.github/workflows/ci.yml:58-78` | ✓ Runs `pytest tests/ -v` with `GH_TOKEN` |
| CODE_OF_CONDUCT.md | `/CODE_OF_CONDUCT.md` | ✓ Present |
| Translations cleanup | `translations/uk/` | ✓ Removed (commit `bbb831d`) |
| Marketing artifact cleanup | repo root | ✓ Slides, video script, YouTube research all gone (commit `6892d42`) |
| Manifest consistency test | `tests/test_manifest_consistency.py` | ✓ 9 tests, wired into CI, prevents skill-count drift recurrence |

### Targeted bug fixes (Phase B — landed)

| Item | Where | State |
|---|---|---|
| Windows hook (#68) | `hooks/hooks.json:9` | ✓ `python3` → `python` |
| Missing import (`keyword_planner`) | `scripts/keyword_planner.py:31` | ✓ `import os` added |
| PSI KeyError (#57) | `scripts/pagespeed_check.py:101` | ✓ `"audit_details": {}` initialized |
| OAuth refresh (#72) | `scripts/google_auth.py:180-211, 261, 275, 396-405` | ✓ `_persist_oauth_client_path()` helper writes path-only via tempfile + `os.replace`; no `client_secret` ever persisted |
| backlinks NoneType (#58) | `scripts/moz_api.py:191,229,270,308` | ✓ `... or []` guard pattern |
| Astro `<style>` (#59) | issue closed | ✓ Closed by maintainer (verification agent didn't find an explicit code fix; CHANGELOG attributes it to dataforseo_normalize.py changes — accept) |
| seo-geo Write tool (#17) | `agents/seo-geo.md:6` | ✓ `tools: ..., Write` |
| SPA Limitations doc (#11 mitigation) | `README.md:248-252` | ✓ Section added |
| moz_api v2 REST migration | `scripts/moz_api.py` | ✓ All endpoints migrated; v1 JSON-RPC fully removed |
| Extension SKILL.md sync | `extensions/dataforseo/...`, `extensions/banana/...` | ⚠ Synced **only to v1.9.0** — see §3 PARTIAL |
| MCP package version pinning | `extensions/*/install.sh` | ✓ Pinned in `.sh`, ✗ NOT in `.ps1` — see §3 MISSED |
| Marketplace install fix (#66) | `extensions/dataforseo/install.sh` | ✓ Two-stage detection landed (PR #67) |

### PRs merged (9 of 17 prior open PRs)

`#56` `#62` `#63` `#64` `#67` `#69` `#70` `#73` `#74` — all merged 2026-05-09. PRs `#30` `#36` `#46` (still open) `#47` `#53` (still open) `#54` `#55` `#71` either closed or superseded.

### Issues closed (8 of 13 prior open issues)

HIGH closed: #60, #68, #72. MEDIUM closed: #65 (umbrella), #59, #58. LOW closed: #57, #66, #17. **Still open from prior audit:** #11 (HIGH, mitigated), #61 (MEDIUM), #51 (LOW), #41 (LOW).

---

## §3. What's still partial or missed

### PARTIAL (5 items — fix delivered but with a gap)

| # | Item | Gap |
|---|---|---|
| P1 | CLAUDE.md `seo-flow` mention | The overview prose (lines 5-14) does not name `seo-flow` explicitly. Counts are right; enumeration is incomplete. **LOW.** |
| P2 | `/release-blog` documentation | Section exists at `CLAUDE.md:202-210` but no row in the commands table at `CLAUDE.md:127-153` and no entry in `docs/COMMANDS.md`. **LOW. Third audit pass flagging this.** |
| P3 | Extension SKILL.md mirror sync | PRs #62 (dataforseo) and #63 (banana) brought the mirrors to **v1.9.0**, not v1.9.8. Core is now at v1.9.8. The drift gap that the prior audit flagged is wider now (1.9.0 vs 1.9.8 = 8 minor versions). **MEDIUM.** |
| P4 | Subagent output persistence (#51) | `skills/seo-audit/SKILL.md:50-55` lists output files (`FULL-AUDIT-REPORT.md`, `ACTION-PLAN.md`, `screenshots/`) but never *instructs* subagents to Write them. The list reads as descriptive, not directive. Issue plausibly still reproducible. **MEDIUM.** |
| P5 | Dependabot ecosystems | `.github/dependabot.yml` covers pip + github-actions but not npm. Extensions install npm packages via `npx`, so npm coverage was implied. **LOW.** |

### MISSED (6 items — recommended in prior audit, not delivered)

| # | Item | Where | Severity |
|---|---|---|---|
| M1 | `extensions/banana/install.ps1` | Extension dir | **MEDIUM** — Windows users still cannot install banana extension |
| M2 | Astro `<style>` strip in `content_parsing_live` | scripts | **MEDIUM** — Issue #59 was closed but no explicit code change found by the verification agent; verify the closure was correct |
| M3 | `tests/test_validate_url.py` | tests | **MEDIUM** — Production SSRF guard with zero unit tests |
| M4 | `tests/test_validate_schema.py` | tests | **MEDIUM** — 172-line production hook validator with zero unit tests |
| M5 | `tests/test_skill_frontmatter.py` | tests | **LOW** — Frontmatter parity coverage missing |
| M6 | `tests/test_routing_consistency.py` | tests | **LOW** — Would have caught the new HIGH regressions in §4 |

---

## §4. New findings (introduced or surfaced post-v1.9.6)

### HIGH

#### N1 — `seo-content-brief` is unreachable through documented routing

PR #56 added the skill on disk and bumped the manifest count from 24 → 25, but did not wire it into any user-visible routing.

| File | Issue |
|---|---|
| `skills/seo/SKILL.md:25-53` | Routing table has no `/seo content-brief` row |
| `skills/seo/SKILL.md:175-199` | Numbered sub-skills list goes 1-24, omits content-brief, includes ghost `seo-firecrawl` |
| `CLAUDE.md:127-153` | Commands table missing both `/seo content-brief` and `/seo flow` |
| `docs/COMMANDS.md` | No entry for `seo-content-brief` |
| `README.md` Commands section | No entry for `seo-content-brief` |

The skill's frontmatter `argument-hint: "[url-or-keyword] [page-type]"` (`skills/seo-content-brief/SKILL.md:11`) implies positional args, which only matter if the skill is reachable via slash command — currently it isn't. Auto-discovery via description triggers will still fire, but documented invocation is broken.

**Fix:** add a `/seo content-brief <url-or-keyword> [page-type]` row to the routing table; replace the ghost `seo-firecrawl` numbered entry with `seo-content-brief`; add to `CLAUDE.md` and `docs/COMMANDS.md`.

#### N2 — `seo-firecrawl` ghost reference in orchestrator

`skills/seo/SKILL.md` references `seo-firecrawl` as a sub-skill at lines 21, 196, and 221, but **`skills/seo-firecrawl/` does not exist** on disk. Only `extensions/firecrawl/skills/seo-firecrawl/` exists, and that path is not auto-discovered as a Tier 1 skill.

**Fix:** decide whether firecrawl is documented as an extension-only skill (then phrase the orchestrator references accordingly) or moved to `skills/`. Update `skills/seo/SKILL.md` either way to remove the false claim that it's a top-level sub-skill.

#### N3 — PR #64 not finished for Windows (third audit pass)

| File | State |
|---|---|
| `extensions/banana/install.sh:113,151` | ✓ Pinned `@ycse/nanobanana-mcp@1.1.1` |
| `extensions/banana/install.ps1` | ✗ **MISSING** |
| `extensions/banana/uninstall.ps1` | ✗ **MISSING** |
| `extensions/dataforseo/install.sh:134,157` | ✓ Pinned `dataforseo-mcp-server@2.8.10` |
| `extensions/dataforseo/install.ps1:118,147` | ✗ Unpinned (bare `dataforseo-mcp-server`) |
| `extensions/firecrawl/install.sh:104,124` | ✓ Pinned `firecrawl-mcp@3.11.0` |
| `extensions/firecrawl/install.ps1:73,81` | ✗ Unpinned (bare `firecrawl-mcp`) |

Windows users still get unpinned `npx` execution — the supply-chain risk PR #64 was specifically meant to close. **Fix:** add pin strings to both `.ps1` files; create `extensions/banana/install.ps1` + `uninstall.ps1`; add a CI test `test_extension_installer_versions_match_across_platforms`.

### MEDIUM

#### N4 — Release notes vs code discrepancy: `author.email`

Issue #92 (filed 2026-05-09) verified that v1.9.8 release notes claim `author.email` was added to the `marketplace.json` plugin entry, but the field is not actually present.

**Fix:** add `"author": { "email": "..." }` to the marketplace.json plugin entry, OR amend the v1.9.8 release notes to remove that claim.

#### N5 — `scripts/moz_api.py` legacy strings

The v1 → v2 REST migration was structurally complete but left three textual artifacts:

| Location | Issue |
|---|---|
| `scripts/moz_api.py:5` | Module docstring still says "Queries the Moz API (JSON-RPC 2.0)" |
| `scripts/moz_api.py:97` | `User-Agent: ClaudeSEO/1.8.0` (plugin is at 1.9.8 — drift) |
| `scripts/moz_api.py:343` | Argparse help says `default: 50, max: 100`; code caps at 50 (line 224, 265, 303) |

**Fix:** update docstring; either source UA from plugin version or remove the version suffix; either lift the cap to 100 or fix the help text.

#### N6 — Manifest CI guard coverage gaps

`tests/test_manifest_consistency.py` is well-designed but does **not** assert:

| Gap | Would have caught |
|---|---|
| Every `skills/seo-*/` is referenced in the orchestrator routing table | N1 (`seo-content-brief` not routed) |
| Every skill the orchestrator references exists on disk | N2 (`seo-firecrawl` ghost) |
| `.sh` and `.ps1` extension installers pin the same MCP versions | N3 (Windows unpinned) |
| README/CLAUDE.md/AGENTS.md canonical-phrase scan goes beyond first 120 lines | future relocations of the headline phrase |
| `marketplace.json:8` top-level `metadata.description` count matches plugin entry | future top-level drift |
| `docs/ARCHITECTURE.md`, `docs/COMMANDS.md`, `docs/INSTALLATION.md` skill counts | future doc drift |

**Fix:** add the routing-coverage and installer-parity tests at minimum.

#### N7 — CI `lint` job hardcodes 30 script names

`.github/workflows/ci.yml:24-56` enumerates each script by name and ends with `"All 30 scripts passed syntax check"`. Adding a new script requires editing CI; same drift pattern the manifest-consistency guard was designed to fix.

**Fix:** replace with `find scripts/ -name '*.py' -exec python3 -m py_compile {} +` or the equivalent matrix.

#### N8 — Missing `encoding='utf-8'` on `open()` calls (~15 sites)

Will break on Windows under CP1252 with non-ASCII content. Hot spots:

- `scripts/google_auth.py:154,167,176,194,205,555,612` (config / token JSON)
- `scripts/dataforseo_costs.py:128,140,150,153,160,169,172,177` (cost ledger)
- `scripts/commoncrawl_graph.py:111,126`
- `scripts/gsc_inspect.py:273`
- `scripts/indexing_notify.py:268`
- `scripts/validate_backlink_report.py:318`
- `scripts/verify_backlinks.py:332`
- `scripts/backlinks_auth.py:84`
- `scripts/moz_api.py:57`
- `scripts/google_report.py:2427`

**Fix:** add `encoding="utf-8"` to every read-mode `open()` in `scripts/`.

#### N9 — pytest sync_flow tests fail in restricted networks

`tests/test_sync_flow.py` 2 of 7 tests fail with HTTP 403 from GitHub API rate-limiting in sandboxed CI / sandboxes without `GH_TOKEN`. Production CI passes because `GH_TOKEN` is set, but the tests should be tolerant.

**Fix:** mark with `@pytest.mark.skipif(no_gh_token, reason="rate-limited")` or `@pytest.mark.network`.

### LOW

| # | Finding | Where |
|---|---|---|
| N10 | 7 `except Exception:` clauses still in scripts (down from 15 bare excepts) | google_auth.py:208,348; analyze_visual.py:124,142; commoncrawl_graph.py:304; sync_flow.py:200; youtube_search.py:225 |
| N11 | `seo-content-brief` SKILL.md frontmatter version is `"1.0.0"` while other skills are `"1.9.6"` | `skills/seo-content-brief/SKILL.md` |
| N12 | All other 24 SKILL.md frontmatter versions claim `"1.9.6"` while plugin is at `1.9.8` | All skill dirs (intentional skill-level vs plugin-level versioning, but worth a CI policy decision) |
| N13 | `uninstall.ps1` prints "Restart Claude Code" but `uninstall.sh` does not | `uninstall.ps1:66` vs `uninstall.sh` |
| N14 | `.ps1` and `.sh` uninstall outputs are otherwise asymmetric | review and reconcile |
| N15 | Author email exposed in two manifests (`plugin.json`, `marketplace.json`) | by design? confirm |
| N16 | DNS rebinding in `validate_url()` is acknowledged but not fixed | `release_report.py:983-986` (known H1 finding) |
| N17 | 6 scripts accept user URLs but don't call `validate_url()` (low SSRF risk because they target Google APIs) | gsc_inspect.py, gsc_query.py, ga4_report.py, indexing_notify.py, youtube_search.py, dataforseo_merchant.py |

---

## §5. GitHub state

### Open PRs (7)

| # | Title | Mergeable | CI | Verdict |
|---|---|---|---|---|
| 76 | deps: openpyxl 3.1.5 | clean | green (syntax) | Safe to merge as batch |
| 77 | deps: google-api-python-client 2.196 | clean | green (syntax) | Safe |
| 78 | deps: weasyprint 68.1 | clean | green (syntax) | Safe; PDF rendering not exercised in CI |
| 79 | deps: google-auth-oauthlib 1.4 | clean | green (syntax) | Safe |
| 80 | deps: playwright 1.59 | clean | green (syntax) | Safe |
| 46 | fix: cross-directory script paths + macOS SSL | dirty | none | **Stale; rebase or close.** `--extract` flag for fetch_page.py is salvageable as a separate cherry-pick |
| 53 | Add seo-notebooklm skill | dirty | none | **Stale; will fail new manifest CI.** Decision needed |

**Note:** the 5 Dependabot PRs predate the v1.9.8 pytest job (added 12:30 UTC). Re-running them will trigger the full pytest suite — do that before merging the batch.

**CI gap:** the lint+test workflow doesn't actually `pip install -r requirements.txt`, so dependency bumps only get syntax-check validation. Future regressions in WeasyPrint, Playwright, or googleapis will not be caught at PR time.

### Open issues (6)

| # | Title | Severity | Status |
|---|---|---|---|
| 11 | SPA / CSR audit produces false negatives | HIGH | Mitigated via README Limitations; architectural fix is multi-sprint epic |
| 51 | `/seo audit` does not persist subagent research | MEDIUM | Carryover from prior audit; not addressed |
| 61 | `google_report.py full` ignores audit JSON | MEDIUM | Carryover from prior audit; not addressed |
| 41 | Perfmatters lazy-loading not detected | LOW | Carryover from prior audit; not addressed |
| 89 | Adopt uv for installer + dev workflow | LOW (tracking) | New today; replaces closed PR #36 |
| 92 | Cosmetic drift cleanup (orchestrator + bulk skill version) | LOW | New today; explicitly references the regressions in this audit's §4 |

### CI health

- Latest 5 commits on main: all green.
- `permissions: contents: read` properly scoped at workflow level (`.github/workflows/ci.yml:9-10`).
- `actions/checkout@v6` and `actions/setup-python@v6` pinned to majors; Dependabot will keep them current.
- `pytest tests/` runs in CI and passes on main (verified locally: 22 PASS, 2 sync_flow network failures that are environmental).

### Branches

Clean. Six branches: `main` + 5 dependabot. No long-lived feature branches. `AgriciDaniel-patch-1` previously flagged is gone.

### Releases

`v1.9.7` (2026-05-09 11:20 UTC) and `v1.9.8` (2026-05-09 12:40 UTC) both shipped with detailed release notes. CHANGELOG entries match. **One verifiable claim is wrong:** v1.9.8 notes say `author.email` was added to marketplace.json plugin entry; it isn't (see N4 + issue #92).

---

## §6. Specific file:line remediation list

### HIGH-priority fixes

| File | Line | Action |
|---|---|---|
| `skills/seo/SKILL.md` | 25-53 (routing table) | Add `/seo content-brief <url-or-keyword> [page-type]` row |
| `skills/seo/SKILL.md` | 175-199 (numbered list) | Replace ghost `seo-firecrawl` entry with `seo-content-brief` |
| `skills/seo/SKILL.md` | 21, 196, 221 | Remove or relocate `seo-firecrawl` references; if extension-only, label accordingly |
| `CLAUDE.md` | 127-153 | Add `/seo content-brief` and `/seo flow` rows to commands table |
| `docs/COMMANDS.md` | (search file) | Add `seo-content-brief` entry; verify `seo-flow` entry exists |
| `README.md` | Commands section | Add `seo-content-brief` |
| `extensions/banana/install.ps1` | NEW | Create paralleling install.sh; pin `@ycse/nanobanana-mcp@1.1.1` |
| `extensions/banana/uninstall.ps1` | NEW | Create paralleling uninstall.sh |
| `extensions/dataforseo/install.ps1` | 118, 147 | Change `dataforseo-mcp-server` → `dataforseo-mcp-server@2.8.10` |
| `extensions/firecrawl/install.ps1` | 73, 81 | Change `firecrawl-mcp` → `firecrawl-mcp@3.11.0` |

### MEDIUM-priority fixes

| File | Line | Action |
|---|---|---|
| `.claude-plugin/marketplace.json` | plugin entry | Add `"author": { "email": "..." }` OR amend v1.9.8 release notes |
| `extensions/dataforseo/skills/seo-dataforseo/SKILL.md` | 18 | Sync to v1.9.8 (currently 1.9.0) |
| `extensions/banana/skills/seo-image-gen/SKILL.md` | 10 | Sync to v1.9.8 (currently 1.9.0) |
| `scripts/moz_api.py` | 5 | Update docstring: "JSON-RPC 2.0" → "v2 REST" |
| `scripts/moz_api.py` | 97 | Update User-Agent string (or remove version suffix) |
| `scripts/moz_api.py` | 343 | Either lift `--limit` cap to 100 or fix help text |
| `tests/test_manifest_consistency.py` | NEW tests | Add: routing-coverage, ghost-skill-reference, extension-installer-parity |
| `tests/test_validate_schema.py` | NEW file | Cover `hooks/validate-schema.py`: deprecated types, placeholders, valid/malformed JSON |
| `tests/test_validate_url.py` | NEW file | SSRF coverage: private IPs, loopback, GCP metadata, HTTPS-only |
| `tests/test_sync_flow.py` | 2 failing tests | Mark `@pytest.mark.skipif(no_gh_token)` |
| `.github/workflows/ci.yml` | 24-56 | Replace hardcoded 30-script list with `find scripts/ -name '*.py' -exec python3 -m py_compile {} +` |
| `.github/workflows/ci.yml` | new step | Add `pip install -r requirements.txt` so dependency bumps get real validation |
| `.github/dependabot.yml` | new entry | Add `npm` ecosystem for `extensions/*/install.sh` package references |
| `skills/seo-audit/SKILL.md` | 50-55 | Add explicit "Write FULL-AUDIT-REPORT.md / ACTION-PLAN.md after subagents complete" directive (closes #51) |
| Multiple scripts | multiple | Add `encoding="utf-8"` to all read-mode `open()` calls — see N8 list |

### LOW-priority cleanups

| File | Line | Action |
|---|---|---|
| `CLAUDE.md` | 5-14 | Name `seo-flow` explicitly in overview prose |
| `CLAUDE.md` | 127-153 | Add `/release-blog` row OR mark internal-only (third audit pass) |
| `skills/seo-content-brief/SKILL.md` | 14 | Decide: stay `1.0.0` (per-skill versioning) or harmonize with plugin |
| `uninstall.sh` vs `uninstall.ps1` | output | Reconcile UX messages |
| `scripts/google_auth.py:208,348`, `analyze_visual.py:124,142`, `commoncrawl_graph.py:304`, `sync_flow.py:200`, `youtube_search.py:225` | inline | Narrow `except Exception:` to specific exception types |

---

## §7. Recommended sequence

### Now — quick wins (≤1 hour)

1. Fix N1 + N2 in one commit: edit `skills/seo/SKILL.md` to add `seo-content-brief` and remove `seo-firecrawl` ghost. Update `CLAUDE.md` + `docs/COMMANDS.md` + `README.md`.
2. Fix N4: add `author.email` to `marketplace.json` plugin entry.
3. Fix N5: 3 textual fixes in `scripts/moz_api.py`.
4. Fix N7: replace hardcoded script list in `.github/workflows/ci.yml`.

### This week (a few hours)

5. Finish N3: pin `.ps1` versions; create `extensions/banana/install.ps1` + `uninstall.ps1`.
6. Sync extension SKILL.md mirrors to v1.9.8 (P3).
7. Extend the manifest CI guard with the three new assertions in N6.
8. Merge Dependabot batch (#76-#80) after triggering re-run for the new pytest job.

### Next sprint (quality investments)

9. Add `tests/test_validate_schema.py`, `tests/test_validate_url.py`, and `tests/test_routing_consistency.py`.
10. Add `pip install -r requirements.txt` to CI for real dependency validation.
11. Sweep `encoding='utf-8'` across scripts (N8).
12. Decide skill-level vs plugin-level versioning policy (N12).
13. Address open carryover issues #51 (audit persistence), #61 (google_report full).

### Backlog

14. SPA/CSR architectural fix (#11) — multi-sprint epic.
15. Stale PRs #46 and #53 — rebase or close decisions.
16. PR #46's `fetch_page.py --extract` flag is salvageable; consider cherry-picking.

---

## §8. Methodology

Four parallel sub-agents ran via the general-purpose Agent tool:

1. **Verification** — checked each recommendation in `docs/AUDIT-2026-05-09.md` against current file contents. Output: 19 FIXED / 5 PARTIAL / 6 MISSED.
2. **New-code review** — audited v1.9.7/v1.9.8 additions: `skills/seo-content-brief/`, moz v2 migration, `tests/test_manifest_consistency.py`, CI guard, uninstall glob enumeration, manifest updates, docs cleanup.
3. **GitHub state** — pulled open PR/issue lists via the GitHub MCP server, including the 5 new Dependabot PRs and 2 new issues filed today (#89, #92). Confirmed all 17 prior PRs reached terminal state.
4. **Regressions/leftover-bugs** — programmatic frontmatter parity check (25/25 SKILL.md + 18/18 agents pass), grep sweep for bare excepts / missing encoding / `shell=True` / `http.client` timeouts, pytest run, orchestrator ↔ disk consistency check (where the two HIGH regressions surfaced).

Findings were cross-referenced across agents; all severity tags reflect cross-source consensus.

---

*End of follow-up audit. The repo made enormous progress in v1.9.7/.8 — most of the prior audit's recommendations landed correctly. The two HIGH regressions are mechanical to fix and the manifest CI guard can be extended to prevent recurrence. Use §6 as the canonical fix list.*
