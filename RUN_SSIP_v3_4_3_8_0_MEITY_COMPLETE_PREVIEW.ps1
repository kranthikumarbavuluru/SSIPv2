param(
    [ValidateSet(
        "live-preview",
        "repository-evidence-only"
    )]
    [string]$Mode = "live-preview"
)

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
    ".\scripts\meity_complete_intelligence_v3_4_3_8_0.py" `
    --project-root "." `
    --mode $Mode `
    --json

if ($LASTEXITCODE -ne 0) {
    throw "MeitY complete intelligence preview failed"
}

$result = $resultJson | ConvertFrom-Json

if ($result.database_write_performed) {
    throw "The preview reported a database write"
}
if ($result.publication_performed) {
    throw "The preview reported a publication action"
}

$databaseHashAfter = (
    Get-FileHash $DatabasePath -Algorithm SHA256
).Hash

if ($databaseHashBefore -ne $databaseHashAfter) {
    throw "The preview modified the operational database"
}

Write-Host ""
Write-Host "SSIP v3.4.3.8.0 MeitY complete preview completed."
Write-Host "Mode:                           $Mode"
Write-Host "URLs discovered:                $($result.discovered_url_count)"
Write-Host "Fetch attempts:                 $($result.fetch_attempt_count)"
Write-Host "Fetch successes:                $($result.fetch_success_count)"
Write-Host "Browser available:              $($result.browser_available)"
Write-Host "Browser-render successes:       $($result.browser_success_count)"
Write-Host "Evidence records:               $($result.evidence_count)"
Write-Host "Programme candidates:           $($result.programme_candidate_count)"
Write-Host "Calls/challenges candidates:    $($result.current_call_challenge_candidate_count)"
Write-Host "Historical/results candidates:  $($result.historical_call_result_count)"
Write-Host "Relationship review:            $($result.relationship_review_count)"
Write-Host "Excluded evidence:              $($result.exclusion_count)"
Write-Host "Admin review records:           $($result.admin_review_count)"
Write-Host "Verified open records:          $($result.verified_open_count)"
Write-Host "Apply actions allowed:          $($result.apply_action_allowed_count)"
Write-Host "Manifest signature:             $($result.signature)"
Write-Host "Database modified:              No"
Write-Host "Publication action:             No"
Write-Host ""
Write-Host "Preview output:"
Write-Host (
    "data\departments\meity\v3_4_3_8_0"
)
