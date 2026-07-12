$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Invoke-PythonChecked {
    param([string[]]$Arguments, [string]$StepName)
    Write-Host "`n--- $StepName ---" -ForegroundColor Yellow
    $old = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & python @Arguments
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $old
    }
    if ($code -ne 0) {
        throw ("{0} failed with exit code {1}: python {2}" -f $StepName, $code, ($Arguments -join " "))
    }
}

Write-Host "SSIP v3.4.2.1 - Intelligent Catalogue Governance" -ForegroundColor Cyan
Write-Host "LM Studio: disabled by default" -ForegroundColor DarkGray

$required = @(
    ".\agents\v3420\orchestrator.py",
    ".\config\catalogue_governance_v3_4_2_1.json",
    ".\config\sector_taxonomy_v3_4_2_1.json",
    ".\tests\test_governance_agents_v3_4_2_1.py",
    ".\data\catalogue_preview\v3_3_2\catalogue_preview_v3_3_2.csv"
)
$missing = @($required | Where-Object { -not (Test-Path $_) })
if ($missing.Count -gt 0) {
    $missing | ForEach-Object { Write-Host "Missing: $_" -ForegroundColor Red }
    throw "Package extraction is incomplete."
}

Invoke-PythonChecked `
    -Arguments @("-m", "pytest", ".\tests\test_governance_agents_v3_4_2_1.py", "-q") `
    -StepName "Governance agent tests"

Invoke-PythonChecked `
    -Arguments @("-m", "agents.v3420.orchestrator", "--project-root", ".", "--config", "config\catalogue_governance_v3_4_2_1.json") `
    -StepName "Catalogue governance and publication"

Invoke-PythonChecked `
    -Arguments @(".\scripts\verify_governance_v3_4_2_1.py", ".") `
    -StepName "Active dashboard catalogue verification"

$old = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    & python -m streamlit cache clear
} finally {
    $ErrorActionPreference = $old
}

$port = 8502
Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object {
        try { Stop-Process -Id $_.OwningProcess -Force -ErrorAction Stop } catch {}
    }
Start-Sleep -Seconds 2

Start-Process -FilePath "python" -ArgumentList @(
    "-m", "streamlit", "run",
    ".\apps\public_dashboard_app_v2_9.py",
    "--server.address", "127.0.0.1",
    "--server.port", "8502"
) -WorkingDirectory $PSScriptRoot

Write-Host "`nGovernance publication completed. Dashboard: http://localhost:8502" -ForegroundColor Green
