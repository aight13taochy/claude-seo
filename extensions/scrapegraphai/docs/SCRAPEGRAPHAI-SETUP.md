# ScrapeGraphAI Setup Guide

The extension uses ScrapeGraphAI's hosted MCP server. Nothing is installed
locally: no Python package, no virtual environment.

## 1. Create an Account

1. Go to [dashboard.scrapegraphai.com](https://dashboard.scrapegraphai.com)
2. Sign up (free credits are included)
3. Optional: open **API Keys** and create a key. It starts with `sgai-`.
   Older `sk-...` keys are rejected by the new API.

## 2. Run the Installer

```bash
./extensions/scrapegraphai/install.sh          # macOS / Linux
.\extensions\scrapegraphai\install.ps1         # Windows PowerShell
```

It copies the skill and registers an HTTP MCP server named `sgai` in
`~/.claude.json`. At the prompt, either paste an `sgai-` key or leave it empty.

## 3. Sign In (Google option)

If you left the key empty:

```bash
claude mcp login sgai
```

Choose *Continue with Google* in the browser and sign in with the account
linked to ScrapeGraphAI. Alternatively, inside Claude Code run `/mcp`, select
`sgai`, and pick *Authenticate*.

## 4. Manual MCP Configuration

If the installer fails, add this to `~/.claude.json`:

```json
{
  "mcpServers": {
    "sgai": {
      "type": "http",
      "url": "https://sgai-mcp-main.onrender.com/mcp"
    }
  }
}
```

then run `claude mcp login sgai`. With an API key instead:

```json
{
  "mcpServers": {
    "sgai": {
      "type": "http",
      "url": "https://sgai-mcp-main.onrender.com/mcp",
      "headers": { "X-API-Key": "sgai-your-api-key-here" }
    }
  }
}
```

Or with the CLI:

```bash
claude mcp add --transport http sgai https://sgai-mcp-main.onrender.com/mcp \
  --header "X-API-Key: $SGAI_API_KEY"
```

### Two pitfalls

- **URL.** ScrapeGraphAI's docs give `https://mcp.scrapegraphai.com/mcp`, but
  its OAuth metadata declares `https://sgai-mcp-main.onrender.com/mcp` as the
  protected resource. Claude Code checks the two match and refuses the public
  hostname with "Protected resource does not match". Use the onrender URL.
- **Header.** The docs show `Authorization: Bearer sgai-...`; against this
  server Claude Code gets `401 no token payload`. `X-API-Key` works.

## 5. Verify Installation

```bash
claude mcp get sgai
```

Then start Claude Code and try:

```
/seo scrapegraphai credits
```

A balance confirms authentication. If you see a "tool not available" error,
restart Claude Code to reload MCP servers.

## 6. Credits

Every call spends credits; the server does not publish per-tool prices.
Run `credits` before large jobs and read a request's cost with
`history_get` after a test call. Each tool call times out after 60 seconds;
multi-page jobs go through `crawl_start` and page monitors through
`monitor_create`.
