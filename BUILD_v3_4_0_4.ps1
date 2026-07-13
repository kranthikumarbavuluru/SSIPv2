$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=== SSIP v3.4.0.4: Install requirements ===" -ForegroundColor Cyan
python -m pip install -r .\requirements-v3_4_0_4.txt

Write-Host "=== Compile ===" -ForegroundColor Cyan
python -m py_compile `
  .\scripts\dst_canonical_publication_builder_v3_4_0_4.py `
  .\apps\ssip_public_dashboard_v3_4_0_4.py

Write-Host "=== Self-test ===" -ForegroundColor Cyan
python .\scripts\dst_canonical_publication_builder_v3_4_0_4.py --self-test
if ($LASTEXITCODE -ne 0) { throw "v3.4.0.4 self-test failed." }

Write-Host "=== Automated tests ===" -ForegroundColor Cyan
python -m pytest .\tests\test_dst_canonical_publication_builder_v3_4_0_4.py -q
if ($LASTEXITCODE -ne 0) { throw "v3.4.0.4 automated tests failed." }

Write-Host "=== Build canonical registry and public catalogue ===" -ForegroundColor Cyan
python .\scripts\dst_canonical_publication_builder_v3_4_0_4.py `
  --project-root $PSScriptRoot `
  --config .\config\dst_canonical_publication_rules_v3_4_0_4.json `
  --overrides .\config\dst_identity_curation_overrides_v3_4_0_4.csv `
  --strict
if ($LASTEXITCODE -ne 0) { throw "v3.4.0.4 production validation failed." }

$validationPath = Join-Path $PSScriptRoot "data\departments\dst\v3_4_0_4\dst_canonical_validation_v3_4_0_4.json"
$validation = Get-Content $validationPath -Raw -Encoding UTF8 | ConvertFrom-Json

if (-not $validation.canonical_validation_passed) {
  throw "Canonical validation did not pass. Review $validationPath"
}
if (-not $validation.ready_for_dashboard_preview) {
  throw "Dashboard preview gate did not pass. Review $validationPath"
}

Write-Host "" 
Write-Host "BUILD PASSED" -ForegroundColor Green
Write-Host ("Canonical schemes   : {0}" -f $validation.counts.canonical_schemes)
Write-Host ("Canonical programmes: {0}" -f $validation.counts.canonical_programmes)
Write-Host ("Public records      : {0}" -f $validation.counts.publication_records)
Write-Host ("Manual review       : {0}" -f $validation.counts.manual_entity_reviews)
Write-Host "Database: .\data\departments\dst\v3_4_0_4\ssip_public_preview_v3_4_0_4.db"
