param(
    [string]$BackupName = ""
)

$PreviousErrorActionPreference = $ErrorActionPreference
$ExitCode = 0
try {
    Set-Location -LiteralPath $PSScriptRoot
    $ErrorActionPreference = "Continue"
    if ([string]::IsNullOrWhiteSpace($BackupName)) {
        & python "scripts\rollback_publication_v1.py" --project-root $PSScriptRoot
    } else {
        & python "scripts\rollback_publication_v1.py" --project-root $PSScriptRoot --backup-name $BackupName
    }
    $ExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
}
if ($ExitCode -ne 0) {
    throw "Publication rollback failed with exit code $ExitCode."
}
