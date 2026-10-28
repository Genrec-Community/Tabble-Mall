#requires -Version 5.1
<#
.SYNOPSIS
    Builds print-agent.exe and the Windows release folder and zip.

.DESCRIPTION
    Run on Windows: PyInstaller cannot cross-compile. Makes a clean virtualenv, runs
    the test suite, builds, smoke-runs the binary, and packages
    dist\mallt-print-agent-windows-x64.zip.
#>
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Invoke-Checked([string]$What, [scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit $LASTEXITCODE)" }
}

$python = (Get-Command python -ErrorAction Stop).Source
& $python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 or newer is required to build.' }

$venv = Join-Path $PSScriptRoot '.build-venv-win'
if (-not (Test-Path -LiteralPath $venv)) {
    Invoke-Checked 'creating the virtualenv' { & $python -m venv $venv }
}
$py = Join-Path $venv 'Scripts\python.exe'

Invoke-Checked 'installing build dependencies' {
    & $py -m pip install --quiet websockets pytest pytest-asyncio -r requirements-build.txt
}
Invoke-Checked 'the test suite' { & $py -m pytest -q }

$stage = Join-Path $PSScriptRoot 'dist\win'
Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
Invoke-Checked 'PyInstaller' {
    & $py -m PyInstaller --noconfirm --clean --onefile --name print-agent `
        --collect-submodules websockets `
        --distpath (Join-Path $stage 'pyi') `
        --workpath (Join-Path $PSScriptRoot 'build\win\work') `
        --specpath (Join-Path $PSScriptRoot 'build\win') `
        entry.py
}

$exe = Join-Path $stage 'pyi\print-agent.exe'
Invoke-Checked 'the --help smoke run' { & $exe --help | Out-Null }

# A missing config must exit 2 with a sentence: that is what a half-installed PC does.
$env:MALLT_AGENT_URL = ''
$env:MALLT_AGENT_TOKEN = ''
# Windows PowerShell 5.1 turns a native program's stderr into a terminating error under
# 'Stop', and this program is *supposed* to write to stderr here.
$previousPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& $exe --config (Join-Path $env:TEMP 'mallt-no-such-agent.toml') 2>$null
$missingConfigCode = $LASTEXITCODE
$ErrorActionPreference = $previousPreference
if ($missingConfigCode -ne 2) { throw "smoke run: expected exit 2 for a missing config, got $missingConfigCode" }

$folder = Join-Path $stage 'mallt-print-agent'
New-Item -ItemType Directory -Path $folder | Out-Null
Copy-Item -LiteralPath $exe -Destination $folder
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'agent.example.toml') -Destination $folder
Copy-Item -Path (Join-Path $PSScriptRoot 'packaging\windows\*') -Destination $folder

$zip = Join-Path $PSScriptRoot 'dist\mallt-print-agent-windows-x64.zip'
Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
Compress-Archive -LiteralPath $folder -DestinationPath $zip

Write-Host ''
Write-Host "Built $zip ($([math]::Round((Get-Item $zip).Length / 1MB, 1)) MB)" -ForegroundColor Green
