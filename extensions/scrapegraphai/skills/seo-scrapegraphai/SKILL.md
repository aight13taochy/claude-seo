---
name: seo-scrapegraphai
description: >
  LLM-powered scraping, structured extraction, search, and crawling via the
  ScrapeGraphAI MCP server. Use when user says "scrapegraph", "extract data
  from page", "scrape with a prompt", "structured extraction", "convert to
  markdown", "search and extract", "crawl with AI", or needs prompt-driven
  extraction from JS-rendered pages at scale.
user-invocable: true
argument-hint: "[command] <url|query>"
license: MIT
compatibility: "Requires the scrapegraph-mcp MCP server (Python 3.10+) and a ScrapeGraphAI API key"
metadata:
  version: "2.2.5"
  category: seo
---

# ScrapeGraphAI Extension for Claude SEO

This skill requires the ScrapeGraphAI extension to be installed:
```bash
./extensions/scrapegraphai/install.sh
```

**Check availability:** Before using any ScrapeGraphAI tool, verify the MCP
server is connected by checking if `smartscraper` or any other ScrapeGraphAI
tool is available. If tools are not available, inform the user the extension is
not installed and provide install instructions.

**Credits awareness:** Every call spends ScrapeGraphAI credits. Before any
multi-page operation (`crawl`, `search` with `num_results` > 3, batch
`extract`), state the estimated credit cost and get confirmation.

## Quick Reference

| Command | MCP tool | Credits |
|---------|----------|---------|
| `/seo scrapegraphai markdown <url>` | `markdownify` | 2 / page |
| `/seo scrapegraphai extract <url> "<prompt>"` | `smartscraper` | 10 / page |
| `/seo scrapegraphai search "<query>"` | `searchscraper` | 10 / website (default 3) |
| `/seo scrapegraphai crawl <url> ["<prompt>"]` | `smartcrawler_initiate` + `smartcrawler_fetch_results` | 2 / page (markdown) or 10 / page (AI) |
| `/seo scrapegraphai sitemap <url>` | `sitemap` | 1 |
| `/seo scrapegraphai scrape <url>` | `scrape` | 1 / page |
| `/seo scrapegraphai agent <url> "<prompt>"` | `agentic_scrapper` | variable |

Credit figures come from the server's own `scrapegraph://api/status` resource
(scrapegraph-mcp 1.0.1). Confirm current pricing on the dashboard before
quoting it to a client.

## Commands

### markdown -- Clean Markdown Conversion

Convert a page to boilerplate-free markdown. Cheapest way to get readable
content from a JS-rendered page.

**MCP Tool:** `markdownify`

**Parameters:**
- `website_url` (required)

**SEO Usage Patterns:**
1. Content inventory for E-E-A-T review: feed the markdown to `seo-content`
2. Word-count and heading-structure checks on SPA pages `fetch_page.py` cannot render
3. Competitor content comparison without manual copy-paste
4. Pre-processing for `content_quality.py` and `content_verify.py`

### extract -- Prompt-Driven Structured Extraction

Extract structured data from one page using a natural-language prompt and an
optional JSON schema.

**MCP Tool:** `smartscraper`

**Parameters:**
- `website_url` (required unless `website_html` or `website_markdown` is given)
- `user_prompt` (required): what to extract, in plain language
- `output_schema`: JSON schema for the response shape
- `render_heavy_js`: enable for heavy client-side rendering
- `number_of_scrolls`: infinite-scroll depth (0-50)
- `total_pages`: follow pagination for N pages
- `stealth`: anti-bot evasion mode

**SEO Usage Patterns:**
1. **On-page element audit**: "Return title, meta description, canonical, H1, every H2, and the word count of each section" with a strict `output_schema`
2. **Schema gap detection**: "List every product on this page with name, price, availability, and rating" then compare with the JSON-LD found by `seo-schema`
3. **Internal link map**: "List every internal link with anchor text and destination URL"
4. **E-E-A-T signals**: "Extract author name, bio, credentials, publish date, last-updated date, and cited sources"
5. **Competitor page teardown**: identical prompt across 3-5 competitor URLs, same schema, side-by-side table

**Always pass an `output_schema`** when the result feeds another skill or a
report. Free-form extraction drifts between pages.

### search -- Web Search Plus Extraction

Search the web for a query and extract structured answers from the top results.

**MCP Tool:** `searchscraper`

**Parameters:**
- `user_prompt` (required): the question or extraction instruction
- `num_results`: websites to search (default 3)
- `number_of_scrolls`: scroll depth per site

**SEO Usage Patterns:**
1. **SERP content analysis**: "For the query X, what sub-topics, FAQs, and formats do ranking pages use?"
2. **Entity and citation research** for `seo-geo`: which sources AI engines are likely to cite for a topic
3. **Content gap discovery** feeding `seo-content-brief`
4. **Competitor identification** when the user has no list yet

Cost grows linearly with `num_results`. Default 3 websites is enough for
format analysis; use 5-10 only for research briefs.

### crawl -- Multi-Page Crawl (Async)

Crawl a site section and either convert each page to markdown or run a
prompt-driven extraction on each page. Two-step: initiate, then poll.

**MCP Tools:** `smartcrawler_initiate` then `smartcrawler_fetch_results`

**Parameters (initiate):**
- `url` (required): starting URL
- `extraction_mode`: `"markdown"` (2 credits/page) or `"ai"` (10 credits/page, needs `prompt`)
- `prompt`: required when `extraction_mode` is `"ai"`
- `depth`: max link depth
- `max_pages`: hard cap on pages (always set it)
- `same_domain_only`: stay on the start domain (default true)

**Parameters (fetch):**
- `request_id` (from initiate). Poll until status is completed.

**SEO Usage Patterns:**
1. **Section audit**: crawl `/blog/` with `max_pages=50`, markdown mode, then thin-content and duplicate checks
2. **Template consistency**: AI mode with a schema for title/H1/meta on every page in a product category
3. **Orphan detection**: compare crawled URLs with `/seo sitemap` output
4. **Migration QA**: crawl before and after, diff with `/seo drift`

**Example orchestration for `/seo audit`:**
```
1. sitemap(url)                       -> URL inventory (1 credit)
2. Pick top sections, cap max_pages    -> state estimated credits, confirm
3. smartcrawler_initiate(markdown)     -> request_id
4. smartcrawler_fetch_results(id)      -> poll until completed
5. Feed page markdown to seo-content, seo-schema, seo-geo agents
```

### sitemap -- Site Structure Extraction

Discover a site's URLs from its sitemap and structure in one call.

**MCP Tool:** `sitemap`

**Parameters:**
- `website_url` (required)

**SEO Usage Patterns:**
1. Quick URL inventory before scoping a crawl
2. Cross-check against `/seo sitemap` XML validation output
3. URL-pattern breakdown (blog vs product vs category share)

### scrape -- Raw HTML Fetch

Fetch rendered HTML for a page, optionally with heavy JavaScript rendering.

**MCP Tool:** `scrape`

**Parameters:**
- `website_url` (required)
- `render_heavy_js`: enable for client-side frameworks

**When to use scrape vs fetch_page.py vs render_page.py:**
| Scenario | Use |
|----------|-----|
| Static HTML, need response headers | `fetch_page.py` (no API cost) |
| JS-rendered SPA, local Chromium available | `render_page.py` (no API cost) |
| JS-rendered SPA, no local browser or bot-protected | `scrape` with `render_heavy_js` |
| Need clean content, not markup | `markdownify` |

### agent -- Agentic Browser Automation

Run a multi-step browser automation (click, scroll, fill, navigate) and
optionally extract data at the end.

**MCP Tool:** `agentic_scrapper`

**Parameters:**
- `url` (required)
- `steps`: ordered list of actions in plain language
- `user_prompt` and `output_schema`: extraction after the steps
- `ai_extraction`: enable extraction (otherwise returns page state)
- `persistent_session`: keep cookies between steps
- `timeout_seconds`

**SEO Usage Patterns:**
1. Content behind tabs, accordions, or "load more" buttons
2. Faceted navigation audit: apply filters and capture resulting URLs and canonicals
3. Checkout or form flows for `seo-sxo` user-story validation

Credits are variable. Prefer `extract` with `number_of_scrolls` when a plain
scroll is enough.

## Cross-Skill Integration

### With seo-audit
When ScrapeGraphAI is available and the site is JS-rendered or bot-protected:
1. `sitemap` for inventory, then `smartcrawler_initiate` in markdown mode on key sections
2. Feed markdown to `seo-content`, `seo-schema`, `seo-geo` agents
3. Report credits spent in the methodology section

### With seo-content and seo-content-brief
- `markdownify` supplies clean text for readability and E-E-A-T scoring
- `searchscraper` supplies SERP format analysis for briefs

### With seo-schema
- `smartscraper` with a product/article schema reveals data present on the page but missing from JSON-LD

### With seo-ecommerce
- `smartscraper` with `total_pages` for category-page product inventories
- `agentic_scrapper` for faceted-navigation and variant-URL audits

### With seo-geo
- `searchscraper` to see which sources answer a question today, then compare citability

### With Firecrawl (if both installed)
| Need | Prefer |
|------|--------|
| Whole-site URL discovery, cheapest | Firecrawl `map` |
| Prompt-driven structured extraction | ScrapeGraphAI `smartscraper` |
| Search plus extraction in one call | ScrapeGraphAI `searchscraper` |
| Browser automation steps | ScrapeGraphAI `agentic_scrapper` |

## Error Handling

| Error | Cause | Resolution |
|-------|-------|-----------|
| `SGAI_API_KEY` missing | MCP not configured | Run `./extensions/scrapegraphai/install.sh` |
| `401 Unauthorized` | Invalid or revoked key | Regenerate at dashboard.scrapegraphai.com, re-run installer |
| `402` / insufficient credits | Credits exhausted | Check dashboard, top up or wait for reset |
| `429 Too Many Requests` | Rate limited | Wait 60s, lower `num_results` or `max_pages` |
| Crawl status stays pending | Large crawl still running | Keep polling `smartcrawler_fetch_results`; lower `max_pages` next time |
| Tool not available | Server not started | Restart Claude Code; check `~/.claude/settings.json` for `scrapegraph-mcp` |

**Graceful fallback:** If ScrapeGraphAI is unavailable, inform the user and suggest:
1. `render_page.py` for JS-rendered single pages (no API cost)
2. `fetch_page.py` for static pages (no API cost)
3. Firecrawl extension for whole-site crawling if installed
4. Install ScrapeGraphAI: `./extensions/scrapegraphai/install.sh`
