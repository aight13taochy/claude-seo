#!/usr/bin/env bash
set -euo pipefail

# ScrapeGraphAI Extension Installer for Claude SEO
# Installs the official scrapegraph-mcp server (Python) into an isolated venv
# and registers it as an MCP server. Wraps everything in main() to prevent
# partial execution on network failure.

main() {
    SKILL_DIR="${HOME}/.claude/skills/seo-scrapegraphai"
    VENV_DIR="${SKILL_DIR}/.venv"
    SEO_SKILL_DIR="${HOME}/.claude/skills/seo"
    # MCP servers live in ~/.claude.json (the file `claude mcp add` writes).
    # NOT ~/.claude/settings.json - `mcpServers` is not a key Claude Code reads
    # there, so entries written to settings.json silently never load.
    MCP_CONFIG_FILE="${HOME}/.claude.json"
    SGAI_MCP_VERSION="1.0.1"

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

    if ! command -v python3 >/dev/null 2>&1; then
        echo "x Python 3.10+ is required but python3 was not found."
        echo "  Install Python: https://www.python.org/downloads/"
        exit 1
    fi
    if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
        echo "x Python 3.10+ required (found $(python3 --version 2>&1))."
        exit 1
    fi
    echo "v $(python3 --version 2>&1) detected"

    if ! python3 -c 'import venv, ensurepip' >/dev/null 2>&1; then
        echo "x Python 'venv' module is missing."
        echo "  Debian/Ubuntu: sudo apt install python3-venv"
        exit 1
    fi

    # Prompt for credentials
    echo ""
    echo "ScrapeGraphAI API key required."
    echo "Sign up at: https://dashboard.scrapegraphai.com"
    echo "Free credits are included on sign-up; see the dashboard for current limits."
    echo ""

    read -rsp "ScrapeGraphAI API key (SGAI_API_KEY): " SGAI_API_KEY
    echo ""
    if [ -z "${SGAI_API_KEY}" ]; then
        echo "x API key cannot be empty."
        exit 1
    fi

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

    # Install the MCP server into an isolated virtual environment
    echo "-> Creating isolated Python environment..."
    if [ ! -x "${VENV_DIR}/bin/python" ]; then
        python3 -m venv "${VENV_DIR}"
    fi
    VENV_PYTHON="${VENV_DIR}/bin/python"

    echo "-> Installing scrapegraph-mcp ${SGAI_MCP_VERSION} (pinned)..."
    "${VENV_PYTHON}" -m pip install --quiet --disable-pip-version-check \
        "scrapegraph-mcp==${SGAI_MCP_VERSION}"

    if ! "${VENV_PYTHON}" -c 'import scrapegraph_mcp.server' >/dev/null 2>&1; then
        echo "x scrapegraph-mcp installed but failed to import. Check the pip output above."
        exit 1
    fi
    echo "  v scrapegraph-mcp importable"

    # Merge MCP config into ~/.claude.json
    echo "-> Configuring MCP server..."

    # Credentials travel in the environment (never argv, never interpolated into the source string)
    # and the config file is written atomically with 0600 permissions.
    #
    # The server is launched via `python -c` instead of the `scrapegraph-mcp`
    # console script: the console script's main() prints a banner to stdout,
    # which corrupts the stdio JSON-RPC framing. Calling mcp.run() directly
    # keeps stdout clean.
    CLAUDE_SEO_SECRET="${SGAI_API_KEY}" python3 - "${MCP_CONFIG_FILE}" "${VENV_PYTHON}" <<'PY'
import json, os, sys, tempfile

settings_path, venv_python = sys.argv[1], sys.argv[2]
api_key = os.environ["CLAUDE_SEO_SECRET"]

if os.path.exists(settings_path):
    try:
        with open(settings_path) as f:
            settings = json.load(f)
    except json.JSONDecodeError:
        sys.exit(f"✗ {settings_path} is not valid JSON. Nothing was changed; fix it and rerun.")
else:
    settings = {}

settings.setdefault('mcpServers', {})['scrapegraph-mcp'] = {
    'command': venv_python,
    'args': ['-c', "from scrapegraph_mcp.server import mcp; mcp.run(transport='stdio')"],
    'env': {
        'SGAI_API_KEY': api_key,
    },
}

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

print('  v MCP server configured in ~/.claude.json')
PY

    echo ""
    echo "v ScrapeGraphAI extension installed successfully!"
    echo ""
    echo "Usage:"
    echo "  1. Start Claude Code:  claude"
    echo "  2. Run commands:"
    echo "     /seo scrapegraphai markdown https://example.com/page"
    echo "     /seo scrapegraphai extract https://example.com/page \"list every H2 and its word count\""
    echo "     /seo scrapegraphai crawl https://example.com"
    echo "     /seo scrapegraphai search \"best running shoes 2026\""
    echo ""
    echo "Documentation: extensions/scrapegraphai/README.md"
    echo "To uninstall: ./extensions/scrapegraphai/uninstall.sh"
}

main "$@"
