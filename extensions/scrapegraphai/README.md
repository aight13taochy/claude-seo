# ScrapeGraphAI Extension for Claude SEO

LLM-powered scraping, prompt-driven structured extraction, search, and
multi-page crawling powered by [ScrapeGraphAI](https://scrapegraphai.com/).
Adds "describe what you want, get JSON back" extraction to Claude SEO, on top
of the free local fetchers.

## Prerequisites

- [Claude SEO](https://github.com/AgriciDaniel/claude-seo) installed
- Python 3.10+ with the `venv` module (Debian/Ubuntu: `python3-venv`)
- ScrapeGraphAI API key ([dashboard](https://dashboard.scrapegraphai.com); free credits on sign-up)

No Node.js needed: the official MCP server is a Python package.

## Installation

### macOS / Linux

```bash
./extensions/scrapegraphai/install.sh
```

### Windows (PowerShell)

```powershell
.\extensions\scrapegraphai\install.ps1
```

The installer:

1. Creates an isolated virtual environment in `~/.claude/skills/seo-scrapegraphai/.venv`
2. Installs the pinned `scrapegraph-mcp==1.0.1` package into it
3. Copies the `seo-scrapegraphai` skill
4. Registers the `scrapegraph-mcp` server in `~/.claude/settings.json` with your key

Nothing is installed into your system Python.

## Commands

| Command | Purpose | Credits |
|---------|---------|---------|
| `/seo scrapegraphai markdown <url>` | Clean markdown of one page | 2 / page |
| `/seo scrapegraphai extract <url> "<prompt>"` | Structured extraction with prompt and optional JSON schema | 10 / page |
| `/seo scrapegraphai search "<query>"` | Web search plus extraction from top results | 10 / website |
| `/seo scrapegraphai crawl <url> ["<prompt>"]` | Multi-page crawl, markdown or AI mode | 2 or 10 / page |
| `/seo scrapegraphai sitemap <url>` | URL inventory from the site's sitemap | 1 |
| `/seo scrapegraphai scrape <url>` | Rendered HTML, optional heavy JS | 1 / page |
| `/seo scrapegraphai agent <url> "<prompt>"` | Multi-step browser automation then extraction | variable |

Credit figures are the ones reported by the server's own status resource.
Confirm on the dashboard before quoting them.

## Integration with Claude SEO

When installed, other Claude SEO skills can use ScrapeGraphAI:

- **`/seo audit`**: crawl JS-rendered or bot-protected sections, feed clean markdown to the content, schema, and GEO agents
- **`/seo content`** and **`/seo content-brief`**: markdown conversion for E-E-A-T scoring, SERP format research via search
- **`/seo schema`**: extract on-page product or article data and compare with the JSON-LD actually present
- **`/seo ecommerce`**: paginated category inventories, faceted-navigation audits
- **`/seo geo`**: see which sources currently answer a question before optimizing for citation

## ScrapeGraphAI vs Firecrawl

Both extensions can coexist. Rule of thumb:

| Need | Prefer |
|------|--------|
| Discover every URL on a site, cheapest | Firecrawl `map` |
| Extract structured fields with a prompt | ScrapeGraphAI `extract` |
| Search the web and extract in one step | ScrapeGraphAI `search` |
| Click through tabs, filters, "load more" | ScrapeGraphAI `agent` |

## Version note

`scrapegraph-mcp` 1.0.1 is the latest PyPI release and targets the
`api.scrapegraphai.com/v1` endpoints with the tool names documented above
(`smartscraper`, `markdownify`, `searchscraper`, `smartcrawler_*`, `scrape`,
`sitemap`, `agentic_scrapper`). The upstream repository's unreleased 3.x line
renames these tools (`extract`, `search`, `crawl_start`, ...) and targets API v2.
When 3.x reaches PyPI, bump the pin in both installers and update the tool
names in `skills/seo-scrapegraphai/SKILL.md`.

## Troubleshooting

**MCP not connecting?**
- Check: `cat ~/.claude/settings.json | python3 -m json.tool | grep -A6 scrapegraph`
- Test the server by hand: `SGAI_API_KEY=x ~/.claude/skills/seo-scrapegraphai/.venv/bin/python -c "import scrapegraph_mcp.server"`
- Manual config: see [SCRAPEGRAPHAI-SETUP.md](docs/SCRAPEGRAPHAI-SETUP.md)

**`python3 -m venv` fails?**
- Debian/Ubuntu: `sudo apt install python3-venv`, then re-run the installer

**Credits exhausted?**
- Check usage at https://dashboard.scrapegraphai.com
- Prefer `markdown` (2 credits) over `extract` (10 credits) when you only need text

**Site blocks the scraper?**
- Try `extract` with `stealth: true` or `render_heavy_js: true`
- Fall back to `render_page.py` or `fetch_page.py` for unprotected pages

## Uninstall

```bash
./extensions/scrapegraphai/uninstall.sh      # macOS/Linux
.\extensions\scrapegraphai\uninstall.ps1     # Windows
```

Removes the skill, the isolated virtual environment, and the MCP entry.

## Links

- [ScrapeGraphAI](https://scrapegraphai.com/)
- [scrapegraph-mcp on GitHub](https://github.com/ScrapeGraphAI/scrapegraph-mcp)
- [scrapegraph-mcp on PyPI](https://pypi.org/project/scrapegraph-mcp/)
- [API documentation](https://docs.scrapegraphai.com/)
