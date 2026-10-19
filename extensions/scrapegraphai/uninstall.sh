#!/usr/bin/env bash
set -euo pipefail

echo "Removing ScrapeGraphAI extension..."

# Remove skill directory (includes the isolated .venv with scrapegraph-mcp)
rm -rf "${HOME}/.claude/skills/seo-scrapegraphai"
echo "v Removed skill files and Python environment"

# Remove MCP entry from settings.json
SETTINGS_FILE="${HOME}/.claude/settings.json"
if [ -f "${SETTINGS_FILE}" ]; then
    python3 - "${SETTINGS_FILE}" <<'PY' || echo "  Warning: Could not update settings.json automatically."
import json, os, sys

settings_path = sys.argv[1]
with open(settings_path, 'r') as f:
    settings = json.load(f)

if 'mcpServers' in settings and 'scrapegraph-mcp' in settings['mcpServers']:
    del settings['mcpServers']['scrapegraph-mcp']
    with open(settings_path, 'w') as f:
        json.dump(settings, f, indent=2)
    print('v Removed MCP server from settings.json')
else:
    print('  MCP server not found in settings.json (already removed)')
PY
fi

echo ""
echo "v ScrapeGraphAI extension uninstalled."
echo "  Core Claude SEO skills are unchanged."
