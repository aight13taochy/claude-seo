# ScrapeGraphAI Extension Installer for Claude SEO (Windows)
# Registers ScrapeGraphAI's hosted MCP server (HTTP transport) in ~/.claude.json
# and copies the seo-scrapegraphai skill. No Python package, no venv.
$ErrorActionPreference = 'Stop'

Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  ScrapeGraphAI Extension - Installer" -ForegroundColor Cyan
Write-Host "  For Claude SEO" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

$SkillDir = "$env:USERPROFILE\.claude\skills\seo-scrapegraphai"
$SeoSkillDir = "$env:USERPROFILE\.claude\skills\seo"
# MCP servers live in ~/.claude.json (the file `claude mcp add` writes).
# NOT ~/.claude/settings.json - `mcpServers` is not a key Claude Code reads
# there, so entries written to settings.json silently never load.
$McpConfigFile = "$env:USERPROFILE\.claude.json"
# The public hostname is https://mcp.scrapegraphai.com/mcp, but its OAuth
# metadata declares the onrender URL as the protected resource, so Claude Code
# refuses the public hostname ("Protected resource does not match").
$SgaiMcpUrl = "https://sgai-mcp-main.onrender.com/mcp"

# Check prerequisites
if (-not (Test-Path $SeoSkillDir)) {
    Write-Host "x Claude SEO is not installed." -ForegroundColor Red
    Write-Host "  Install it first: irm https://raw.githubusercontent.com/AgriciDaniel/claude-seo/main/install.ps1 | iex"
    exit 1
}
Write-Host "v Claude SEO detected" -ForegroundColor Green

# Any Python 3 works: it only merges JSON into ~/.claude.json.
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Python 3 is required to update ~/.claude.json safely." }

# Prompt for API key (optional: the hosted server also accepts Google sign-in)
Write-Host ""
Write-Host "Authentication: Google sign-in (run 'claude mcp login sgai' afterwards)" -ForegroundColor Yellow
Write-Host "or an API key from https://dashboard.scrapegraphai.com (starts with sgai-)."
Write-Host "Older sk-... keys are rejected by the new API; generate an sgai- key."
Write-Host ""

$apiKey = Read-Host "ScrapeGraphAI API key (sgai-..., leave empty for Google sign-in)" -AsSecureString
$apiKeyPlain = [System.Net.NetworkCredential]::new("", $apiKey).Password

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

# Configure MCP server in ~/.claude.json.
# The secret travels in the environment (never argv). The writer is a Python
# here-string so the JSON merge is atomic (temp file + os.replace) and refuses
# to touch an unparseable ~/.claude.json.
Write-Host "=> Configuring MCP server..." -ForegroundColor Yellow
$py = @"
import json, os, sys, tempfile

settings_path = sys.argv[1]
api_key = os.environ.get('CLAUDE_SEO_SECRET', '')
url = os.environ.get('SGAI_MCP_URL', 'https://sgai-mcp-main.onrender.com/mcp')

if os.path.exists(settings_path):
    try:
        with open(settings_path, encoding='utf-8') as f:
            settings = json.load(f)
    except json.JSONDecodeError:
        sys.exit(settings_path + ' is not valid JSON. Nothing was changed; fix it and rerun.')
else:
    settings = {}

server = {'type': 'http', 'url': url}
if api_key:
    # Bearer is rejected ('no token payload'); the server reads X-API-Key.
    server['headers'] = {'X-API-Key': api_key}
settings.setdefault('mcpServers', {})['sgai'] = server

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

print('  v MCP server "sgai" configured in ~/.claude.json')
"@
$env:CLAUDE_SEO_SECRET = $apiKeyPlain
$env:SGAI_MCP_URL = $SgaiMcpUrl
try {
    $py | python - $McpConfigFile
    # A native command's non-zero exit does not throw, even with Stop.
    if ($LASTEXITCODE -ne 0) { throw "Nothing was saved (python exited $LASTEXITCODE). See the message above." }
} finally {
    Remove-Item Env:CLAUDE_SEO_SECRET -ErrorAction SilentlyContinue
    Remove-Item Env:SGAI_MCP_URL -ErrorAction SilentlyContinue
}
if (-not [string]::IsNullOrWhiteSpace($apiKeyPlain)) {
    # Restrict the credential-bearing config file to the current user only.
    try {
        icacls $McpConfigFile /inheritance:r /grant:r "${env:USERNAME}:F" | Out-Null
    } catch {
        Write-Host "  Note: could not restrict ~/.claude.json ACL; review manually." -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "v ScrapeGraphAI extension installed!" -ForegroundColor Green
Write-Host ""
if ([string]::IsNullOrWhiteSpace($apiKeyPlain)) {
    Write-Host "Next step (Google sign-in):" -ForegroundColor Yellow
    Write-Host "  claude mcp login sgai"
    Write-Host ""
}
Write-Host "Usage:"
Write-Host "  /seo scrapegraphai markdown https://example.com/page"
Write-Host "  /seo scrapegraphai extract https://example.com/page `"list every H2 and its word count`""
Write-Host "  /seo scrapegraphai search `"best running shoes 2026`""
Write-Host "  /seo scrapegraphai crawl https://example.com"
