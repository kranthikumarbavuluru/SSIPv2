$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=== SSIP v3.4.0.4a: Existing dashboard integration ===" -ForegroundColor Cyan

$required = @(
  ".\data\catalogue_preview\v3_3_2\catalogue_preview_v3_3_2.csv",
  ".\data\departments\dst\v3_4_0_4\dst_publication_catalogue_v3_4_0_4.csv",
  ".\apps\public_dashboard_app_v2_9.py"
)
foreach ($path in $required) {
  if (-not (Test-Path $path)) { throw "Required file missing: $path" }
}

python -m py_compile .\scripts\integrate_dst_v3_4_0_4_into_existing_dashboard.py
python .\scripts\integrate_dst_v3_4_0_4_into_existing_dashboard.py --self-test
if ($LASTEXITCODE -ne 0) { throw "Integration self-test failed." }

python .\scripts\integrate_dst_v3_4_0_4_into_existing_dashboard.py `
  --project-root $PSScriptRoot
if ($LASTEXITCODE -ne 0) { throw "DST dashboard integration failed." }

Write-Host "" 
Write-Host "=== Dashboard data verification ===" -ForegroundColor Cyan
python -c "import csv,pathlib; p=pathlib.Path(r'data/catalogue_preview/v3_3_2/catalogue_preview_v3_3_2.csv'); rows=list(csv.DictReader(open(p,encoding='utf-8-sig'))); dst=[r for r in rows if (r.get('source') or '').strip().upper()=='DST']; print('Active preview rows:',len(rows)); print('DST rows:',len(dst)); print('Unique DST IDs:',len(set(r.get('master_id','') for r in dst))); print('First DST records:'); [print(' -',r.get('scheme_name')) for r in dst[:5]]; raise SystemExit(0 if len(dst)==23 and len(set(r.get('master_id','') for r in dst))==23 else 1)"
if ($LASTEXITCODE -ne 0) { throw "The active preview does not contain exactly 23 DST records." }

Write-Host "" 
Write-Host "=== Stopping old Streamlit listener on port 8502 ===" -ForegroundColor Cyan
$connections = Get-NetTCPConnection -LocalPort 8502 -State Listen -ErrorAction SilentlyContinue
$pids = @($connections | Select-Object -ExpandProperty OwningProcess -Unique)
foreach ($processId in $pids) {
  if ($processId -and $processId -ne $PID) {
    Write-Host "Stopping process $processId"
    Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
  }
}
Start-Sleep -Seconds 2

python -m streamlit cache clear

Write-Host "" 
Write-Host "Opening UPDATED SSIP dashboard at http://localhost:8502" -ForegroundColor Green
Write-Host "Expected: footer v3.4.0.4 and search 'dst' returns 23 records." -ForegroundColor Green
python -m streamlit run `
  .\apps\public_dashboard_app_v2_9.py `
  --server.address localhost `
  --server.port 8502 `
  --server.headless false `
  --browser.gatherUsageStats false
