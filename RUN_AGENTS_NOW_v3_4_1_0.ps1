$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "SSIP v3.4.1.0a - Governed Agent Run" -ForegroundColor Cyan
Write-Host "Project root: $PSScriptRoot" -ForegroundColor DarkGray

$requiredFiles = @(
    ".\scripts\preflight_agents_v3_4_1_0.py",
    ".\scripts\verify_active_catalogue_v3_4_1_0.py",
    ".\agents\__init__.py",
    ".\agents\common.py",
    ".\agents\taxonomy.py",
    ".\agents\sector_agent.py",
    ".\agents\relevance_agent.py",
    ".\agents\call_agent.py",
    ".\agents\validation_agent.py",
    ".\agents\publication_agent.py",
    ".\agents\orchestrator.py",
    ".\config\agent_platform_v3_4_1_0.json",
    ".\config\sector_taxonomy_v3_4_1_0.json",
    ".\tests\test_agent_platform_v3_4_1_0.py",
    ".\data\catalogue_preview\v3_3_2\catalogue_preview_v3_3_2.csv",
    ".\apps\public_dashboard_app_v2_9.py"
)

$missing = @()
foreach ($file in $requiredFiles) {
    if (-not (Test-Path $file)) {
        $missing += $file
    }
}

if ($missing.Count -gt 0) {
    Write-Host "`nMissing required files:" -ForegroundColor Red
    $missing | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    throw "Agent platform extraction is incomplete. Re-extract the complete ZIP into $PSScriptRoot."
}

Write-Host "`nAll required files are present." -ForegroundColor Green

python .\scripts\preflight_agents_v3_4_1_0.py --project-root .
if ($LASTEXITCODE -ne 0) {
    throw "Preflight failed with exit code $LASTEXITCODE."
}

python -m pytest .\tests\test_agent_platform_v3_4_1_0.py -q
if ($LASTEXITCODE -ne 0) {
    throw "Agent tests failed with exit code $LASTEXITCODE."
}

python -m agents.orchestrator --project-root . --config config/agent_platform_v3_4_1_0.json
if ($LASTEXITCODE -ne 0) {
    throw "Agent orchestration failed with exit code $LASTEXITCODE."
}

python .\scripts\verify_active_catalogue_v3_4_1_0.py .
if ($LASTEXITCODE -ne 0) {
    throw "Active dashboard catalogue verification failed with exit code $LASTEXITCODE."
}

Write-Host "Clearing Streamlit cache..." -ForegroundColor Yellow
python -m streamlit cache clear 2>$null

$port = 8502
$connections = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
foreach ($connection in $connections) {
    try {
        Stop-Process -Id $connection.OwningProcess -Force -ErrorAction Stop
    } catch {
        Write-Host "Could not stop process $($connection.OwningProcess): $($_.Exception.Message)" -ForegroundColor Yellow
    }
}
Start-Sleep -Seconds 2

Write-Host "Starting dashboard at http://localhost:8502" -ForegroundColor Green
Start-Process -FilePath "python" -ArgumentList @(
    "-m", "streamlit", "run",
    ".\apps\public_dashboard_app_v2_9.py",
    "--server.address", "127.0.0.1",
    "--server.port", "8502"
) -WorkingDirectory $PSScriptRoot

Write-Host "`nAgent run and dashboard publication completed." -ForegroundColor Green
