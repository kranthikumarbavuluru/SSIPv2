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

Write-Host "Refreshing the complete MeitY source discovery..."

$sourceJson = python `
    ".\scripts\meity_complete_intelligence_v3_4_3_8_0.py" `
    --project-root "." `
    --mode "live-preview" `
    --json

if ($LASTEXITCODE -ne 0) {
    throw "MeitY v3.4.3.8.0 source refresh failed"
}

$source = $sourceJson | ConvertFrom-Json

$htmlParseErrors = @(
    $source.errors |
    Where-Object {
        $_ -like "HTML_PARSE:*"
    }
)

if ($htmlParseErrors.Count -gt 0) {
    throw (
        "HTML parser errors remain after repair:`n" +
        ($htmlParseErrors -join "`n")
    )
}

Write-Host "Purifying refreshed candidates..."

$resultJson = python `
    ".\scripts\meity_candidate_purification_v3_4_3_8_0_1.py" `
    --project-root "." `
    --json

if ($LASTEXITCODE -ne 0) {
    throw "MeitY candidate purification failed"
}

$result = $resultJson | ConvertFrom-Json

if (-not $result.partition_complete) {
    throw "Candidate partition is incomplete"
}
if ($result.partition_total -ne $result.source_candidate_count) {
    throw "Candidate partition totals do not reconcile"
}
if ($result.unsafe_programme_identity_count -ne 0) {
    throw "Unsafe programme identities survived purification"
}
if ($result.apply_action_allowed_count -ne 0) {
    throw "Purified preview exposed an Apply action"
}
if ($result.database_write_performed) {
    throw "Purified preview reported a database write"
}
if ($result.publication_performed) {
    throw "Purified preview reported publication"
}

$databaseHashAfter = (
    Get-FileHash $DatabasePath -Algorithm SHA256
).Hash

if ($databaseHashBefore -ne $databaseHashAfter) {
    throw "Preview processing modified the operational database"
}

Write-Host ""
Write-Host "SSIP v3.4.3.8.0.1 purification completed."
Write-Host "Refreshed source candidates: $($result.source_candidate_count)"
Write-Host "Programme families:          $($result.purified_programme_family_count)"
Write-Host "Calls and challenges:        $($result.purified_call_challenge_count)"
Write-Host "Historical events:           $($result.purified_historical_event_count)"
Write-Host "Supporting documents:        $($result.supporting_document_count)"
Write-Host "Excluded/error pages:        $($result.excluded_error_page_count)"
Write-Host "Identity/role review:        $($result.identity_role_review_count)"
Write-Host "Admin review records:        $($result.admin_review_count)"
Write-Host "Unsafe programme identities: $($result.unsafe_programme_identity_count)"
Write-Host "Database modified:           No"
Write-Host "Publication action:          No"
