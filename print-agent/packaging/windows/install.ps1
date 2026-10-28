#requires -Version 5.1
<#
.SYNOPSIS
    Installs the MallT print agent on this PC, checks it can pair, and starts it.

.DESCRIPTION
    One command, run from the unzipped folder:
      powershell -ExecutionPolicy Bypass -File install.ps1 -Url https://... -Token ...

    Safe to run again: that is the upgrade. The program is replaced; the token is
    replaced; every other setting in agent.toml and the printed-slip record are kept.
    If the server refuses the token or cannot be reached, nothing is left changed: a
    working install stays working and a fresh PC is left clean.

    -SkipTask skips Task Scheduler and the live wait. It exists for the test suite.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Url,
    [Parameter(Mandatory)][string]$Token,
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'MallTPrintAgent'),
    [string]$TaskName = 'MallT Print Agent',
    [switch]$SkipTask,
    [int]$LiveSeconds = 30
)

$ErrorActionPreference = 'Stop'

# The task is switched off while files are being replaced: its five-minute tick must not
# start the supervisor on a half-installed program. Every way out switches it back on.
$script:taskDisabled = $false
function Enable-Task {
    if ($script:taskDisabled) {
        Enable-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Out-Null
        $script:taskDisabled = $false
    }
}

# An unexpected error (a full disk, a file locked by antivirus) must not leave a working
# PC with its task switched off.
trap {
    Enable-Task
    break
}

function Fail([string]$Message) {
    Enable-Task
    Write-Host "Install stopped: $Message" -ForegroundColor Red
    exit 1
}

# --- 1. Refuse anything that is not what the dashboard generates ---------------------
# Only these characters ever need to pass, so values never need quoting in PowerShell,
# cmd.exe or TOML -- and a pasted command that was damaged on the way is refused here,
# before a single file is touched.
if ($Url -notmatch '^(https?|wss?)://[A-Za-z0-9.-]+(:[0-9]+)?(/[A-Za-z0-9._~%/-]*)?$') {
    Fail 'the address is not valid. Paste the command from the dashboard exactly as shown.'
}
if ($Token -notmatch '^[A-Za-z0-9._~+/=-]+$') {
    Fail 'the token contains characters it never has. Paste the command from the dashboard exactly as shown.'
}
if ($Token -eq 'PASTE-THE-PAIRING-TOKEN-HERE' -or $Url -like '*mallt.example.com*') {
    Fail 'that is the placeholder from the example file. Use the command the dashboard shows after "Pair a PC".'
}

$source = Join-Path $PSScriptRoot 'print-agent.exe'
if (-not (Test-Path -LiteralPath $source)) {
    Fail 'print-agent.exe is not next to install.ps1. Run this from the unzipped folder.'
}

$installedExe = Join-Path $InstallDir 'print-agent.exe'
$runner       = Join-Path $InstallDir 'run-agent.ps1'
$config       = Join-Path $InstallDir 'agent.toml'
$log          = Join-Path $InstallDir 'print-agent.log'
$backup       = Join-Path $InstallDir 'backup'
$ours         = @('print-agent.exe', 'run-agent.ps1', 'agent.example.toml')
$stoppedFlag  = Join-Path $InstallDir 'stopped.flag'

$firstInstall = -not (Test-Path -LiteralPath $installedExe)
$hadConfig    = Test-Path -LiteralPath $config
$taskExisted  = $false
if (-not $SkipTask) {
    $taskExisted = [bool](Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)
}

function Stop-Agent {
    if (-not $SkipTask -and $taskExisted) {
        Disable-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Out-Null
        $script:taskDisabled = $true
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    }
    # The supervisor first, or it would restart the agent the moment it is killed.
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -like "*$runner*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Get-Process -Name 'print-agent' -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $installedExe } |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
    # A just-stopped program can stay locked for a moment (the loader, antivirus scanning
    # it). Wait, up to ten seconds, until it can be replaced instead of failing the copy.
    for ($i = 0; ($i -lt 40) -and (Test-Path -LiteralPath $installedExe); $i++) {
        try {
            [System.IO.File]::Open($installedExe, 'Open', 'ReadWrite', 'None').Dispose()
            break
        } catch {
            Start-Sleep -Milliseconds 250
        }
    }
}

function Restore-Previous {
    foreach ($name in $ours) {
        $saved = Join-Path $backup $name
        $target = Join-Path $InstallDir $name
        if (Test-Path -LiteralPath $saved) {
            Copy-Item -LiteralPath $saved -Destination $target -Force
        } elseif ($firstInstall) {
            Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue
        }
    }
    $savedConfig = Join-Path $backup 'agent.toml'
    if ($hadConfig -and (Test-Path -LiteralPath $savedConfig)) {
        Copy-Item -LiteralPath $savedConfig -Destination $config -Force
    } elseif (-not $hadConfig) {
        Remove-Item -LiteralPath $config -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue
    if ((Test-Path -LiteralPath $InstallDir) -and -not (Get-ChildItem -LiteralPath $InstallDir -Force)) {
        Remove-Item -LiteralPath $InstallDir -Force
    }
    if (-not $SkipTask -and $taskExisted -and -not $firstInstall) {
        Enable-Task
        Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    }
}

# --- 2. Stop any running copy, then keep one previous generation ---------------------
Stop-Agent

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $backup | Out-Null
foreach ($name in ($ours + 'agent.toml')) {
    $existing = Join-Path $InstallDir $name
    if (Test-Path -LiteralPath $existing) { Copy-Item -LiteralPath $existing -Destination $backup }
}

# --- 3. Put the new files down -------------------------------------------------------
# A fresh program is a fresh start: leftovers of an earlier self-update (a trial in
# progress, a rolled-back version, the previous program) must not act on it.
foreach ($leftover in @('print-agent.exe.old', 'print-agent.exe.new', 'print-agent.exe.bad', 'print-agent.trial', 'print-agent.bad')) {
    Remove-Item -LiteralPath (Join-Path $InstallDir $leftover) -Force -ErrorAction SilentlyContinue
}
Copy-Item -LiteralPath $source -Destination $installedExe -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'run-agent.ps1') -Destination $runner -Force
$example = Join-Path $PSScriptRoot 'agent.example.toml'
if (Test-Path -LiteralPath $example) {
    Copy-Item -LiteralPath $example -Destination (Join-Path $InstallDir 'agent.example.toml') -Force
}

# url and token are replaced; every other line the admin may have added is kept.
$kept = @()
if (Test-Path -LiteralPath $config) {
    $kept = @(Get-Content -LiteralPath $config -Encoding UTF8 |
        Where-Object { $_ -notmatch '^\s*(url|token)\s*=' })
}
$lines = [string[]](@("url = `"$Url`"", "token = `"$Token`"") + $kept)
[System.IO.File]::WriteAllLines($config, $lines, (New-Object System.Text.UTF8Encoding($false)))
# The token is a credential: this user only.
& icacls.exe $config /inheritance:r /grant:r "$($env:USERNAME):(M)" | Out-Null

# --- 4. Prove it can pair, before anything starts ------------------------------------
Write-Host 'Checking the pairing with the server...'
# Windows PowerShell 5.1 turns a native program's stderr into a terminating error under
# 'Stop'; the check writes its failure reason to stderr, and that is what we want shown.
$previousPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& $installedExe --config $config --check
$checkCode = $LASTEXITCODE
$ErrorActionPreference = $previousPreference
if ($checkCode -ne 0) {
    Restore-Previous
    switch ($checkCode) {
        3 { Fail 'the server refused the token. In the dashboard go to Printers in the store dashboard, choose "New credential" for this PC, and run the new command. Nothing was changed.' }
        5 { Fail 'this PC could not reach the server. Check the internet connection and the address, then run the command again. Nothing was changed.' }
        default { Fail "the new program failed its self-check (exit $checkCode). Nothing was changed." }
    }
}

Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue
# A fresh credential deserves a fresh try: clear the supervisor's "stopped for good" marker.
Remove-Item -LiteralPath $stoppedFlag -Force -ErrorAction SilentlyContinue

if ($SkipTask) {
    Write-Host 'Installed (task registration skipped).'
    exit 0
}

# --- 5. Start on logon, and start now ------------------------------------------------
$user = "$($env:USERDOMAIN)\$($env:USERNAME)"
$arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -Exe "{1}" -Config "{2}" -LogPath "{3}"' -f $runner, $installedExe, $config, $log
$action    = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments
$trigger   = New-ScheduledTaskTrigger -AtLogOn -User $user
# Task Scheduler's restart-on-failure does not fire when the supervisor is killed from
# outside (a crash of powershell.exe, an admin ending the task tree), so the task is also
# started every five minutes. MultipleInstances IgnoreNew makes that a no-op while the
# supervisor is alive; if it is gone, the next tick brings it back. A separate trigger,
# not a repetition on the logon one: that would only start repeating at the next logon.
$repeat    = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings  = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($trigger, $repeat) `
    -Settings $settings -Principal $principal -Force | Out-Null

$before = 0
if (Test-Path -LiteralPath $log) { $before = (Get-Item -LiteralPath $log).Length }
Start-ScheduledTask -TaskName $TaskName

function Read-LogSince([long]$Offset) {
    if (-not (Test-Path -LiteralPath $log)) { return '' }
    $stream = [System.IO.File]::Open($log, 'Open', 'Read', 'ReadWrite')
    try {
        if ($stream.Length -lt $Offset) { $Offset = 0 }
        $null = $stream.Seek($Offset, 'Begin')
        return (New-Object System.IO.StreamReader($stream)).ReadToEnd()
    } finally { $stream.Dispose() }
}

$live = $false
$deadline = (Get-Date).AddSeconds($LiveSeconds)
while ((Get-Date) -lt $deadline) {
    $text = Read-LogSince $before
    if ($text -match 'paired as agent') { $live = $true; break }
    if ($text -match 'not restarting') { break }
    Start-Sleep -Seconds 1
}

$winlogon = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' -ErrorAction SilentlyContinue
if (-not $winlogon -or $winlogon.AutoAdminLogon -ne '1') {
    Write-Warning 'This PC does not sign in automatically. After a power cut the agent starts only once someone signs in. Turn on automatic sign-in (Windows key, type "netplwiz") if it must print unattended.'
}

if ($live) {
    Write-Host 'Printing is live. The dashboard should now show this PC as connected.' -ForegroundColor Green
    Write-Host "Log: $log"
} else {
    Write-Warning "Installed and started, but the server has not confirmed the connection yet. Look at: $log"
}
