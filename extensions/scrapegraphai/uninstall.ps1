# ScrapeGraphAI Extension Uninstaller for Claude SEO (Windows)
$ErrorActionPreference = 'Stop'

Write-Host "Removing ScrapeGraphAI extension..." -ForegroundColor Yellow

$SkillDir = "$env:USERPROFILE\.claude\skills\seo-scrapegraphai"
$McpConfigFile = "$env:USERPROFILE\.claude.json"

if (Test-Path $SkillDir) {
    Remove-Item -Recurse -Force $SkillDir
    Write-Host "v Removed skill files and Python environment" -ForegroundColor Green
}

if (Test-Path $McpConfigFile) {
    $settings = Get-Content $McpConfigFile -Raw | ConvertFrom-Json
    if ($settings.mcpServers.'scrapegraph-mcp') {
        $settings.mcpServers.PSObject.Properties.Remove('scrapegraph-mcp')
        # Write atomically: stage to a temp file in the same directory, then
        # swap it into place, so a crash mid-write never leaves ~/.claude.json
        # truncated (it is shared with Claude Code and other installers).
        # -Depth 100 so deeply nested existing config round-trips intact.
        $TempConfigFile = Join-Path (Split-Path -Parent $McpConfigFile) ".claude.json.$([guid]::NewGuid().ToString('N')).tmp"
        $jsonText = $settings | ConvertTo-Json -Depth 100
        # No byte-order mark: Node's JSON.parse rejects a BOM, which would make ~/.claude.json unreadable.
        [System.IO.File]::WriteAllText($TempConfigFile, $jsonText, (New-Object System.Text.UTF8Encoding $false))
        Move-Item -Path $TempConfigFile -Destination $McpConfigFile -Force
        Write-Host "v Removed MCP server from ~/.claude.json" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "v ScrapeGraphAI extension uninstalled." -ForegroundColor Green
Write-Host "  Core Claude SEO skills are unchanged."
