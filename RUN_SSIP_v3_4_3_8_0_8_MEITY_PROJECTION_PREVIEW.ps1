Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = "D:\WebSite\DASHBOARD\Code\SSIP_GitHub"
$DatabasePath = Join-Path `
    $ProjectRoot `
    "database\ssip_staging_v1.db"

Set-Location $ProjectRoot

$databaseHashBefore = (
    Get-FileHash $DatabasePath -Algorithm SHA256
).Hash

$env:PYTHONUTF8 = "1"

$resultJson = python `
    ".\scripts\meity_classification_projection_v3_4_3_8_0_8.py" `
    --project-root "." `
    --json

if ($LASTEXITCODE -ne 0) {
    throw "MeitY dashboard projection preview failed"
}

$result = $resultJson | ConvertFrom-Json

$databaseHashAfter = (
    Get-FileHash $DatabasePath -Algorithm SHA256
).Hash

if ($databaseHashBefore -ne $databaseHashAfter) {
    throw "Preview generation modified the database"
}

Write-Host ""
Write-Host "SSIP v3.4.3.8.0.8 preview completed."
Write-Host "Records:                    $($result.record_count)"
Write-Host "Overrides applied:          $($result.override_count)"
Write-Host "Type corrections:           $($result.type_correction_count)"
Write-Host "Programmes:                 $($result.programme_count)"
Write-Host "Calls and challenges:       $($result.call_challenge_count)"
Write-Host "Historical references:      $($result.historical_count)"
Write-Host "Excluded/supporting:        $($result.excluded_supporting_count)"
Write-Host "Projection eligible:        $($result.projection_eligible_count)"
Write-Host "Projection blocked:         $($result.projection_blocked_count)"
Write-Host "Projection signature:       $($result.projection_signature)"
Write-Host "Database modified:          No"
Write-Host "Publication action:         No"
