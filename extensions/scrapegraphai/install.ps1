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
$SettingsFile = "$env:USERPROFILE\.claude\settings.json"
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
$apiKeyPlain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($apiKey))
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
    if ($LASTEXITCODE -ne 0) { Write-Host "x Could not create the virtual environment." -ForegroundColor Red; exit 1 }
}

Write-Host "=> Installing scrapegraph-mcp $SgaiMcpVersion (pinned)..." -ForegroundColor Yellow
& $VenvPython -m pip install --quiet --disable-pip-version-check "scrapegraph-mcp==$SgaiMcpVersion"
if ($LASTEXITCODE -ne 0) { Write-Host "x pip install failed." -ForegroundColor Red; exit 1 }
& $VenvPython -c "import scrapegraph_mcp.server" 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host "x scrapegraph-mcp installed but failed to import." -ForegroundColor Red; exit 1 }
Write-Host "  v scrapegraph-mcp importable" -ForegroundColor Green

# Configure MCP server.
# Launched via `python -c` rather than the console script: main() prints a banner
# to stdout, which corrupts the stdio JSON-RPC framing.
Write-Host "=> Configuring MCP server..." -ForegroundColor Yellow
$settingsContent = if (Test-Path $SettingsFile) { Get-Content $SettingsFile -Raw | ConvertFrom-Json } else { @{} }
if (-not $settingsContent.mcpServers) { $settingsContent | Add-Member -NotePropertyName mcpServers -NotePropertyValue @{} -Force }
$settingsContent.mcpServers | Add-Member -NotePropertyName 'scrapegraph-mcp' -NotePropertyValue @{
    command = $VenvPython
    args = @('-c', "from scrapegraph_mcp.server import mcp; mcp.run(transport='stdio')")
    env = @{ SGAI_API_KEY = $apiKeyPlain }
} -Force
$settingsContent | ConvertTo-Json -Depth 10 | Set-Content $SettingsFile -Encoding UTF8
# Restrict the credential-bearing settings file to the current user only.
try {
    icacls $SettingsFile /inheritance:r /grant:r "${env:USERNAME}:F" | Out-Null
} catch {
    Write-Host "  Note: could not restrict settings.json ACL; review manually." -ForegroundColor Yellow
}
Write-Host "  v MCP server configured" -ForegroundColor Green

Write-Host ""
Write-Host "v ScrapeGraphAI extension installed!" -ForegroundColor Green
Write-Host ""
Write-Host "Usage:"
Write-Host "  /seo scrapegraphai markdown https://example.com/page"
Write-Host "  /seo scrapegraphai extract https://example.com/page `"list every H2 and its word count`""
Write-Host "  /seo scrapegraphai crawl https://example.com"
Write-Host "  /seo scrapegraphai search `"best running shoes 2026`""
