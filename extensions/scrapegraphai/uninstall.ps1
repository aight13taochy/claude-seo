# ScrapeGraphAI Extension Uninstaller for Claude SEO (Windows)
$ErrorActionPreference = 'Stop'

Write-Host "Removing ScrapeGraphAI extension..." -ForegroundColor Yellow

$SkillDir = "$env:USERPROFILE\.claude\skills\seo-scrapegraphai"
$SettingsFile = "$env:USERPROFILE\.claude\settings.json"

if (Test-Path $SkillDir) {
    Remove-Item -Recurse -Force $SkillDir
    Write-Host "v Removed skill files and Python environment" -ForegroundColor Green
}

if (Test-Path $SettingsFile) {
    $settings = Get-Content $SettingsFile -Raw | ConvertFrom-Json
    if ($settings.mcpServers.'scrapegraph-mcp') {
        $settings.mcpServers.PSObject.Properties.Remove('scrapegraph-mcp')
        $settings | ConvertTo-Json -Depth 10 | Set-Content $SettingsFile -Encoding UTF8
        Write-Host "v Removed MCP server from settings.json" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "v ScrapeGraphAI extension uninstalled." -ForegroundColor Green
Write-Host "  Core Claude SEO skills are unchanged."
