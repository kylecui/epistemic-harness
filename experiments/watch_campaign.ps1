param([Parameter(Mandatory=$true)][int]$CampaignPid, [string]$Repo = (Split-Path -Parent -Parent $PSScriptRoot))
# Host-side watchdog for experiments/run_campaign.py (detached, survives agent sessions).
# Polls the campaign process once a minute; on exit writes experiments/campaign.status
# and pops a Windows message so the human does not have to babysit the log.
$runsDir = Join-Path $Repo 'experiments\runs'
$status = Join-Path $Repo 'experiments\campaign.status'
"watching pid $CampaignPid since $(Get-Date -Format s)" | Set-Content $status
while (Get-Process -Id $CampaignPid -ErrorAction SilentlyContinue) {
    $done = (Get-ChildItem (Join-Path $runsDir '*.jsonl') -ErrorAction SilentlyContinue | Where-Object { $_.Name -notlike '*.judged.jsonl' }).Count
    "running pid $CampaignPid cells_done=$done/30 at $(Get-Date -Format s)" | Set-Content $status
    Start-Sleep -Seconds 60
}
$cells = (Get-ChildItem (Join-Path $runsDir '*.jsonl') -ErrorAction SilentlyContinue | Where-Object { $_.Name -notlike '*.judged.jsonl' }).Count
$judged = (Get-ChildItem (Join-Path $runsDir '*.judged.jsonl') -ErrorAction SilentlyContinue).Count
$tail = if (Test-Path (Join-Path $Repo 'experiments\campaign.log')) { (Get-Content (Join-Path $Repo 'experiments\campaign.log') -Tail 3) -join ' | ' } else { '' }
"done $(Get-Date -Format s) cells=$cells/30 judged=$judged/30 tail: $tail" | Set-Content $status
try { msg * "epistemic-harness campaign finished: cells=$cells/30 judged=$judged/30 (see experiments\campaign.status)" } catch { Write-Beep 880, 600 }
