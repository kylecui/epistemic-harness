# Epistemic Dual-Process Harness — One-Click Installer (Windows PowerShell)
param(
    [switch]$SkipPi,
    [switch]$ViaNpm
)
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "[1/5] Checking Python 3.10+..." -ForegroundColor Cyan
python --version

if (-not $SkipPi) {
    Write-Host "[2/5] Checking / installing Pi Coding Agent..." -ForegroundColor Cyan
    if (-not (Get-Command pi -ErrorAction SilentlyContinue)) {
        if ($ViaNpm) {
            npm install -g @earendil-works/pi-coding-agent
        } else {
            irm https://pi.dev/install.ps1 | iex
        }
    }
}

Write-Host "[3/5] Creating isolated .venv & installing dependencies..." -ForegroundColor Cyan
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    python -m venv (Join-Path $RepoRoot ".venv")
}
& $VenvPython -m pip install --upgrade pip | Out-Null
& $VenvPython -m pip install pyyaml pydantic fastapi uvicorn httpx

Write-Host "[4/7] Wiring .pi/mcp.json (HTTP) & compiling AGENTS.md..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path (Join-Path $RepoRoot ".pi") | Out-Null
@'
{
  "mcpServers": {
    "epistemic-harness":      { "url": "http://127.0.0.1:8787/mcp/epistemic" },
    "epistemic-orchestrator": { "url": "http://127.0.0.1:8787/mcp/orchestrator" }
  }
}
'@ | Set-Content -Path (Join-Path $RepoRoot ".pi\mcp.json") -Encoding UTF8
& $VenvPython (Join-Path $RepoRoot "scripts\compile_clients.py")

Write-Host "[5/7] Running automated tests & mock Golden Eval suite..." -ForegroundColor Cyan
Push-Location $RepoRoot
& $VenvPython -m unittest discover -s tests
& $VenvPython evals\run_evals.py --mock
Pop-Location

Write-Host "[6/7] Global enablement (user-level MCP / instructions / skill / alias)..." -ForegroundColor Cyan
$AgentDir = Join-Path $HOME ".pi\agent"
New-Item -ItemType Directory -Force -Path $AgentDir | Out-Null
if (-not (Test-Path (Join-Path $AgentDir "mcp.json"))) {
    @'
{
  "mcpServers": {
    "epistemic-harness":      { "url": "http://127.0.0.1:8787/mcp/epistemic" },
    "epistemic-orchestrator": { "url": "http://127.0.0.1:8787/mcp/orchestrator" }
  }
}
'@ | Set-Content -Path (Join-Path $AgentDir "mcp.json") -Encoding UTF8
    Write-Host "  [OK] user-level mcp.json"
}
if (-not (Test-Path (Join-Path $AgentDir "AGENTS.md"))) {
    Copy-Item (Join-Path $RepoRoot "AGENTS.md") (Join-Path $AgentDir "AGENTS.md")
    Write-Host "  [OK] user-level AGENTS.md"
}
$UserSkillsRoot = Join-Path $AgentDir "skills"
Get-ChildItem (Join-Path $RepoRoot "clients\skills") -Directory | ForEach-Object {
    $Target = Join-Path $UserSkillsRoot $_.Name
    if (-not (Test-Path (Join-Path $Target "SKILL.md"))) {
        New-Item -ItemType Directory -Force -Path $Target | Out-Null
        Copy-Item (Join-Path $_.FullName "*") $Target -Recurse -Force
        Write-Host "  [OK] user-level skill: $($_.Name)"
    }
}
$HarnessFn = "function harness { & `"$RepoRoot\start_harness.ps1`" -Global @args }"
foreach ($prof in @("$HOME\Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1",
                    "$HOME\Documents\PowerShell\Microsoft.PowerShell_profile.ps1")) {
    $dir = Split-Path $prof
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $existing = if (Test-Path $prof) { Get-Content $prof -Raw } else { "" }
    if ($existing -notmatch "function harness") {
        Add-Content -Path $prof -Value "`n# Epistemic Harness — global launcher`n$HarnessFn`n"
        Write-Host "  [OK] harness function -> $prof"
    }
}
$BashRc = Join-Path $HOME ".bashrc"
if ((Test-Path $BashRc) -and -not (Select-String -Path $BashRc -Pattern "alias harness=" -Quiet -ErrorAction SilentlyContinue)) {
    Add-Content -Path $BashRc -Value "`nalias harness='$($RepoRoot -replace '\\','/')/start_harness.sh --global'"
    Write-Host "  [OK] harness alias -> $BashRc"
}

Write-Host "[7/7] Importing Pi credentials, extensions & building container image..." -ForegroundColor Cyan
$UserExt = Join-Path $AgentDir "extensions"
New-Item -ItemType Directory -Force -Path $UserExt | Out-Null
Get-ChildItem (Join-Path $RepoRoot "extensions") -File -ErrorAction SilentlyContinue | ForEach-Object {
    if (-not (Test-Path (Join-Path $UserExt $_.Name))) {
        Copy-Item $_.FullName $UserExt
        Write-Host "  [OK] extension: $($_.Name)"
    }
}
& $VenvPython (Join-Path $RepoRoot "scripts\import_pi_credentials.py") --repo-root $RepoRoot
if (Get-Command docker -ErrorAction SilentlyContinue) {
    Push-Location $RepoRoot
    docker compose build 2>&1 | Select-Object -Last 1
    Pop-Location
    Write-Host "  [OK] container image built"
} else {
    Write-Host "  [WARN] docker not found; start_harness will fall back or prompt." -ForegroundColor Yellow
}

Write-Host "`nInstallation complete!" -ForegroundColor Green
Write-Host "  Global:   open any directory and run 'harness' (restart terminal for the alias)" -ForegroundColor Cyan
Write-Host "  Repo:     .\start_harness.ps1            (clean-room mode)" -ForegroundColor Cyan
Write-Host "  Models:   .\start_harness.ps1 -Configure (only thing you may ever need to touch)" -ForegroundColor Cyan
