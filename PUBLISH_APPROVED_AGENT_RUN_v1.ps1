param(
    [Parameter(Mandatory = $true)][string]$RunId,
    [Parameter(Mandatory = $true)][string]$ApprovalFile,
    [string]$DeletionApproval = "",
    [switch]$AllowLargeChange
)

$PreviousErrorActionPreference = $ErrorActionPreference
$ExitCode = 0
try {
    Set-Location -LiteralPath $PSScriptRoot
    $ErrorActionPreference = "Continue"
    $Arguments = @(
        "scripts\publish_approved_agent_run_v1.py",
        "--project-root", $PSScriptRoot,
        "--run-id", $RunId,
        "--approval-file", $ApprovalFile
    )
    if (-not [string]::IsNullOrWhiteSpace($DeletionApproval)) {
        $Arguments += @("--deletion-approval", $DeletionApproval)
    }
    if ($AllowLargeChange) {
        $Arguments += "--allow-large-change"
    }
    & python @Arguments
    $ExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
}
if ($ExitCode -ne 0) {
    throw "Approved publication failed with exit code $ExitCode."
}
