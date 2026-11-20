# Query Sysmon process-creation events (Event ID 1) by command-line fragment.
# Usage: .\scripts\sysmon_who.ps1 "mcp/orchestrator"
#        .\scripts\sysmon_who.ps1 "grep" -SinceHours 24
param(
    [Parameter(Mandatory = $true)][string]$Fragment,
    [int]$SinceHours = 48,
    [int]$MaxEvents = 200
)
$start = (Get-Date).AddHours(-$SinceHours)
Get-WinEvent -FilterHashtable @{LogName = 'Microsoft-Windows-Sysmon/Operational'; Id = 1; StartTime = $start} -MaxEvents 5000 -ErrorAction SilentlyContinue |
    Where-Object { $_.Message -like "*$Fragment*" } |
    Select-Object -First $MaxEvents | ForEach-Object {
        $x = [xml]$_.ToXml()
        $d = @{}
        foreach ($n in $x.Event.EventData.Data) { $d[$n.Name] = $n.'#text' }
        [PSCustomObject]@{
            Time     = $_.TimeCreated
            Image    = $d.Image
            CmdLine  = $d.CommandLine
            Parent   = $d.ParentImage
            ParentCmd= $d.ParentCommandLine
            PID      = $d.ProcessId
            PPID     = $d.ParentProcessId
        }
    } | Format-List
