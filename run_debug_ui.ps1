param(
  [int]$Port = 8080,
  [string]$DebugToken = $([guid]::NewGuid().ToString("N")),
  [string]$ApiToken = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

$env:NF_ENABLE_DEBUG_WEB_UI = "1"
$env:NF_DEBUG_WEB_UI_TOKEN = $DebugToken
if ([string]::IsNullOrWhiteSpace($ApiToken)) {
  Remove-Item Env:NF_ORCHESTRATOR_TOKEN -ErrorAction SilentlyContinue
} else {
  $env:NF_ORCHESTRATOR_TOKEN = $ApiToken
}

$url = "http://127.0.0.1:$Port/_debug?debug_token=$DebugToken"
Write-Host ""
Write-Host "nf debug web UI"
Write-Host "- URL: $url"
if (-not [string]::IsNullOrWhiteSpace($ApiToken)) {
  Write-Host "- API token: $ApiToken (paste into the UI's 'API token' field)"
}
Write-Host "- Stop: Ctrl+C"
Write-Host ""

Start-Job -ScriptBlock {
  Start-Sleep -Milliseconds 800
  Start-Process $using:url | Out-Null
} | Out-Null

python -c "from modules.nf_orchestrator import run_orchestrator; run_orchestrator('127.0.0.1', $Port)"

