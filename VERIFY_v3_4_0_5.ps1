$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$catalogue = ".\data\catalogue_preview\v3_3_2\catalogue_preview_v3_3_2.csv"
$output = ".\data\departments\dst\v3_4_0_5"

if (-not (Test-Path $catalogue)) { throw "Catalogue not found: $catalogue" }
$rows = Import-Csv $catalogue
$dstRows = $rows | Where-Object {
  $_.source -eq "DST" -or
  $_.department -match "Department of Science and Technology" -or
  $_.official_page_url -match "dst.gov.in|tdb.gov.in"
}
$badRows = $dstRows | Where-Object {
  $_.scheme_name -match "Climate Change Programme|FIST|INSPIRE|University|Universities|Institutional Capacity|Mega Facilities"
}
$missingSector = $dstRows | Where-Object { [string]::IsNullOrWhiteSpace($_.sector) }
$wrongSection = $dstRows | Where-Object { $_.catalogue_section -ne "STARTUP_SCHEMES" }

$calls = @()
if (Test-Path "$output\dst_startup_calls_v3_4_0_5.csv") {
  $calls = Import-Csv "$output\dst_startup_calls_v3_4_0_5.csv"
}
$ecosystems = Import-Csv "$output\dst_startup_ecosystem_registry_v3_4_0_5.csv"

Write-Host ""
Write-Host "SSIP v3.4.0.5 VERIFICATION" -ForegroundColor Cyan
Write-Host "=========================="
[PSCustomObject]@{
  TotalCatalogueRows = $rows.Count
  PublishedDSTStartupSchemes = $dstRows.Count
  NonStartupDSTRowsRemaining = @($badRows).Count
  MissingSector = @($missingSector).Count
  WrongCatalogueSection = @($wrongSection).Count
  CallsAndOpportunities = @($calls).Count
  EcosystemRecords = @($ecosystems).Count
} | Format-List

Write-Host "Published DST startup records:" -ForegroundColor Green
$dstRows | Select-Object scheme_name, sector, scheme_type, application_status, official_page_url | Format-Table -Wrap -AutoSize

if (@($badRows).Count -gt 0) { throw "Institution/university-only DST records remain in the public Startup Explorer." }
if (@($missingSector).Count -gt 0) { throw "Published DST startup records are missing sector values." }
if (@($wrongSection).Count -gt 0) { throw "Published DST records are not in STARTUP_SCHEMES section." }
if ($dstRows.Count -ne 7) { throw "Expected 7 verified DST startup scheme/access records, found $($dstRows.Count)." }

Write-Host "VALIDATION PASSED" -ForegroundColor Green
Write-Host "Dashboard search 'dst' should show 7 focused scheme/access records, not 23 broad department programmes." -ForegroundColor Yellow
Write-Host "Use the Calls & Opportunities and Incubators & Ecosystem tabs for linked opportunities and umbrella missions." -ForegroundColor Yellow
