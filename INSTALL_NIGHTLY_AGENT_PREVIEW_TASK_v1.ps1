$TaskName = "SSIP Nightly Governed Agent Preview v1"
$Runner = Join-Path $PSScriptRoot "RUN_GOVERNED_AGENTS_PREVIEW_v1.ps1"
$TaskCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Runner`""

$PreviousErrorActionPreference = $ErrorActionPreference
$ExitCode = 0
try {
    $ErrorActionPreference = "Continue"
    & schtasks.exe /Create /F /SC DAILY /ST 00:00 /TN $TaskName /TR $TaskCommand
    $ExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
}
if ($ExitCode -ne 0) {
    throw "Scheduled task installation failed with exit code $ExitCode."
}
Write-Output "Installed '$TaskName'. It runs preview only and never invokes publication."
