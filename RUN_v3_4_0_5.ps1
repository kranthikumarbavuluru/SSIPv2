$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=== SSIP v3.4.0.5: Startup-Focused DST Recovery ===" -ForegroundColor Cyan
Write-Host "This run will replace broad DST department records with verified startup-access records." -ForegroundColor Yellow

python -m pip install -r .\requirements-v3_4_0_5.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }

python -m py_compile .\scripts\dst_startup_focus_pipeline_v3_4_0_5.py
if ($LASTEXITCODE -ne 0) { throw "Python compile failed." }

python .\scripts\dst_startup_focus_pipeline_v3_4_0_5.py --self-test
if ($LASTEXITCODE -ne 0) { throw "Internal self-test failed." }

python -m pytest .\tests\test_dst_startup_focus_pipeline_v3_4_0_5.py -q
if ($LASTEXITCODE -ne 0) { throw "Automated tests failed." }

Write-Host "`n=== Step 1: Quarantine broad DST records and publish verified startup schemes ===" -ForegroundColor Green
python .\scripts\dst_startup_focus_pipeline_v3_4_0_5.py `
  --project-root "$PSScriptRoot" `
  --config .\config\dst_startup_focus_rules_v3_4_0_5.json `
  --publish-curated `
  --patch-dashboard
if ($LASTEXITCODE -ne 0) { throw "Startup-focused publication failed." }

Write-Host "`n=== Step 2: Official deep search for startup schemes, calls, hubs and documents ===" -ForegroundColor Green
python .\scripts\dst_startup_focus_pipeline_v3_4_0_5.py `
  --project-root "$PSScriptRoot" `
  --config .\config\dst_startup_focus_rules_v3_4_0_5.json `
  --deep-search
if ($LASTEXITCODE -ne 0) {
  Write-Warning "Deep search had network errors. The verified startup catalogue was still published. Re-run RUN_DEEP_SEARCH_v3_4_0_5.ps1 later."
}

Write-Host "`n=== Verification ===" -ForegroundColor Green
& .\VERIFY_v3_4_0_5.ps1

Write-Host "`n=== Restarting the actual SSIP dashboard on port 8502 ===" -ForegroundColor Cyan
try {
  $connections = Get-NetTCPConnection -LocalPort 8502 -State Listen -ErrorAction SilentlyContinue
  foreach ($connection in $connections) {
    if ($connection.OwningProcess) {
      Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue
    }
  }
} catch {
  Write-Warning "Could not automatically stop the old Streamlit process. Close it manually if port 8502 is busy."
}

python -m streamlit cache clear | Out-Null
Start-Process powershell -ArgumentList @(
  "-NoExit",
  "-Command",
  "Set-Location '$PSScriptRoot'; python -m streamlit run .\apps\public_dashboard_app_v2_9.py --server.address 127.0.0.1 --server.port 8502"
)
Start-Sleep -Seconds 4
Start-Process "http://localhost:8502"

Write-Host "`nDashboard started: http://localhost:8502" -ForegroundColor Green
Write-Host "Press Ctrl+F5 in the browser after it opens." -ForegroundColor Yellow
