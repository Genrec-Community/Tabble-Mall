#requires -Version 5.1
<#
.SYNOPSIS
    Stops and removes the MallT print agent from this PC.

.DESCRIPTION
    Removes the scheduled task and the program. Keeps agent.toml, printed-jobs.log and
    the log unless -Purge is given: deleting printed-jobs.log is what makes a PC reprint
    slips the kitchen has already cooked from.
#>
[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'MallTPrintAgent'),
    [string]$TaskName = 'MallT Print Agent',
    [switch]$Purge,
    [switch]$SkipTask
)

$ErrorActionPreference = 'Stop'

$installedExe = Join-Path $InstallDir 'print-agent.exe'
$runner       = Join-Path $InstallDir 'run-agent.ps1'

if (-not $SkipTask -and (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*$runner*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Get-Process -Name 'print-agent' -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -eq $installedExe } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

if ($Purge) {
    Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host 'Removed, including the settings and the printed-slip record.'
    exit 0
}

foreach ($name in 'print-agent.exe', 'run-agent.ps1', 'agent.example.toml', 'print-agent.exe.old', 'print-agent.exe.new', 'print-agent.exe.bad', 'print-agent.trial', 'print-agent.bad') {
    Remove-Item -LiteralPath (Join-Path $InstallDir $name) -Force -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath (Join-Path $InstallDir 'backup') -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "Removed. Settings and the printed-slip record were kept in $InstallDir (add -Purge to delete them)."
