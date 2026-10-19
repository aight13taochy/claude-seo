#!/usr/bin/env bash
# SessionStart hook for this fork's checkout.
#
# Claude Code installs the claude-seo plugin from .claude/settings.json
# (extraKnownMarketplaces + enabledPlugins). The plugin's Python runtime and
# Chromium are not part of that install; they come from `claude-seo setup`,
# which this hook runs in the background when the runtime is not ready yet.
# In an ephemeral cloud container that is every session; on a developer
# machine it is a no-op after the first run.
#
# Never fails the session: every path exits 0. Output goes to Claude's
# context so it knows whether the runtime is usable.
set -uo pipefail

data_dir="${CLAUDE_SEO_DATA_DIR:-$HOME/.claude/plugins/data/claude-seo}"
data_dir="${data_dir/#\~/$HOME}"
cache_root="${CLAUDE_CODE_PLUGIN_CACHE_DIR:-$HOME/.claude/plugins}/cache/agricidaniel-claude-seo/claude-seo"

plugin_root=""
if [ -d "$cache_root" ]; then
  plugin_root="$(ls -d "$cache_root"/*/ 2>/dev/null | sort -V | tail -1)"
  plugin_root="${plugin_root%/}"
fi

if [ -z "$plugin_root" ] || [ ! -x "$plugin_root/scripts/claude-seo" ]; then
  echo "claude-seo: plugin not installed yet in this session. If it is still missing after startup, run: claude plugin install claude-seo@agricidaniel-claude-seo"
  exit 0
fi

export CLAUDE_PLUGIN_ROOT="$plugin_root"
export CLAUDE_SEO_DATA_DIR="$data_dir"

status="$("$plugin_root/scripts/claude-seo" doctor 2>/dev/null || true)"
if printf '%s' "$status" | grep -q "Runtime: ready" && printf '%s' "$status" | grep -q "Chromium: ready"; then
  echo "claude-seo: runtime ready ($plugin_root)."
  exit 0
fi

mkdir -p "$data_dir"
log="$data_dir/setup.log"
if [ -f "$data_dir/.setup.lock" ] && pgrep -f "claude-seo.*setup" >/dev/null 2>&1; then
  echo "claude-seo: runtime setup already running in the background (log: $log)."
  exit 0
fi

nohup "$plugin_root/scripts/claude-seo" setup >"$log" 2>&1 &
echo "claude-seo: runtime setup started in the background (2 to 3 minutes; log: $log). Check with: \"$plugin_root/scripts/claude-seo\" doctor"
exit 0
