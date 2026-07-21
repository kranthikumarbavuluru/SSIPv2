Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = (
    Resolve-Path (
        Join-Path $PSScriptRoot ".."
    )
).Path

Set-Location $projectRoot

& python ".\scripts\meity_candidate_triage_agent_v3_4_3_2.py"

if ($LASTEXITCODE -eq 2) {
    throw "MeitY v3.4.3.2 completed safely but validation failed."
}

if ($LASTEXITCODE -ne 0) {
    throw "MeitY v3.4.3.2 candidate triage failed."
}
