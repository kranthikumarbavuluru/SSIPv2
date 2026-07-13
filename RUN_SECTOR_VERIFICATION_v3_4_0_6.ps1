$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "SSIP v3.4.0.6 - Sector Verification Agent" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

python -m pip install -r .\requirements-v3_4_0_6.txt
python -m py_compile .\scripts\sector_verification_agent_v3_4_0_6.py
python .\scripts\sector_verification_agent_v3_4_0_6.py --self-test
python .\scripts\patch_dashboard_sector_taxonomy_v3_4_0_6.py --self-test
python -m pytest .\tests\test_sector_verification_agent_v3_4_0_6.py .\tests\test_dashboard_sector_patch_v3_4_0_6.py -q

# Run the network stage with native stderr tolerated, then enforce the actual
# Python exit code. This prevents harmless parser warnings from being promoted
# to terminating NativeCommandError records by Windows PowerShell 5.1.
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
python .\scripts\sector_verification_agent_v3_4_0_6.py `
  --project-root "$PSScriptRoot" `
  --allow-network `
  --lm-studio auto `
  --apply `
  --progress
$agentExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference
if ($agentExitCode -ne 0) {
    throw "Sector Verification Agent failed with exit code $agentExitCode."
}

python .\scripts\patch_dashboard_sector_taxonomy_v3_4_0_6.py `
  --project-root "$PSScriptRoot"
python -m py_compile .\ssip_dashboard\catalogue_populations.py .\apps\public_dashboard_app_v2_9.py

$validationPath = ".\data\sector_verification\v3_4_0_6\sector_validation_v3_4_0_6.json"
$summaryPath = ".\data\sector_verification\v3_4_0_6\sector_summary_v3_4_0_6.json"

Write-Host "`n=== SECTOR VALIDATION ===" -ForegroundColor Green
Get-Content $validationPath -Encoding UTF8
Write-Host "`n=== SECTOR SUMMARY ===" -ForegroundColor Green
Get-Content $summaryPath -Encoding UTF8

$validation = Get-Content $validationPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $validation.validation_passed) {
    throw "Sector validation failed. Dashboard was not safely updated."
}

# Update dashboard version label without altering layout.
$app = ".\apps\public_dashboard_app_v2_9.py"
if (Test-Path $app) {
    $content = Get-Content $app -Raw -Encoding UTF8
    $updated = [regex]::Replace($content, 'APP_VERSION\s*=\s*["''][^"'']+["'']', 'APP_VERSION = "3.4.0.6"', 1)
    if ($updated -ne $content) {
        Set-Content $app -Value $updated -Encoding UTF8
    }
}

Write-Host "`nRestarting Streamlit on port 8502..." -ForegroundColor Yellow
$connections = Get-NetTCPConnection -LocalPort 8502 -State Listen -ErrorAction SilentlyContinue
foreach ($connection in $connections) {
    Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue
}
python -m streamlit cache clear
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "cd '$PSScriptRoot'; python -m streamlit run .\apps\public_dashboard_app_v2_9.py --server.address 127.0.0.1 --server.port 8502"
)
Start-Sleep -Seconds 4
Start-Process "http://localhost:8502"

Write-Host "`nSector verification completed." -ForegroundColor Green
Write-Host "Press Ctrl+F5 in the browser if an old chart is cached." -ForegroundColor Green
