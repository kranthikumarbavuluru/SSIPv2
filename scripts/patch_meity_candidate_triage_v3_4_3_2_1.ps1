Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = (
    Resolve-Path (
        Join-Path $PSScriptRoot ".."
    )
).Path

Set-Location $projectRoot

& python ".\scripts\patch_meity_candidate_triage_v3_4_3_2_1.py"

if ($LASTEXITCODE -ne 0) {
    throw "MeitY v3.4.3.2.1 patch failed."
}

& python -m py_compile `
  ".\scripts\meity_candidate_triage_agent_v3_4_3_2.py"

if ($LASTEXITCODE -ne 0) {
    throw "Patched triage agent did not compile."
}

& python `
  ".\scripts\meity_candidate_triage_agent_v3_4_3_2.py" `
  --self-test

if ($LASTEXITCODE -ne 0) {
    throw "Patched triage agent self-test failed."
}

Write-Host ""
Write-Host "Patch validation: PASS"
