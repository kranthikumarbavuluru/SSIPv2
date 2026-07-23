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
    ".\scripts\meity_temporal_parent_safety_v3_4_3_8_0_3.py" `
    --project-root "." `
    --json

if ($LASTEXITCODE -ne 0) {
    throw "MeitY temporal and decision-safety gate failed"
}

$result = $resultJson | ConvertFrom-Json

if (
    $result.source_decision_bundle_count -ne
    $result.safe_decision_bundle_count
) {
    throw "Decision bundles did not reconcile"
}
if ($result.unsafe_current_status_count -ne 0) {
    throw "Unsafe current status survived"
}
if ($result.ambiguous_decision_label_count -ne 0) {
    throw "Ambiguous decision wording survived"
}
if (-not $result.deep_review_requires_child_selection) {
    throw "Deep review child selection is not mandatory"
}
if (-not $result.deep_review_requires_admin_note) {
    throw "Deep review Admin notes are not mandatory"
}
if (-not $result.session_decisions_invalidated_on_signature_change) {
    throw "Session decisions are not invalidated after evidence changes"
}
if ($result.apply_action_allowed_count -ne 0) {
    throw "An Apply action was exposed"
}
if ($result.publication_eligible_count -ne 0) {
    throw "A publication-eligible record was exposed"
}
if ($result.database_write_performed) {
    throw "Safety gate reported a database write"
}
if ($result.publication_performed) {
    throw "Safety gate reported publication"
}

$databaseHashAfter = (
    Get-FileHash $DatabasePath -Algorithm SHA256
).Hash

if ($databaseHashBefore -ne $databaseHashAfter) {
    throw "Safety gate modified the operational database"
}

Write-Host ""
Write-Host "SSIP v3.4.3.8.0.3 safety gate completed."
Write-Host "Decision bundles:            $($result.safe_decision_bundle_count)"
Write-Host "Temporal downgrades:         $($result.temporal_downgrade_count)"
Write-Host "Parent links repaired:       $($result.parent_link_repair_count)"
Write-Host "Current evidence complete:   $($result.current_status_evidence_complete_count)"
Write-Host "Historical classifications: $($result.historical_classification_count)"
Write-Host "Unsafe current status:       $($result.unsafe_current_status_count)"
Write-Host "Ambiguous decision labels:   $($result.ambiguous_decision_label_count)"
Write-Host "Child selection required:    $($result.deep_review_requires_child_selection)"
Write-Host "Admin note required:         $($result.deep_review_requires_admin_note)"
Write-Host "Database modified:           No"
Write-Host "Publication action:          No"
