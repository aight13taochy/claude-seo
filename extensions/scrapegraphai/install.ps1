# ScrapeGraphAI Extension Installer for Claude SEO (Windows)
$ErrorActionPreference = 'Stop'

Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  ScrapeGraphAI Extension - Installer" -ForegroundColor Cyan
Write-Host "  For Claude SEO" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

$SkillDir = "$env:USERPROFILE\.claude\skills\seo-scrapegraphai"
$VenvDir = "$SkillDir\.venv"
$SeoSkillDir = "$env:USERPROFILE\.claude\skills\seo"
# MCP servers live in ~/.claude.json (the file `claude mcp add` writes).
# NOT ~/.claude/settings.json - `mcpServers` is not a key Claude Code reads
# there, so entries written to settings.json silently never load.
$McpConfigFile = "$env:USERPROFILE\.claude.json"
$SgaiMcpVersion = "1.0.1"

# Check prerequisites
if (-not (Test-Path $SeoSkillDir)) {
    Write-Host "x Claude SEO is not installed." -ForegroundColor Red
    Write-Host "  Install it first: irm https://raw.githubusercontent.com/AgriciDaniel/claude-seo/main/install.ps1 | iex"
    exit 1
}
Write-Host "v Claude SEO detected" -ForegroundColor Green

# Resolve a Python 3.10+ interpreter (py launcher first, then python3/python)
$python = $null
foreach ($candidate in @(@{ Exe = 'py'; Args = @('-3') }, @{ Exe = 'python3'; Args = @() }, @{ Exe = 'python'; Args = @() })) {
    if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) { continue }
    $probe = & $candidate.Exe @($candidate.Args) -c "import sys; print(1 if sys.version_info >= (3, 10) else 0)" 2>$null
    if ($probe -eq '1') { $python = $candidate; break }
}
if ($null -eq $python) {
    Write-Host "x Python 3.10+ is required but was not found (tried 'py -3', 'python3', 'python')." -ForegroundColor Red
    Write-Host "  Install Python: https://www.python.org/downloads/"
    exit 1
}
$pyVersion = & $python.Exe @($python.Args) --version 2>&1
Write-Host "v $pyVersion detected" -ForegroundColor Green

# Prompt for API key
Write-Host ""
Write-Host "ScrapeGraphAI API key required." -ForegroundColor Yellow
Write-Host "Sign up at: https://dashboard.scrapegraphai.com"
Write-Host "Free credits are included on sign-up; see the dashboard for current limits."
Write-Host ""

$apiKey = Read-Host "ScrapeGraphAI API key (SGAI_API_KEY)" -AsSecureString
$apiKeyPlain = [System.Net.NetworkCredential]::new("", $apiKey).Password
if ([string]::IsNullOrWhiteSpace($apiKeyPlain)) {
    Write-Host "x API key cannot be empty." -ForegroundColor Red
    exit 1
}

# Determine source directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceDir = $null
if (Test-Path "$ScriptDir\skills\seo-scrapegraphai\SKILL.md") {
    $SourceDir = $ScriptDir
} elseif (Test-Path "$ScriptDir\extensions\scrapegraphai\skills\seo-scrapegraphai\SKILL.md") {
    $SourceDir = "$ScriptDir\extensions\scrapegraphai"
} else {
    Write-Host "x Cannot find extension source files." -ForegroundColor Red
    exit 1
}

# Install skill
Write-Host ""
Write-Host "=> Installing ScrapeGraphAI skill..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path $SkillDir | Out-Null
Copy-Item "$SourceDir\skills\seo-scrapegraphai\SKILL.md" "$SkillDir\SKILL.md" -Force

# Install the MCP server into an isolated virtual environment
Write-Host "=> Creating isolated Python environment..." -ForegroundColor Yellow
$VenvPython = "$VenvDir\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    & $python.Exe @($python.Args) -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { throw "Could not create the virtual environment." }
}

Write-Host "=> Installing scrapegraph-mcp $SgaiMcpVersion (pinned)..." -ForegroundColor Yellow
& $VenvPython -m pip install --quiet --disable-pip-version-check "scrapegraph-mcp==$SgaiMcpVersion"
if ($LASTEXITCODE -ne 0) { throw "pip install failed." }
& $VenvPython -c "import scrapegraph_mcp.server" 2>$null
if ($LASTEXITCODE -ne 0) { throw "scrapegraph-mcp installed but failed to import." }
Write-Host "  v scrapegraph-mcp importable" -ForegroundColor Green

# Configure MCP server in ~/.claude.json.
# The secret travels in the environment (never argv). The writer is a Python
# here-string so the JSON merge is atomic (temp file + os.replace) and refuses
# to touch an unparseable ~/.claude.json. The server is launched via
# `python -c` rather than the console script: main() prints a banner to
# stdout, which corrupts the stdio JSON-RPC framing.
Write-Host "=> Configuring MCP server..." -ForegroundColor Yellow
$py = @"
import json, os, sys, tempfile

settings_path, venv_python = sys.argv[1], sys.argv[2]
api_key = os.environ['CLAUDE_SEO_SECRET']

if os.path.exists(settings_path):
    try:
        with open(settings_path, encoding='utf-8') as f:
            settings = json.load(f)
    except json.JSONDecodeError:
        sys.exit(settings_path + ' is not valid JSON. Nothing was changed; fix it and rerun.')
else:
    settings = {}

settings.setdefault('mcpServers', {})['scrapegraph-mcp'] = {
    'command': venv_python,
    'args': ['-c', "from scrapegraph_mcp.server import mcp; mcp.run(transport='stdio')"],
    'env': {'SGAI_API_KEY': api_key},
}

os.makedirs(os.path.dirname(settings_path) or '.', exist_ok=True)
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(settings_path) or '.', prefix='.claude.json.', suffix='.tmp')
try:
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(settings, f, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, settings_path)
except Exception:
    if os.path.exists(tmp):
        os.unlink(tmp)
    raise

print('  v MCP server configured in ~/.claude.json')
"@
$env:CLAUDE_SEO_SECRET = $apiKeyPlain
try {
    $py | & $VenvPython - $McpConfigFile $VenvPython
    # A native command's non-zero exit does not throw, even with Stop.
    if ($LASTEXITCODE -ne 0) { throw "Nothing was saved (python exited $LASTEXITCODE). See the message above." }
} finally { Remove-Item Env:CLAUDE_SEO_SECRET -ErrorAction SilentlyContinue }
# Restrict the credential-bearing config file to the current user only.
try {
    icacls $McpConfigFile /inheritance:r /grant:r "${env:USERNAME}:F" | Out-Null
} catch {
    Write-Host "  Note: could not restrict ~/.claude.json ACL; review manually." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "v ScrapeGraphAI extension installed!" -ForegroundColor Green
Write-Host ""
Write-Host "Usage:"
Write-Host "  /seo scrapegraphai markdown https://example.com/page"
Write-Host "  /seo scrapegraphai extract https://example.com/page `"list every H2 and its word count`""
Write-Host "  /seo scrapegraphai crawl https://example.com"
Write-Host "  /seo scrapegraphai search `"best running shoes 2026`""
