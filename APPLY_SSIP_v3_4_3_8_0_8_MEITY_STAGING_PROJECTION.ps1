param(
    [string]$Confirmation = "",
    [string]$Actor = "Admin"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = "D:\WebSite\DASHBOARD\Code\SSIP_GitHub"
$DatabasePath = Join-Path `
    $ProjectRoot `
    "database\ssip_staging_v1.db"

Set-Location $ProjectRoot

$env:PYTHONUTF8 = "1"

$previewJson = python `
    ".\scripts\meity_classification_projection_v3_4_3_8_0_8.py" `
    --project-root "." `
    --json

if ($LASTEXITCODE -ne 0) {
    throw "Could not regenerate the signed staging projection plan"
}

$preview = $previewJson | ConvertFrom-Json

Write-Host ""
Write-Host "SSIP v3.4.3.8.0.8 reviewed staging projection plan"
Write-Host "----------------------------------------------------"
Write-Host "Overrides applied:         $($preview.override_count)"
Write-Host "Type corrections:          $($preview.type_correction_count)"
Write-Host "Projection eligible:       $($preview.projection_eligible_count)"
Write-Host "Projection blocked:        $($preview.projection_blocked_count)"
Write-Host "Public visibility changes: No"
Write-Host "Publication action:        No"
Write-Host "Projection signature:      $($preview.projection_signature)"

if ($Confirmation -ne "PROJECT TO STAGING") {
    Write-Host ""
    Write-Host "No database change was made."
    Write-Host ""
    Write-Host "Run this exact command after reviewing the dashboard preview:"
    Write-Host (
        'powershell.exe -NoProfile -ExecutionPolicy Bypass -File ' +
        '".\APPLY_SSIP_v3_4_3_8_0_8_MEITY_STAGING_PROJECTION.ps1" ' +
        '-Confirmation "PROJECT TO STAGING"'
    )
    exit 0
}

$databaseHashBefore = (
    Get-FileHash $DatabasePath -Algorithm SHA256
).Hash

$resultJson = python `
    ".\scripts\meity_classification_projection_v3_4_3_8_0_8.py" `
    --project-root "." `
    --apply `
    --expected-signature $preview.projection_signature `
    --confirmation $Confirmation `
    --actor $Actor `
    --json

if ($LASTEXITCODE -ne 0) {
    throw "Governed MeitY staging projection failed"
}

$result = $resultJson | ConvertFrom-Json

Write-Host ""
Write-Host "SSIP v3.4.3.8.0.8 staging projection completed."
Write-Host "Eligible rows:               $($result.eligible_projection_rows)"
Write-Host "Projection rows written:     $($result.written_projection_rows)"
Write-Host "Projection rows superseded:  $($result.superseded_projection_rows)"
Write-Host "Database backup:             $($result.backup_path)"
Write-Host "Core table counts preserved: $($result.core_table_counts_preserved)"
Write-Host "scheme_staging modified:     $($result.scheme_staging_modified)"
Write-Host "admin_review_queue modified: $($result.admin_review_queue_modified)"
Write-Host "public_schemes modified:     $($result.public_schemes_modified)"
Write-Host "Public visibility changed:   $($result.public_visibility_changed)"
Write-Host "Publication action:          $($result.publication_action)"
