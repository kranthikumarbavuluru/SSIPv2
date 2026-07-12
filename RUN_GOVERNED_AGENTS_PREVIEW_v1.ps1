param(
    [string]$RunId = ""
)

$PreviousErrorActionPreference = $ErrorActionPreference
$ExitCode = 0
try {
    Set-Location -LiteralPath $PSScriptRoot
    $ErrorActionPreference = "Continue"
    if ([string]::IsNullOrWhiteSpace($RunId)) {
        & python "scripts\run_governed_agents_preview_v1.py" --project-root $PSScriptRoot
    } else {
        & python "scripts\run_governed_agents_preview_v1.py" --project-root $PSScriptRoot --run-id $RunId
    }
    $ExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
}
if ($ExitCode -ne 0) {
    throw "Governed preview failed with exit code $ExitCode."
}
