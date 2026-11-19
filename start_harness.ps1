# ==============================================================================
# Epistemic Harness — Interactive API Key Manager & One-Click Launcher (Windows)
#
# Usage:
#   .\start_harness.ps1              # 默认：检查 8787 + 容器状态，必要时拉起 Docker 一体化后端，然后启动 Pi
#   .\start_harness.ps1 -Configure   # Add / update API keys incrementally at any time
#   .\start_harness.ps1 -LocalDebug  # 开发调试：本机 uvicorn 前台拉起网关（不进 Docker）
# ==============================================================================

param(
    [switch]$Configure,
    [switch]$Login,        # GitHub Copilot 设备码登录（不索取 API key），写入 .secrets/
    [switch]$Global,       # 全局模式：在当前目录启动 pi（不切到仓库），技能装到用户级目录
    [switch]$LocalDebug,   # 开发调试：本机 uvicorn 前台运行，仅特殊排障时使用
    [switch]$Continue,     # 继续当前目录最近的会话（传 pi -c）
    [string]$Resume = "",  # 按会话 ID/路径恢复指定会话（传 pi --session <id>）
    [int]$Port = 8787
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvFile  = Join-Path $RepoRoot ".env"
$VenvPy   = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPy)) {
    Write-Host "[ERROR] .venv not found. Run .\install.ps1 first." -ForegroundColor Red
    exit 1
}

# Ensure .env is git-ignored so secrets are never committed
$GitIgnore = Join-Path $RepoRoot ".gitignore"
if (-not (Test-Path $GitIgnore) -or -not ((Get-Content $GitIgnore -Raw) -match '(?m)^\.env$')) {
    Add-Content -Path $GitIgnore -Value "`n.env`ntraces/`npromotions/`n.venv/`n__pycache__/" -Encoding UTF8
}

$Providers = @(
    @{ Key = "ZHIPU_API_KEY";       UrlKey = "ZHIPU_BASE_URL";          DefaultUrl = "https://open.bigmodel.cn/api/coding/paas/v4";          Label = "[Primary 1] Zhipu V2 Max CodingPlan (glm-5.3 / glm-5.3-flash)" },
    @{ Key = "KIMI_API_KEY";        UrlKey = "KIMI_BASE_URL";           DefaultUrl = "https://api.kimi.com/coding/v1";                           Label = "[Primary 2] Kimi Allegretto (k3.1-pro / kimi-for-coding)" },
    @{ Key = "OPENCODE_GO_API_KEY"; UrlKey = "OPENCODE_GO_BASE_URL";    DefaultUrl = "https://opencode.ai/inference/go/v1";                           Label = "[Primary 3] OpenCode Go Basic (deepseek-v4.1-flash)" },
    @{ Key = "GITHUB_COPILOT_TOKEN";UrlKey = "GITHUB_COPILOT_BASE_URL"; DefaultUrl = "https://api.githubcopilot.com";                        Label = "[Last Option 1] GitHub Copilot Pro+ (claude-fable-5.2 / sonnet-5.5)" },
    @{ Key = "GEMINI_API_KEY";      UrlKey = "GOOGLE_AI_BASE_URL";      DefaultUrl = "https://generativelanguage.googleapis.com/v1beta/openai"; Label = "[Last Option 2] Google AI Pro (gemini-4-neon)" }
)

function Load-EnvMap([string]$Path) {
    $map = [ordered]@{}
    if (Test-Path $Path) {
        foreach ($line in Get-Content $Path -Encoding UTF8) {
            if ($line -match '^\s*([^#\s=]+)\s*=\s*(.*)$') {
                $k = $matches[1].Trim()
                $v = $matches[2].Trim().Trim('"').Trim("'")
                $map[$k] = $v
            }
        }
    }
    return $map
}

function Save-EnvMap([string]$Path, $Map) {
    $lines = @("# Auto-managed by start_harness.ps1 (git-ignored)")
    foreach ($k in $Map.Keys) {
        $lines += "$k=`"$($Map[$k])`""
    }
    Set-Content -Path $Path -Value ($lines -join "`n") -Encoding UTF8
}

function Mask-Key([string]$Val) {
    if ([string]::IsNullOrWhiteSpace($Val)) { return "(not set)" }
    if ($Val.Length -le 8) { return "****" }
    return "$($Val.Substring(0,4))****$($Val.Substring($Val.Length - 4))"
}

function Invoke-CopilotLogin {
    # Device-flow login (same flow Pi uses); writes .secrets/github-copilot.json for the container.
    Write-Host "`n=== GitHub Copilot device login ===" -ForegroundColor Cyan
    Push-Location $RepoRoot
    $env:HARNESS_SECRETS_DIR = (Join-Path $RepoRoot ".secrets")
    & $VenvPy -m proxy_gateway.provider_auth login
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -eq 0) {
        Write-Host "[OK] Copilot credentials stored in .secrets/ (mounted read-only into the container)." -ForegroundColor Green
    } else {
        Write-Host "[WARN] Copilot login did not complete (exit $code)." -ForegroundColor Yellow
    }
    return $code -eq 0
}

if ($Login) {
    if (Invoke-CopilotLogin) { exit 0 } else { exit 1 }
}

# 1. Incremental API Key configuration (auto-runs if .env missing or -Configure passed)
$envMap = Load-EnvMap $EnvFile
if ($Configure -or -not (Test-Path $EnvFile)) {
    Write-Host "`n=== Epistemic Harness API Key Setup (press Enter to keep/skip) ===" -ForegroundColor Cyan
    foreach ($p in $Providers) {
        $cur = if ($envMap.Contains($p.Key)) { $envMap[$p.Key] } else { "" }
        Write-Host "`n$($p.Label)" -ForegroundColor Yellow
        if ($p.Key -eq "GITHUB_COPILOT_TOKEN") {
            # Copilot has no static API key: use the same device-code flow Pi uses.
            $secrets = Join-Path $RepoRoot ".secrets\github-copilot.json"
            if (Test-Path $secrets) {
                Write-Host "  Device-login credentials: present (.secrets/github-copilot.json)" -ForegroundColor DarkGray
            } else {
                Write-Host "  Device-login credentials: not yet acquired" -ForegroundColor DarkGray
            }
            $ans = Read-Host "  Press Enter to run GitHub Copilot device login now (or type 'skip')"
            if ($ans -notmatch '^(skip|s|n)$') { Invoke-CopilotLogin | Out-Null }
            continue
        }
        Write-Host "  Current $($p.Key): $(Mask-Key $cur)" -ForegroundColor DarkGray
        $inputKey = Read-Host "  Enter new $($p.Key) (or press Enter to keep/skip)"
        if (-not [string]::IsNullOrWhiteSpace($inputKey)) {
            $envMap[$p.Key] = $inputKey.Trim()
        }
        if (-not $envMap.Contains($p.UrlKey) -or [string]::IsNullOrWhiteSpace($envMap[$p.UrlKey])) {
            $envMap[$p.UrlKey] = $p.DefaultUrl
        }
    }
    if (-not $envMap.Contains("KIMI_CODING_BASE_URL")) {
        $envMap["KIMI_CODING_BASE_URL"] = "https://api.kimi.com/coding/v1"
    }
    if (-not $envMap.Contains("HARNESS_THINKING_LANG")) {
        $envMap["HARNESS_THINKING_LANG"] = "en_with_native_terms"
    }
    Save-EnvMap $EnvFile $envMap
    Write-Host "`n[OK] Saved keys to $EnvFile (re-run with -Configure anytime to add/update)." -ForegroundColor Green
}

# 2. Export .env into current process environment
foreach ($k in $envMap.Keys) {
    if (-not [string]::IsNullOrWhiteSpace($envMap[$k])) {
        [Environment]::SetEnvironmentVariable($k, $envMap[$k], "Process")
    }
}

# 3. Ensure ~/.pi/agent/models.json includes local Harness proxy provider (with safe backup)
$PiModels = Join-Path $HOME ".pi\agent\models.json"
& $VenvPy -c @"
from datetime import datetime
import json
from pathlib import Path
import shutil

p = Path(r'$PiModels')
p.parent.mkdir(parents=True, exist_ok=True)
data = {}
if p.exists():
    data = json.loads(p.read_text(encoding='utf-8'))
providers = data.setdefault('providers', {})
if 'harness-router' not in providers:
    if p.exists():
        ts = datetime.now().strftime('%Y%m%d%H%M%S')
        shutil.copy2(p, p.with_suffix(f'.json.bak.{ts}'))
    providers['harness-router'] = {
        'baseUrl': 'http://127.0.0.1:$Port/v1',
        'api': 'openai-completions',
        'apiKey': 'local-harness-proxy',
        'models': [
            {'id': 'kimi-k3.1-pro', 'contextWindow': 1048576},
            {'id': 'zhipu-glm-5.3', 'contextWindow': 1048576},
            {'id': 'zhipu-glm-5.3-flash', 'contextWindow': 1048576},
            {'id': 'opencode-deepseek-v4.1-flash', 'contextWindow': 1048576}
        ]
    }
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('[OK] Added harness-router provider to', p)
"@

# 3.5 Import provider credentials configured in Pi (copilot refresh token, google api key) — idempotent.
New-Item -ItemType Directory -Force -Path (Join-Path $RepoRoot ".secrets") | Out-Null
& $VenvPy (Join-Path $RepoRoot "scripts\import_pi_credentials.py") --repo-root $RepoRoot

# 4. Launch harness backend.
#    默认（生产）：Docker 一体化容器（网关 + MCP-over-HTTP）。
#      - 8787 已健康 -> 直接跳过；
#      - 容器在运行但 8787 不健康 -> 告警并提示看日志；
#      - 容器停止或不存在   -> docker compose up -d 拉起/重建。
#    -LocalDebug：本机 uvicorn 前台拉起网关，仅供开发调试。
$HealthUrl = "http://127.0.0.1:$Port/health"

function Wait-HarnessHealthy([int]$Retries = 30) {
    for ($i = 0; $i -lt $Retries; $i++) {
        Start-Sleep -Milliseconds 400
        try {
            $resp = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 2
            if ($resp.status -eq "ok") { return $true }
        } catch {}
    }
    return $false
}

if ($LocalDebug) {
    Write-Host "`n[LocalDebug] 本机 uvicorn 前台启动（Ctrl+C 停止，不进 Docker）: http://127.0.0.1:$Port" -ForegroundColor Cyan
    Push-Location $RepoRoot
    & $VenvPy -m uvicorn proxy_gateway.app:app --host 127.0.0.1 --port $Port
    Pop-Location
    exit 0
}

$backendRunning = $false
try {
    $resp = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 2
    if ($resp.status -eq "ok") { $backendRunning = $true }
} catch {}

if (-not $backendRunning) {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Host "[ERROR] $HealthUrl 无响应，且未找到 docker。`n        请安装 Docker Desktop，或改用 .\start_harness.ps1 -LocalDebug 走本机 uvicorn 调试模式。" -ForegroundColor Red
        exit 1
    }
    Push-Location $RepoRoot
    $containerState = (docker ps -a --filter "name=^harness-backend$" --format "{{.State}}" 2>$null | Select-Object -First 1)
    if ($containerState -eq "running") {
        Write-Host "[WARN] 容器 harness-backend 在运行但 $HealthUrl 未响应，疑似启动中或配置异常。`n         排查: docker compose logs --tail 50" -ForegroundColor Yellow
    } else {
        if ($containerState) {
            Write-Host "`n检测到 harness-backend 容器（状态: $containerState），重新拉起..." -ForegroundColor Cyan
        } else {
            Write-Host "`n未检测到 harness-backend 容器，首次创建并启动（镜像缺失会自动构建，请稍候）..." -ForegroundColor Cyan
        }
        docker compose up -d | Out-Null
    }
    Pop-Location
    if ($containerState -ne "running") {
        $backendRunning = Wait-HarnessHealthy
        if ($backendRunning) {
            Write-Host "[OK] Harness backend 容器已就绪! 配额面板: http://127.0.0.1:$Port/quota  MCP HTTP: http://127.0.0.1:$Port/mcp/epistemic" -ForegroundColor Green
        } else {
            Write-Host "[WARN] 容器启动后 $HealthUrl 仍未就绪，排查: docker compose logs --tail 50" -ForegroundColor Yellow
        }
    }
}

# 5. Launch Pi (repo clean-room by default; -Global launches in the current directory)
if (Get-Command pi -ErrorAction SilentlyContinue) {
    # Global enablement: user-level MCP (HTTP) + user instructions, idempotent.
    $AgentDir = Join-Path $HOME ".pi\agent"
    $UserMcp = Join-Path $AgentDir "mcp.json"
    $UserAgents = Join-Path $AgentDir "AGENTS.md"
    if (-not (Test-Path $UserMcp)) {
        New-Item -ItemType Directory -Force -Path $AgentDir | Out-Null
        @'
{
  "mcpServers": {
    "epistemic-harness":      { "url": "http://127.0.0.1:8787/mcp/epistemic" },
    "epistemic-orchestrator": { "url": "http://127.0.0.1:8787/mcp/orchestrator" }
  }
}
'@ | Set-Content -Path $UserMcp -Encoding UTF8
        Write-Host "[OK] Wrote user-level MCP config: $UserMcp" -ForegroundColor Green
    }
    if (-not (Test-Path $UserAgents)) {
        Copy-Item (Join-Path $RepoRoot "AGENTS.md") $UserAgents
        Write-Host "[OK] Installed global user instructions: $UserAgents" -ForegroundColor Green
    }
    if ($Global) {
        # User-level skills: install everything under clients/skills/ so any working directory picks them up.
        $UserSkillsRoot = Join-Path $AgentDir "skills"
        Get-ChildItem (Join-Path $RepoRoot "clients\skills") -Directory | ForEach-Object {
            $Target = Join-Path $UserSkillsRoot $_.Name
            if (-not (Test-Path (Join-Path $Target "SKILL.md"))) {
                New-Item -ItemType Directory -Force -Path $Target | Out-Null
                Copy-Item (Join-Path $_.FullName "*") $Target -Recurse -Force
                Write-Host "[OK] Installed user-level skill: $($_.Name)" -ForegroundColor Green
            }
        }
        $piArgs = @("--provider", "harness-router", "--model", "opencode-deepseek-v4.1-flash")
        if ($Continue) { $piArgs += "-c" }
        if ($Resume)   { $piArgs += @("--session", $Resume) }
        Write-Host "Launching Pi (global harness mode) in $PWD ...`n" -ForegroundColor Cyan
        pi @piArgs
    } else {
        $piArgs = @("--no-skills", "--skill", ".\clients\skills\epistemic-dual-process-harness", "--provider", "harness-router", "--model", "opencode-deepseek-v4.1-flash")
        if ($Continue) { $piArgs += "-c" }
        if ($Resume)   { $piArgs += @("--session", $Resume) }
        Write-Host "Launching Pi in $RepoRoot ... (use '.\start_harness.ps1 -Configure' anytime to add more keys; -Resume <id> / -Continue to restore sessions)`n" -ForegroundColor Cyan
        Push-Location $RepoRoot
        pi @piArgs
        Pop-Location
    }
} else {
    Write-Host "[WARN] 'pi' command not found on PATH. Open a new terminal or run .\install.ps1." -ForegroundColor Yellow
}
