#!/usr/bin/env bash
set -euo pipefail

# ScrapeGraphAI Extension Installer for Claude SEO
# Registers ScrapeGraphAI's hosted MCP server (HTTP transport) in ~/.claude.json
# and copies the seo-scrapegraphai skill. Nothing is installed locally: no
# Python package, no virtual environment. Wrapped in main() to prevent partial
# execution if the script is cut off mid-download.

main() {
    SKILL_DIR="${HOME}/.claude/skills/seo-scrapegraphai"
    SEO_SKILL_DIR="${HOME}/.claude/skills/seo"
    # MCP servers live in ~/.claude.json (the file `claude mcp add` writes).
    # NOT ~/.claude/settings.json - `mcpServers` is not a key Claude Code reads
    # there, so entries written to settings.json silently never load.
    MCP_CONFIG_FILE="${HOME}/.claude.json"
    # The public hostname is https://mcp.scrapegraphai.com/mcp, but its OAuth
    # metadata declares the onrender URL as the protected resource. Claude Code
    # refuses the public hostname ("Protected resource does not match"), so the
    # onrender URL is the one that works for both Google sign-in and API keys.
    SGAI_MCP_URL="https://sgai-mcp-main.onrender.com/mcp"

    echo "════════════════════════════════════════"
    echo "║   ScrapeGraphAI Extension - Installer ║"
    echo "║   For Claude SEO                      ║"
    echo "════════════════════════════════════════"
    echo ""

    # Check prerequisites
    if [ ! -d "${SEO_SKILL_DIR}" ]; then
        echo "x Claude SEO is not installed."
        echo "  Install it first: curl -fsSL https://raw.githubusercontent.com/AgriciDaniel/claude-seo/main/install.sh | bash"
        exit 1
    fi
    echo "v Claude SEO detected"

    # Any python3 works: it only merges JSON (the venv requirement is gone).
    if ! command -v python3 >/dev/null 2>&1; then
        echo "x python3 is required to update ~/.claude.json safely."
        exit 1
    fi

    # Prompt for credentials (optional: the hosted server also accepts Google sign-in)
    echo ""
    echo "Authentication: Google sign-in (run 'claude mcp login sgai' afterwards)"
    echo "or an API key from https://dashboard.scrapegraphai.com (starts with sgai-)."
    echo "Older sk-... keys are rejected by the new API; generate an sgai- key."
    echo ""

    read -rsp "ScrapeGraphAI API key (sgai-..., leave empty for Google sign-in): " SGAI_API_KEY
    echo ""

    # Determine script directory (works for both ./install.sh and curl|bash)
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    # Check if running from repo or standalone
    if [ -f "${SCRIPT_DIR}/skills/seo-scrapegraphai/SKILL.md" ]; then
        SOURCE_DIR="${SCRIPT_DIR}"
    elif [ -f "${SCRIPT_DIR}/extensions/scrapegraphai/skills/seo-scrapegraphai/SKILL.md" ]; then
        SOURCE_DIR="${SCRIPT_DIR}/extensions/scrapegraphai"
    else
        echo "x Cannot find extension source files."
        echo "  Run this script from the claude-seo repo: ./extensions/scrapegraphai/install.sh"
        exit 1
    fi

    # Install skill
    echo ""
    echo "-> Installing ScrapeGraphAI skill..."
    mkdir -p "${SKILL_DIR}"
    cp "${SOURCE_DIR}/skills/seo-scrapegraphai/SKILL.md" "${SKILL_DIR}/SKILL.md"

    # Merge MCP config into ~/.claude.json
    echo "-> Configuring MCP server..."

    # Credentials travel in the environment (never argv, never interpolated into the source string)
    # and the config file is written atomically with 0600 permissions.
    CLAUDE_SEO_SECRET="${SGAI_API_KEY}" SGAI_MCP_URL="${SGAI_MCP_URL}" python3 - "${MCP_CONFIG_FILE}" <<'PY'
import json, os, sys, tempfile

settings_path = sys.argv[1]
api_key = os.environ.get("CLAUDE_SEO_SECRET", "")
url = os.environ.get("SGAI_MCP_URL", "https://sgai-mcp-main.onrender.com/mcp")

if os.path.exists(settings_path):
    try:
        with open(settings_path) as f:
            settings = json.load(f)
    except json.JSONDecodeError:
        sys.exit(f"✗ {settings_path} is not valid JSON. Nothing was changed; fix it and rerun.")
else:
    settings = {}

server = {'type': 'http', 'url': url}
if api_key:
    # Bearer is rejected ("no token payload"); the server reads X-API-Key.
    server['headers'] = {'X-API-Key': api_key}
settings.setdefault('mcpServers', {})['sgai'] = server

os.makedirs(os.path.dirname(settings_path) or '.', exist_ok=True)
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

print('  v MCP server "sgai" configured in ~/.claude.json')
PY

    echo ""
    echo "v ScrapeGraphAI extension installed successfully!"
    echo ""
    if [ -z "${SGAI_API_KEY}" ]; then
        echo "Next step (Google sign-in):"
        echo "  claude mcp login sgai"
        echo ""
    fi
    echo "Usage:"
    echo "  1. Start Claude Code:  claude"
    echo "  2. Run commands:"
    echo "     /seo scrapegraphai markdown https://example.com/page"
    echo "     /seo scrapegraphai extract https://example.com/page \"list every H2 and its word count\""
    echo "     /seo scrapegraphai search \"best running shoes 2026\""
    echo "     /seo scrapegraphai crawl https://example.com"
    echo ""
    echo "Documentation: extensions/scrapegraphai/README.md"
    echo "To uninstall: ./extensions/scrapegraphai/uninstall.sh"
}

main "$@"
