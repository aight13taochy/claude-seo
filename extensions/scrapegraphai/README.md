# ScrapeGraphAI Extension for Claude SEO

LLM-powered scraping, prompt-driven structured extraction, search, async
crawling and page-change monitors powered by
[ScrapeGraphAI](https://scrapegraphai.com/). Adds "describe what you want, get
JSON back" extraction to Claude SEO, on top of the free local fetchers.

The extension registers ScrapeGraphAI's **hosted MCP server** (HTTP transport).
Nothing runs on your machine: no Python package, no virtual environment,
no Node.js.

## Prerequisites

- [Claude SEO](https://github.com/AgriciDaniel/claude-seo) installed
- A ScrapeGraphAI account ([dashboard](https://dashboard.scrapegraphai.com);
  free credits on sign-up)
- `python3` (any version) for the installer's JSON merge of `~/.claude.json`

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

1. Copies the `seo-scrapegraphai` skill to `~/.claude/skills/seo-scrapegraphai/`
2. Registers an HTTP MCP server named `sgai` in `~/.claude.json`
   (written atomically, never touched if the file is unparseable)
3. Asks for an optional `sgai-...` API key

## Authentication

Two options; the installer prompt decides which.

| Option | What to do |
|--------|------------|
| **Google sign-in** (leave the key empty) | After installing, run `claude mcp login sgai` and choose *Continue with Google* in the browser. Or in Claude Code: `/mcp`, select `sgai`, *Authenticate*. |
| **API key** | Paste an `sgai-...` key from the dashboard. It is stored in `~/.claude.json` as an `X-API-Key` header and skips OAuth. |

Pitfalls, all verified:

- Old `sk-...` keys are "Invalid or deprecated". Generate an `sgai-` key in
  the new dashboard.
- The key must go in `X-API-Key`. Sent as `Authorization: Bearer` the server
  answers `401 no token payload`.
- The public URL `https://mcp.scrapegraphai.com/mcp` fails in Claude Code with
  "Protected resource does not match": the server's OAuth metadata declares
  `https://sgai-mcp-main.onrender.com/mcp` as the protected resource. The
  installer registers the onrender URL, which works for both auth options.

## Commands

| Command | MCP tool |
|---------|----------|
| `/seo scrapegraphai markdown <url>` | `scrape` (markdown) |
| `/seo scrapegraphai scrape <url> [format]` | `scrape` (html, screenshot, links, images, summary, branding, json) |
| `/seo scrapegraphai extract <url> "<prompt>"` | `extract` |
| `/seo scrapegraphai search "<query>"` | `search` |
| `/seo scrapegraphai crawl <url> [mode]` | `crawl_start` + `crawl_get` / `crawl_pages` |
| `/seo scrapegraphai monitor <url> [interval]` | `monitor_create`, `monitor_activity` |
| `/seo scrapegraphai credits` | `credits` |
| `/seo scrapegraphai history [id]` | `history_list`, `history_get` |

The hosted server exposes 20 tools: `scrape`, `extract`, `search`,
`crawl_start`, `crawl_get`, `crawl_pages`, `crawl_stop`, `crawl_resume`,
`crawl_delete`, `credits`, `history_list`, `history_get`, `monitor_create`,
`monitor_list`, `monitor_get`, `monitor_update`, `monitor_pause`,
`monitor_resume`, `monitor_delete`, `monitor_activity`. Per-tool credit
prices are not published by the server; check the dashboard or `history_get`.

## Integration with Claude SEO

When installed, other Claude SEO skills can use ScrapeGraphAI:

- **`/seo audit`**: crawl JS-rendered or bot-protected sections, feed clean markdown to the content, schema, and GEO agents
- **`/seo content`** and **`/seo content-brief`**: markdown conversion for E-E-A-T scoring, SERP format research via search
- **`/seo schema`**: extract on-page product or article data and compare with the JSON-LD actually present
- **`/seo ecommerce`**: category inventories, faceted-navigation audits with `links` mode
- **`/seo geo`**: see which sources currently answer a question before optimizing for citation
- **`/seo drift`** and **`/seo competitor-pages`**: monitors between baselines

## ScrapeGraphAI vs Firecrawl

Both extensions can coexist. Rule of thumb:

| Need | Prefer |
|------|--------|
| Discover every URL on a site, cheapest | Firecrawl `map` |
| Extract structured fields with a prompt | ScrapeGraphAI `extract` |
| Search the web and extract in one step | ScrapeGraphAI `search` |
| Watch a page for changes on a schedule | ScrapeGraphAI `monitor_*` |

## Why the hosted server

The PyPI package `scrapegraph-mcp` (1.0.1) still calls
`api.scrapegraphai.com/v1`, whose TLS endpoint no longer answers. ScrapeGraphAI
moved to `v2-api.scrapegraphai.com` and ships the MCP server itself at
`mcp.scrapegraphai.com`; the GitHub repository's 3.x line targets the new API
but is not published on PyPI. Registering the hosted server is the only
option that works today and needs no local runtime.

## Troubleshooting

**MCP not connecting?**
- Check: `claude mcp get sgai` (expect type `http`, the onrender URL)
- Google sign-in: `claude mcp login sgai`, then restart Claude Code
- Manual config: see [SCRAPEGRAPHAI-SETUP.md](docs/SCRAPEGRAPHAI-SETUP.md)

**"Protected resource does not match"?**
- The entry points at `mcp.scrapegraphai.com`. Re-run the installer, which
  registers the onrender URL.

**`401`?**
- An `sk-` key, or a key sent as Bearer. Re-run the installer with an
  `sgai-` key.

**Credits exhausted (`402`)?**
- Ask for `credits`, top up at https://dashboard.scrapegraphai.com
- Prefer `scrape` (markdown) over `extract` when you only need text

**Tool call times out?**
- Each call is capped at 60 seconds. Use `crawl_start` for multi-page jobs.

## Uninstall

```bash
./extensions/scrapegraphai/uninstall.sh      # macOS/Linux
.\extensions\scrapegraphai\uninstall.ps1     # Windows
```

Removes the skill and the `sgai` MCP entry. A Google token, if any, is
dropped with `claude mcp logout sgai`.

## Links

- [ScrapeGraphAI](https://scrapegraphai.com/)
- [Hosted MCP server docs](https://docs.scrapegraphai.com/services/mcp-server/introduction)
- [Claude Code setup page](https://docs.scrapegraphai.com/services/mcp-server/claude-code)
- [scrapegraph-mcp on GitHub](https://github.com/ScrapeGraphAI/scrapegraph-mcp)
