# Weekly style/anti-jargon A/B sweep (scheduled task target).
# Runs the periodic eval against the two primary families and appends history + report.
$ErrorActionPreference = "Stop"
$Repo = "D:\MyWorkSpaces\epistemic-harness"
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
$Stamp = Get-Date -Format "yyyyMMdd-HHmm"
$Log = Join-Path $Repo "evals\style_ab_weekly_$Stamp.log"

Push-Location $Repo
& $Python scripts\style_ab_periodic.py --models "opencode-deepseek-v4.1-flash,zhipu-glm-5.3" 2>&1 | Tee-Object -FilePath $Log
$exit = $LASTEXITCODE
Pop-Location

if ($exit -eq 2) {
    Write-Host "[style-ab] REGRESSION detected — see $Log" -ForegroundColor Yellow
} elseif ($exit -eq 0) {
    Write-Host "[style-ab] all green — $Log" -ForegroundColor Green
} else {
    Write-Host "[style-ab] runner error ($exit) — see $Log" -ForegroundColor Red
}
exit $exit
