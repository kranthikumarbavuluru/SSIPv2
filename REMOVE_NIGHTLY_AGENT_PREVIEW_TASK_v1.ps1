$TaskName = "SSIP Nightly Governed Agent Preview v1"

$PreviousErrorActionPreference = $ErrorActionPreference
$ExitCode = 0
try {
    $ErrorActionPreference = "Continue"
    & schtasks.exe /Delete /F /TN $TaskName
    $ExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
}
if ($ExitCode -ne 0) {
    throw "Scheduled task removal failed with exit code $ExitCode."
}
Write-Output "Removed '$TaskName'."
