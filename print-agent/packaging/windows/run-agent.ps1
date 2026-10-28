#requires -Version 5.1
<#
.SYNOPSIS
    Keeps print-agent.exe running: restarts it with backoff, and stops for good on the
    exit codes that restarting cannot fix.

.DESCRIPTION
    Task Scheduler starts this at logon. The agent already reconnects by itself after a
    network drop; this exists for the other failures -- a crash, or Windows killing it
    -- and to write down why it stopped when it will not be restarted.

    Exit codes the agent uses on purpose:
      0  stopped deliberately
      2  the configuration is unusable
      3  the server refused the credential
      4  another print-agent is already running
     10  it replaced itself with a newer release: start it again straight away
     11  an updated agent could not reach the server: restart it (counted as a failed trial)
    Restarting any of those is an endless loop with nobody ever told, so the supervisor
    stops, logs the reason, and exits with the same code. Everything else restarts.

    ROLLBACK. After the agent updates itself it leaves print-agent.trial beside the program
    and deletes it once it has been connected for a minute. Every launch while that file
    exists is counted here; after $MaxTrialStarts launches that never became healthy the
    previous program (print-agent.exe.old) is put back, the bad version is recorded in
    print-agent.bad so the agent will not fetch it again for a day, and the old version
    starts. It is done here, not in the agent, because a build that cannot run cannot be
    asked to undo itself.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Exe,
    [Parameter(Mandatory)][string]$Config,
    [Parameter(Mandatory)][string]$LogPath,
    [int]$MinBackoff = 5,
    [int]$MaxBackoff = 60,
    [int]$StableSeconds = 60,
    [int]$MaxTrialStarts = 3,
    [int]$MaxLogBytes = 1048576,
    [int]$KeepLogBytes = 262144
)

$ErrorActionPreference = 'Stop'

$StopCodes = @{
    0 = 'it was stopped deliberately'
    2 = 'its configuration is unusable - fix agent.toml and run install.ps1 again'
    3 = 'the server refused its credential - re-issue it under Printers in the store dashboard and run the new install command'
    4 = 'another print-agent is already running'
}

function Write-Log([string]$Message) {
    $line = '{0} supervisor: {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    # A log that cannot be written must never be the reason slips stop printing.
    try { Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8 } catch { }
}

function Limit-Log {
    try {
        $info = Get-Item -LiteralPath $LogPath -ErrorAction Stop
        if ($info.Length -le $MaxLogBytes) { return }
        $bytes = [System.IO.File]::ReadAllBytes($LogPath)
        $keep = [Math]::Min($KeepLogBytes, $bytes.Length)
        $tail = New-Object byte[] $keep
        [Array]::Copy($bytes, $bytes.Length - $keep, $tail, 0, $keep)
        [System.IO.File]::WriteAllBytes($LogPath, $tail)
    } catch { }
}

$null = New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath)

# UTF-8 without a byte-order mark: Set-Content -Encoding UTF8 adds one in Windows
# PowerShell 5.1, and the agent should not have to cope with a marker it can avoid.
function Write-Plain([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text + "`n", (New-Object System.Text.UTF8Encoding $false))
}

function Read-Pairs([string]$Path) {
    $pairs = @{}
    if (Test-Path -LiteralPath $Path) {
        foreach ($line in (Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue)) {
            if ($line -match '^([A-Za-z_]+)=(.*)$') { $pairs[$Matches[1]] = $Matches[2].Trim() }
        }
    }
    return $pairs
}

# Counts this launch against a trial in progress, and rolls back when it is the one too
# many. Never throws: a supervisor that dies here would stop printing altogether.
function Step-Trial {
    $trialFile = Join-Path (Split-Path -Parent $Exe) 'print-agent.trial'
    if (-not (Test-Path -LiteralPath $trialFile)) { return }
    try {
        $pairs = Read-Pairs $trialFile
        $starts = 0
        [void][int]::TryParse([string]$pairs['starts'], [ref]$starts)
        $starts++
        if ($starts -le $MaxTrialStarts) {
            $pairs['starts'] = [string]$starts
            $text = ($pairs.GetEnumerator() | ForEach-Object { '{0}={1}' -f $_.Key, $_.Value }) -join "`n"
            Write-Plain $trialFile $text
            return
        }
        $old = $Exe + '.old'
        $bad = $Exe + '.bad'
        if (Test-Path -LiteralPath $old) {
            Move-Item -LiteralPath $Exe -Destination $bad -Force
            Move-Item -LiteralPath $old -Destination $Exe -Force
            $until = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() + 86400
            $record = "version=$($pairs['to'])`nuntil=$until"
            Write-Plain (Join-Path (Split-Path -Parent $Exe) 'print-agent.bad') $record
            Write-Log ('version {0} did not become healthy in {1} starts; restored {2}' -f $pairs['to'], $MaxTrialStarts, $pairs['from'])
        } else {
            Write-Log 'update did not become healthy and there is no previous program to restore'
        }
        Remove-Item -LiteralPath $trialFile -Force -ErrorAction SilentlyContinue
    } catch {
        Write-Log ('could not check the update trial: {0}' -f $_.Exception.Message)
    }
}

# The scheduled task is relaunched every few minutes, so that a supervisor that was killed
# from outside comes back. A stop that restarting cannot fix (2 bad config, 3 credential
# refused) would then be retried on every tick forever, so it leaves a marker and a later
# launch exits with the same code without touching the network. Editing agent.toml, or
# running install.ps1 (which removes the marker), lets the next launch try again.
$StoppedFlag = Join-Path (Split-Path -Parent $LogPath) 'stopped.flag'
if (Test-Path -LiteralPath $StoppedFlag) {
    $flag = Get-Item -LiteralPath $StoppedFlag
    $edited = (Test-Path -LiteralPath $Config) -and ((Get-Item -LiteralPath $Config).LastWriteTime -gt $flag.LastWriteTime)
    if (-not $edited) {
        $earlier = 0
        [void][int]::TryParse(((Get-Content -LiteralPath $StoppedFlag -TotalCount 1) -join ''), [ref]$earlier)
        if ($earlier -eq 0) { $earlier = 3 }
        exit $earlier
    }
    Remove-Item -LiteralPath $StoppedFlag -Force -ErrorAction SilentlyContinue
}

$delay = $MinBackoff
Write-Log "supervising $Exe"

while ($true) {
    Limit-Log
    Step-Trial
    $started = Get-Date

    # cmd.exe does the stderr redirect: PowerShell 5.1 wraps native stderr lines in
    # error records. The command line travels in an environment variable and cmd expands
    # it itself, because the two PowerShell editions escape embedded quotes in a native
    # argument differently and a path with a space has to survive both.
    $env:MALLT_AGENT_COMMAND = '"{0}" --config "{1}" 2>>"{2}"' -f $Exe, $Config, $LogPath
    & cmd.exe /d /c %MALLT_AGENT_COMMAND%
    $code = $LASTEXITCODE
    $ranFor = ((Get-Date) - $started).TotalSeconds

    if ($StopCodes.ContainsKey($code)) {
        Write-Log ('agent exited {0}: {1}; not restarting' -f $code, $StopCodes[$code])
        if ($code -eq 2 -or $code -eq 3) {
            try { Set-Content -LiteralPath $StoppedFlag -Value $code } catch { }
        }
        exit $code
    }

    if ($code -eq 10) {
        Write-Log 'agent updated itself; starting the new version'
        $delay = $MinBackoff
        Start-Sleep -Seconds 1
        continue
    }

    if ($ranFor -ge $StableSeconds) { $delay = $MinBackoff }
    Write-Log ('agent exited {0} after {1:N0}s; restarting in {2}s' -f $code, $ranFor, $delay)
    Start-Sleep -Seconds $delay
    $delay = [Math]::Min($MaxBackoff, $delay * 2)
}
