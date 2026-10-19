---
name: seo-scrapegraphai
description: >
  LLM-powered scraping, structured extraction, search, and crawling via the
  hosted ScrapeGraphAI MCP server. Use when user says "scrapegraph", "extract data
  from page", "scrape with a prompt", "structured extraction", "convert to
  markdown", "search and extract", "crawl with AI", or needs prompt-driven
  extraction from JS-rendered pages at scale.
user-invocable: true
argument-hint: "[command] <url|query>"
license: MIT
compatibility: "Requires the hosted ScrapeGraphAI MCP server registered as `sgai` (Google sign-in or an sgai- API key)"
metadata:
  version: "2.4.2"
  category: seo
---

# ScrapeGraphAI Extension for Claude SEO

This skill requires the ScrapeGraphAI extension to be installed:
```bash
./extensions/scrapegraphai/install.sh
```

The extension registers ScrapeGraphAI's **hosted** MCP server as `sgai`
(HTTP transport, nothing runs locally). Authentication is either a Google
sign-in (`claude mcp login sgai`) or an `sgai-...` API key sent as `X-API-Key`.

**Check availability:** Before using any ScrapeGraphAI tool, verify the MCP
server is connected by checking if `credits` or any other `sgai` tool is
available. If tools are not available, inform the user the extension is not
installed or not signed in, and provide install instructions.

**Credits awareness:** Every call spends ScrapeGraphAI credits. Run `credits`
first when a session starts. Before any multi-page operation (`crawl_start`,
`search` with more than 3 results, batch `extract`), state the estimated
credit cost and get confirmation. Per-tool prices are not published by the
server; read them from the dashboard or from `history_get` after a test call.

**Timeouts:** Each tool call times out after 60 seconds. Anything longer
(whole-site work, change tracking) goes through the async `crawl_*` and
`monitor_*` tools.

## Quick Reference

| Command | MCP tool(s) |
|---------|-------------|
| `/seo scrapegraphai markdown <url>` | `scrape` with `formats: ["markdown"]` |
| `/seo scrapegraphai scrape <url> [format]` | `scrape` (html, screenshot, links, images, summary, branding, json) |
| `/seo scrapegraphai extract <url> "<prompt>"` | `extract` |
| `/seo scrapegraphai search "<query>"` | `search` |
| `/seo scrapegraphai crawl <url> [mode]` | `crawl_start` then `crawl_get` / `crawl_pages` |
| `/seo scrapegraphai monitor <url> [interval]` | `monitor_create`, `monitor_activity` |
| `/seo scrapegraphai credits` | `credits` |
| `/seo scrapegraphai history [id]` | `history_list`, `history_get` |

Parameter names below are the ones the hosted server documents. Always read
the tool's own input schema before calling: the server is updated server-side
and may accept more than listed here.

## Commands

### markdown -- Clean Markdown Conversion

Convert a page to boilerplate-free markdown. Cheapest way to get readable
content from a JS-rendered page. Replaces the old `markdownify` tool.

**MCP Tool:** `scrape`

**Parameters:**
- `url` (required)
- `formats`: `["markdown"]` (default)

**SEO Usage Patterns:**
1. Content inventory for E-E-A-T review: feed the markdown to `seo-content`
2. Word-count and heading-structure checks on SPA pages `fetch_page.py` cannot render
3. Competitor content comparison without manual copy-paste
4. Pre-processing for `content_quality.py` and `content_verify.py`

### scrape -- Multi-Format Page Capture

Fetch one page in one or more formats.

**MCP Tool:** `scrape`

**Parameters:**
- `url` (required)
- `formats`: any of `markdown`, `html`, `screenshot`, `branding`, `links`,
  `images`, `summary`, `json`

**SEO Usage Patterns:**
1. `links`: internal link map and anchor-text audit without a full crawl
2. `images`: image inventory for `/seo images` when the page is JS-rendered
3. `screenshot`: above-the-fold check when Playwright is unavailable
4. `branding`: logo, colours and fonts for `/seo sxo` persona work
5. `html`: rendered DOM for `parse_html.py` when `render_page.py` is blocked

**When to use scrape vs the local fetchers:**
| Scenario | Use |
|----------|-----|
| Static HTML, need response headers | `fetch_page.py` (no API cost) |
| JS-rendered SPA, local Chromium available | `render_page.py` (no API cost) |
| JS-rendered SPA, no local browser or bot-protected | `scrape` |
| Need clean content, not markup | `scrape` with `formats: ["markdown"]` |

### extract -- Prompt-Driven Structured Extraction

Extract structured data from a URL, raw HTML, or markdown using a
natural-language prompt and an optional JSON schema.

**MCP Tool:** `extract`

**Parameters:**
- `url` (required unless HTML or markdown is passed in directly)
- `prompt` (required): what to extract, in plain language
- `schema`: JSON Schema for the response shape

**SEO Usage Patterns:**
1. **On-page element audit**: "Return title, meta description, canonical, H1, every H2, and the word count of each section" with a strict `schema`
2. **Schema gap detection**: "List every product on this page with name, price, availability, and rating" then compare with the JSON-LD found by `seo-schema`
3. **Internal link map**: "List every internal link with anchor text and destination URL"
4. **E-E-A-T signals**: "Extract author name, bio, credentials, publish date, last-updated date, and cited sources"
5. **Competitor page teardown**: identical prompt across 3-5 competitor URLs, same schema, side-by-side table

**Always pass a `schema`** when the result feeds another skill or a report.
Free-form extraction drifts between pages.

### search -- Web Search Plus Extraction

Search the web for a query and extract structured answers from the top results.

**MCP Tool:** `search`

**Parameters:**
- `prompt` (required): the question or extraction instruction
- `num_results`: 1-20, default 3
- `schema`: JSON Schema for the response shape

**SEO Usage Patterns:**
1. **SERP content analysis**: "For the query X, what sub-topics, FAQs, and formats do ranking pages use?"
2. **Entity and citation research** for `seo-geo`: which sources AI engines are likely to cite for a topic
3. **Content gap discovery** feeding `seo-content-brief`
4. **Competitor identification** when the user has no list yet

Cost grows linearly with `num_results`. The default 3 is enough for format
analysis; use 5-10 only for research briefs.

### crawl -- Multi-Page Crawl (Async)

Crawl a site section and capture every page in the chosen format. Two-step:
start, then poll.

**MCP Tools:** `crawl_start`, then `crawl_get` (status plus pages) or
`crawl_pages` (paginated pages, 50 per page by default, max 100).
`crawl_stop`, `crawl_resume` and `crawl_delete` manage a running job.

**Parameters (`crawl_start`):**
- `url` (required): starting URL
- `extraction_mode`: `markdown` (default), `html`, `links`, `images`,
  `summary`, `branding`, `screenshot`
- page cap and depth: default 50 pages at depth 2, hard maximum 1,000 pages.
  **Always set the page cap explicitly**; the default already costs 50 pages.

**Polling:** call `crawl_get` with the crawl id until the status is completed,
then page through results with `crawl_pages`. Stop a runaway job with
`crawl_stop`; `crawl_delete` once results are saved.

**SEO Usage Patterns:**
1. **Section audit**: crawl `/blog/` capped at 50 pages, markdown mode, then thin-content and duplicate checks
2. **Link graph**: `links` mode for orphan detection against `/seo sitemap` output
3. **Template consistency**: markdown mode, then one `extract` per page with a shared schema for title/H1/meta
4. **Migration QA**: crawl before and after, diff with `/seo drift`

**Example orchestration for `/seo audit`:**
```
1. sitemap_discovery.py (local, free)  -> URL inventory and section sizes
2. Pick top sections, set the page cap  -> state estimated credits, confirm
3. crawl_start(url, markdown)           -> crawl id
4. crawl_get(id)                        -> poll until completed
5. crawl_pages(id)                      -> page through results
6. Feed page markdown to seo-content, seo-schema, seo-geo agents
7. crawl_delete(id) once saved
```

### monitor -- Scheduled Change Tracking

Watch a page for changes on a schedule and read the tick history.

**MCP Tools:** `monitor_create`, `monitor_list`, `monitor_get`,
`monitor_update`, `monitor_pause`, `monitor_resume`, `monitor_delete`,
`monitor_activity`

**Parameters (`monitor_create`):**
- `url` (required)
- interval: cron expression or shorthand such as `1h`
- formats and an optional webhook (same values as `scrape`)

`monitor_activity` returns one entry per tick with `status`, `changed`,
`elapsedMs` and `diffs` (default 20 per page, max 100).

**SEO Usage Patterns:**
1. Competitor pricing or title changes feeding `/seo competitor-pages`
2. Watching a client's key landing pages between `/seo drift` baselines
3. Confirming a migration went live (monitor the old URL for the redirect)

Monitors keep spending credits every tick. Create them only on request, state
the interval cost, and delete them when the job is done.

### credits and history -- Account

- `credits`: current balance. Run it at session start and before large jobs.
- `history_list`: recent requests, filterable by service (`scrape`, `extract`,
  `search`, `crawl`).
- `history_get`: one request's details, including what it cost. Use it to
  learn the real per-call price before quoting an estimate.

## Cross-Skill Integration

### With seo-audit
When ScrapeGraphAI is available and the site is JS-rendered or bot-protected:
1. `sitemap_discovery.py` for inventory, then `crawl_start` in markdown mode on key sections
2. Feed markdown to `seo-content`, `seo-schema`, `seo-geo` agents
3. Report credits spent (`history_list`) in the methodology section

### With seo-content and seo-content-brief
- `scrape` (markdown) supplies clean text for readability and E-E-A-T scoring
- `search` supplies SERP format analysis for briefs

### With seo-schema
- `extract` with a product/article schema reveals data present on the page but missing from JSON-LD

### With seo-ecommerce
- `extract` with a product schema for category-page inventories
- `crawl_start` in `links` mode for faceted-navigation and variant-URL audits

### With seo-geo
- `search` to see which sources answer a question today, then compare citability

### With Firecrawl (if both installed)
| Need | Prefer |
|------|--------|
| Whole-site URL discovery, cheapest | Firecrawl `map` |
| Prompt-driven structured extraction | ScrapeGraphAI `extract` |
| Search plus extraction in one call | ScrapeGraphAI `search` |
| Scheduled change tracking | ScrapeGraphAI `monitor_*` |

## Error Handling

| Error | Cause | Resolution |
|-------|-------|-----------|
| Tool not available | Server not registered or not signed in | Run `./extensions/scrapegraphai/install.sh`, then `claude mcp login sgai` (Google) |
| `401` / "no token payload" | Key sent as Bearer, or an old `sk-` key | Re-run the installer with an `sgai-` key (sent as `X-API-Key`) |
| "Protected resource does not match" | Server registered on `mcp.scrapegraphai.com` | Register `https://sgai-mcp-main.onrender.com/mcp` (the installer does) |
| `402` / insufficient credits | Credits exhausted | Check `credits`, top up on the dashboard |
| `429 Too Many Requests` | Rate limited | Wait 60s, lower `num_results` or the crawl page cap |
| Call exceeds 60 seconds | Synchronous tool on a long job | Use `crawl_start` / `monitor_create` instead |
| Crawl status stays pending | Large crawl still running | Keep polling `crawl_get`; lower the page cap next time |

**Graceful fallback:** If ScrapeGraphAI is unavailable, inform the user and suggest:
1. `render_page.py` for JS-rendered single pages (no API cost)
2. `fetch_page.py` for static pages (no API cost)
3. Firecrawl extension for whole-site crawling if installed
4. Install ScrapeGraphAI: `./extensions/scrapegraphai/install.sh`
