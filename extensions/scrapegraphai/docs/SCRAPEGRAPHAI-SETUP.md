# ScrapeGraphAI Setup Guide

## 1. Get Your API Key

1. Go to [dashboard.scrapegraphai.com](https://dashboard.scrapegraphai.com)
2. Create an account (free credits are included on sign-up)
3. Open **API Keys** and copy your key (starts with `sgai-`)

## 2. Run the Installer

```bash
./extensions/scrapegraphai/install.sh          # macOS / Linux
.\extensions\scrapegraphai\install.ps1         # Windows PowerShell
```

It prompts for the key, creates an isolated Python environment under
`~/.claude/skills/seo-scrapegraphai/.venv`, installs `scrapegraph-mcp==1.0.1`
into it, and registers the MCP server.

Requirements: Python 3.10+ with the `venv` module. On Debian/Ubuntu install
`python3-venv` first.

## 3. Manual MCP Configuration

If the installer fails, create the environment yourself:

```bash
python3 -m venv ~/.claude/skills/seo-scrapegraphai/.venv
~/.claude/skills/seo-scrapegraphai/.venv/bin/python -m pip install "scrapegraph-mcp==1.0.1"
```

Then add this to `~/.claude.json` (replace `/home/you` with your home
directory, and `Scripts\python.exe` instead of `bin/python` on Windows):

```json
{
  "mcpServers": {
    "scrapegraph-mcp": {
      "command": "/home/you/.claude/skills/seo-scrapegraphai/.venv/bin/python",
      "args": ["-c", "from scrapegraph_mcp.server import mcp; mcp.run(transport='stdio')"],
      "env": {
        "SGAI_API_KEY": "sgai-your-api-key-here"
      }
    }
  }
}
```

Why `python -c` and not the `scrapegraph-mcp` console script: the console
script's `main()` prints a startup banner to stdout before the JSON-RPC stream
begins, which some MCP clients reject. Calling `mcp.run()` directly keeps
stdout clean.

## 4. Verify Installation

Start Claude Code and try:

```
/seo scrapegraphai sitemap https://example.com
```

You should get a URL list for 1 credit. If you see a "tool not available"
error, restart Claude Code to reload MCP servers.

To test the server outside Claude Code:

```bash
SGAI_API_KEY=x ~/.claude/skills/seo-scrapegraphai/.venv/bin/python -c "import scrapegraph_mcp.server; print('ok')"
```

## 5. Understanding Credits

| Operation | Credits |
|-----------|---------|
| `markdown` (`markdownify`) | 2 per page |
| `extract` (`smartscraper`) | 10 per page |
| `search` (`searchscraper`) | 10 per website (default 3 websites) |
| `crawl` markdown mode | 2 per page |
| `crawl` AI mode | 10 per page |
| `scrape` | 1 per page |
| `sitemap` | 1 per request |
| `agent` (`agentic_scrapper`) | variable |

Figures reported by the server's `scrapegraph://api/status` resource in
`scrapegraph-mcp` 1.0.1. Check the dashboard for current pricing.

**Tip**: run `sitemap` first (1 credit) to size the site, then set
`max_pages` on `crawl` before spending 2-10 credits per page.

## 6. Optional Environment Variables

The server also honors `SGAI_API_URL` (override the API base URL) and
`SGAI_TIMEOUT` (request timeout in seconds). Add them to the `env` block of the
MCP entry if needed.
