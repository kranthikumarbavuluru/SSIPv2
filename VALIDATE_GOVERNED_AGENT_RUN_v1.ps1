param(
    [Parameter(Mandatory = $true)][string]$RunId,
    [string]$DeletionApproval = ""
)

$PreviousErrorActionPreference = $ErrorActionPreference
$ExitCode = 0
try {
    Set-Location -LiteralPath $PSScriptRoot
    $ErrorActionPreference = "Continue"
    if ([string]::IsNullOrWhiteSpace($DeletionApproval)) {
        & python "scripts\validate_governed_agent_run_v1.py" --project-root $PSScriptRoot --run-id $RunId
    } else {
        & python "scripts\validate_governed_agent_run_v1.py" --project-root $PSScriptRoot --run-id $RunId --deletion-approval $DeletionApproval
    }
    $ExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
}
if ($ExitCode -ne 0) {
    throw "Governed validation failed with exit code $ExitCode."
}
