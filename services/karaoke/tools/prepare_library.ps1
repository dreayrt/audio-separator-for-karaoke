[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Arguments
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$venvPython = Join-Path $repoRoot '.venv-karaoke\Scripts\python.exe'
$previousDirectory = Get-Location
$exitCode = 1

try {
    Set-Location $repoRoot
    $env:PYTHONUTF8 = '1'
    if (Test-Path -LiteralPath $venvPython) {
        & $venvPython -u -m services.karaoke.tools.cloud_library @Arguments
    } else {
        & python -X utf8 -u -m services.karaoke.tools.cloud_library @Arguments
    }
    $exitCode = $LASTEXITCODE
} finally {
    Set-Location $previousDirectory
}
exit $exitCode
