$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$dbPath = Join-Path $PSScriptRoot "data\departments\dst\v3_4_0_4\ssip_public_preview_v3_4_0_4.db"
if (-not (Test-Path $dbPath)) {
  throw "Dashboard database is missing. Run .\BUILD_v3_4_0_4.ps1 first."
}

Write-Host "Opening SSIP public dashboard at http://localhost:8502" -ForegroundColor Green
python -m streamlit run `
  .\apps\ssip_public_dashboard_v3_4_0_4.py `
  --server.port 8502 `
  --server.address localhost `
  --server.headless false `
  --browser.gatherUsageStats false
