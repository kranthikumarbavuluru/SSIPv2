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

Write-Host "Inspecting MeitY URL provenance and final page roles..."

$resultJson = python `
    ".\scripts\meity_url_integrity_v3_4_3_8_0_4.py" `
    --project-root "." `
    --json

if ($LASTEXITCODE -ne 0) {
    throw "MeitY URL-integrity gate failed"
}

$result = $resultJson | ConvertFrom-Json

if ($result.historical_application_links_exposed -ne 0) {
    throw "Historical application links were exposed"
}
if ($result.about_page_application_links_exposed -ne 0) {
    throw "About-page links were exposed as application routes"
}
if ($result.cross_entity_link_contamination_count -ne 0) {
    throw "Cross-entity application contamination survived"
}
if (
    $result.current_status_evidence_complete_count -eq 0 -and
    $result.verified_application_routes -ne 0
) {
    throw (
        "Application routes were exposed while no child had complete " +
        "current-status evidence"
    )
}
if ($result.apply_action_allowed_count -ne 0) {
    throw "An Apply action was exposed"
}
if ($result.publication_eligible_count -ne 0) {
    throw "A publication-eligible record was exposed"
}
if ($result.database_write_performed) {
    throw "URL-integrity gate reported a database write"
}
if ($result.publication_performed) {
    throw "URL-integrity gate reported publication"
}

$databaseHashAfter = (
    Get-FileHash $DatabasePath -Algorithm SHA256
).Hash

if ($databaseHashBefore -ne $databaseHashAfter) {
    throw "URL-integrity gate modified the operational database"
}

Write-Host ""
Write-Host "SSIP v3.4.3.8.0.4 link-integrity gate completed."
Write-Host "Links inspected:                    $($result.links_inspected)"
Write-Host "Verified information links:        $($result.verified_information_links)"
Write-Host "Verified application routes:       $($result.verified_application_routes)"
Write-Host "Withheld application routes:       $($result.withheld_application_routes)"
Write-Host "Broken/unverified links:           $($result.broken_or_unverified_links)"
Write-Host "Historical application exposed:    $($result.historical_application_links_exposed)"
Write-Host "About-page application exposed:    $($result.about_page_application_links_exposed)"
Write-Host "Cross-entity contamination:        $($result.cross_entity_link_contamination_count)"
Write-Host "Global application withholding:    $($result.global_application_routes_withheld)"
Write-Host "Database modified:                 No"
Write-Host "Publication action:                No"
