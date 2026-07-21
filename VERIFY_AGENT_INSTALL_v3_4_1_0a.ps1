$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$required = @(
    ".\scripts\preflight_agents_v3_4_1_0.py",
    ".\scripts\verify_active_catalogue_v3_4_1_0.py",
    ".\agents\orchestrator.py",
    ".\agents\sector_agent.py",
    ".\config\agent_platform_v3_4_1_0.json",
    ".\config\sector_taxonomy_v3_4_1_0.json",
    ".\tests\test_agent_platform_v3_4_1_0.py"
)

$results = foreach ($item in $required) {
    [PSCustomObject]@{
        Path = $item
        Exists = Test-Path $item
    }
}

$results | Format-Table -AutoSize

if (($results | Where-Object { -not $_.Exists }).Count -gt 0) {
    throw "Installation verification failed. One or more files are missing."
}

Write-Host "Agent platform installation files are complete." -ForegroundColor Green
