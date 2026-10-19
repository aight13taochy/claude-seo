# Score Criteria: On-Page SEO, Images, Content Quality

How three of the seven SEO Health Score categories get their number.
`audit_score.py` owns the category weights; this file covers what feeds two
categories that no subagent scored (On-Page SEO 20%, Images 5%) and how the
automated content detectors move Content Quality (23%).

## Design criteria

Every rule below was chosen against these criteria, in this order:

| Criterion | What it requires | How the scorers meet it |
|-----------|------------------|-------------------------|
| Security | No new attack surface, no way to game the score upward | Both scripts read local JSON only and open no socket; detectors can only lower a score; inputs are validated (0-100, JSON objects) |
| Reliability | A signal counts only where it is trustworthy | Gates: English-only phrase lists, minimum tokens and claims, noindex pages and 1x1 pixels excluded, unknown formats left out |
| Speed | Seconds, not minutes, on a 500-page crawl | Pure arithmetic on `parse_html.py` and detector output already produced by the audit |
| Efficiency | No duplicate work, no model tokens | Reuses `parse_html.py`, `metadata_template.py`, `content_quality.py`, `content_verify.py`; no LLM call |
| No double counting | One signal moves one number once | Canonical stays in Technical SEO, file size in seo-images, thin content in the E-E-A-T reading; detector penalties are applied only by `content_score.py` |
| Proportionality | Penalty size follows how directly a signal maps to a documented problem | Missing title and alt weigh most; format and filename least; uncited claims scale with their share |
| Productivity | Every lost point says what to fix | Each finding carries a count, up to 3 examples and a recommendation |
| Transparency | The score can be recomputed by hand | Per-check `passed`, `applicable`, `weight`, `rate`; applied and skipped penalties with reasons |
| Reproducibility | Same input, same score | Deterministic; rounding half up as in `audit_score.py` |

All three are heuristics on markup and text, not Google ranking signals.
Say so in reports.

## On-Page SEO (`onpage_score.py`)

Score = `sum(weight x pass rate) / sum(applicable weights) x 100`. A check
with nothing to apply to is left out and the other weights rescale.
Pages with `noindex` in meta robots are skipped.

| Check | Weight | Passes when | Severity |
|-------|-------:|-------------|----------|
| `title_present` | 15 | `<title>` is non-empty | High |
| `title_length` | 8 | 30-60 characters (target 50-60) | Low |
| `title_unique` | 10 | no other crawled page has the same title | Medium |
| `description_present` | 10 | meta description is non-empty | Medium |
| `description_length` | 5 | 70-160 characters (target 150-160) | Low |
| `description_unique` | 7 | no other crawled page shares it | Medium |
| `single_h1` | 12 | exactly one H1 | Medium |
| `h2_structure` | 5 | at least one H2, on pages of 300+ words | Low |
| `metadata_not_templated` | 8 | `metadata_template.analyse` finds no title echo + stock CTA | High |
| `internal_links` | 10 | at least one internal link (needs `parse_html.py --url`) | Medium |
| `open_graph` | 10 | `og:title`, `og:description`, `og:image` all set | Low |

Why these weights: title and H1 state the topic to both searchers and
crawlers, so they lead; uniqueness and templating catch metadata produced in
bulk rather than per page; length bands only cost points when far
outside what results pages show; Open Graph affects sharing, not ranking.

Not checked here: canonical (Technical SEO), keyword placement and copy
quality (Content Quality), schema (Schema category).

## Images (`onpage_score.py`)

Scored per image across all crawled pages; 1x1 images are skipped. Sites
with no images get `score: null` and `audit_score.py` rescales.

| Check | Weight | Passes when | Severity |
|-------|-------:|-------------|----------|
| `alt_present` | 30 | the `alt` attribute exists (`alt=""` marks a decorative image and passes) | High |
| `alt_length` | 15 | non-empty alt is 10-125 characters | Low |
| `dimensions` | 20 | both `width` and `height` attributes are set | Medium |
| `modern_format` | 15 | `.webp`, `.avif` or `.svg`; unknown extensions are not judged | Low |
| `lazy_offscreen` | 10 | images 4th and later in source order are lazy-loaded | Low |
| `first_image_eager` | 5 | the first image is not lazy-loaded (likely hero/LCP) | Medium |
| `descriptive_filename` | 5 | file name is not `IMG_1234`, `DSC0001`, a hash, or under 3 characters | Low |

Why these weights: missing alt fails accessibility and image search outright;
missing dimensions cause layout shift (CLS); format, lazy-loading and file
names are optimisations. Source order approximates page position, so the two
lazy-loading checks weigh little. File size needs a network fetch and stays
with `seo-images` and `seo-performance`; a CDN that serves WebP behind a
`.jpg` URL passes in practice even if this check fails.

## Content Quality (`content_score.py`)

The seo-content agent reads the page and scores the E-E-A-T rows (0-100).
That reading is the base. `content_score.py` then applies the detector
penalties once; the agent must not deduct for the same flags in its rows.

| Signal | Source | Penalty | Gate |
|--------|--------|--------:|------|
| `ai-patterns` flag | `content_quality.py` | -4 | English, 300+ tokens, not CJK |
| `filler` flag | `content_quality.py` | -3 | same |
| `repetitive` flag | `content_quality.py` | -3 | same |
| `low-density` flag | `content_quality.py` | -2 | same |
| uncited ratio > 0.4 | `content_verify.py` | -3 | English, 3+ claims |
| uncited ratio > 0.7 | `content_verify.py` | -6 (instead of -3) | same |
| `thin-content` flag | `content_quality.py` | 0 | judged by the agent against page-type minimums |

Total penalty is capped at 15 points; the score never goes below 0. No
signal ever adds points: the phrase lists miss new wordings, so a clean
result proves nothing.

Why these sizes: AI-typical phrasing maps to the QRG's lowest-quality
triggers for scaled, low-effort main content, so it costs most among the
flags; filler and repetition are the QRG's "little-to-no value" padding;
low density is the weakest proxy (a short factual page can be sparse).
Uncited claims hit Trust, the factor Google calls most important, so a
majority of uncited claims costs more than any single flag. The cap keeps
the four detectors together below one E-E-A-T row, so they adjust the
reading and never replace it.

For a site audit, score each sampled page, then use the mean of the
adjusted page scores as the Content Quality category score.
