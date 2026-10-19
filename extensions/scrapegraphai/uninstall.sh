#!/usr/bin/env bash
set -euo pipefail

echo "Removing ScrapeGraphAI extension..."

# Remove skill directory
rm -rf "${HOME}/.claude/skills/seo-scrapegraphai"
echo "v Removed skill files"

# Remove MCP entry from ~/.claude.json
MCP_CONFIG_FILE="${HOME}/.claude.json"
if [ -f "${MCP_CONFIG_FILE}" ]; then
    python3 - "${MCP_CONFIG_FILE}" <<'PY' || echo "  Warning: Could not update ~/.claude.json automatically."
import json, os, sys, tempfile

settings_path = sys.argv[1]
with open(settings_path, 'r') as f:
    settings = json.load(f)

if 'mcpServers' in settings and 'sgai' in settings['mcpServers']:
    del settings['mcpServers']['sgai']
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(settings_path) or '.', prefix='.settings.', suffix='.json')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(settings, f, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, settings_path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    print('v Removed MCP server "sgai" from ~/.claude.json')
else:
    print('  MCP server not found in ~/.claude.json (already removed)')
PY
fi

echo ""
echo "v ScrapeGraphAI extension uninstalled."
echo "  Core Claude SEO skills are unchanged."
echo "  A Google sign-in token, if any, can be dropped with: claude mcp logout sgai"
