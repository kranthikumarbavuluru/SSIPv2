param(
    [Parameter(Mandatory = $true)]
    [string]$WorksheetPath,

    [switch]$AllowValidSubset
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = "D:\WebSite\DASHBOARD\Code\SSIP_GitHub"
$DatabasePath = Join-Path `
    $ProjectRoot `
    "database\ssip_staging_v1.db"

if (-not (Test-Path $WorksheetPath)) {
    throw "Decision worksheet not found: $WorksheetPath"
}

$resolvedWorksheet = (
    Resolve-Path -LiteralPath $WorksheetPath
).Path

Set-Location $ProjectRoot

$databaseHashBefore = (
    Get-FileHash $DatabasePath -Algorithm SHA256
).Hash

$arguments = @(
    ".\scripts\meity_guided_decision_import_v3_4_3_8_0_6.py",
    "--project-root",
    ".",
    "--worksheet",
    $resolvedWorksheet,
    "--json"
)

if ($AllowValidSubset) {
    $arguments += "--allow-valid-subset"
}

$env:PYTHONUTF8 = "1"

$resultJson = python @arguments
$exitCode = $LASTEXITCODE

if ($exitCode -notin @(0, 2)) {
    throw "MeitY guided-decision validation failed"
}

$result = $resultJson | ConvertFrom-Json

$databaseHashAfter = (
    Get-FileHash $DatabasePath -Algorithm SHA256
).Hash

if ($databaseHashBefore -ne $databaseHashAfter) {
    throw "Decision validation modified the operational database"
}

Write-Host ""
Write-Host "SSIP v3.4.3.8.0.6 decision validation completed."
Write-Host "Worksheet:                 $resolvedWorksheet"
Write-Host "Worksheet rows:            $($result.worksheet_row_count)"
Write-Host "Accepted decisions:        $($result.accepted_decision_count)"
Write-Host "Rejected rows:             $($result.rejected_decision_count)"
Write-Host "Plan status:               $($result.plan_status)"
Write-Host "Strict mode:               $($result.strict_mode)"
Write-Host "Plan signature:            $($result.decision_plan_signature)"
Write-Host "Database modified:         No"
Write-Host "Publication action:        No"
Write-Host "Admin bridge applied:      No"

if ($result.plan_status -eq "BLOCKED") {
    Write-Host ""
    Write-Host "The plan is blocked."
    Write-Host (
        "Open the rejected-rows CSV, correct those records in the guided " +
        "review page, download a new worksheet and validate it again."
    )
    exit 2
}

Write-Host ""
Write-Host "The signed Admin-bridge preview is ready for review."
