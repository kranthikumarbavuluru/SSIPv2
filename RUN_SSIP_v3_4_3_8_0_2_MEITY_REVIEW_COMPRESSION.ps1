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
    ".\scripts\meity_review_compression_v3_4_3_8_0_2.py" `
    --project-root "." `
    --json

if ($LASTEXITCODE -ne 0) {
    throw "MeitY family-level review compression failed"
}

$result = $resultJson | ConvertFrom-Json

if (-not $result.row_reconciliation) {
    throw "Review rows did not reconcile"
}
if (-not $result.evidence_weight_reconciliation) {
    throw "Source evidence weight did not reconcile"
}
if (
    $result.admin_decision_bundle_count -gt
    $result.max_admin_decision_bundles
) {
    throw "Admin decision bundle maximum was exceeded"
}
if ($result.apply_action_allowed_count -ne 0) {
    throw "An Apply action was exposed"
}
if ($result.publication_eligible_count -ne 0) {
    throw "A publication-eligible record was exposed"
}
if ($result.database_write_performed) {
    throw "Review compression reported a database write"
}
if ($result.publication_performed) {
    throw "Review compression reported publication"
}

$databaseHashAfter = (
    Get-FileHash $DatabasePath -Algorithm SHA256
).Hash

if ($databaseHashBefore -ne $databaseHashAfter) {
    throw "Review compression modified the operational database"
}

Write-Host ""
Write-Host "SSIP v3.4.3.8.0.2 review compression completed."
Write-Host "Source evidence:          $($result.source_evidence_weight)"
Write-Host "Auto-resolved evidence:   $($result.auto_resolved_evidence_weight)"
Write-Host "Automatic groups:         $($result.auto_resolved_group_count)"
Write-Host "Admin decision bundles:   $($result.admin_decision_bundle_count)"
Write-Host "Batch confirmations:      $($result.batch_confirmation_bundle_count)"
Write-Host "Deep review bundles:      $($result.deep_review_bundle_count)"
Write-Host "Maximum Admin workload:   $($result.max_admin_decision_bundles)"
Write-Host "Row reconciliation:       PASS"
Write-Host "Evidence reconciliation:  PASS"
Write-Host "Database modified:        No"
Write-Host "Publication action:       No"
