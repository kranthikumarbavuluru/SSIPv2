Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = (
    Resolve-Path (
        Join-Path $PSScriptRoot ".."
    )
).Path

Set-Location $projectRoot

$env:PYTHONUNBUFFERED = "1"

& python -u `
  ".\scripts\meity_new_scheme_identity_evidence_agent_v3_4_3_3.py" `
  --browser auto `
  --timeout 60 `
  --browser-timeout-ms 30000

$exitCode = $LASTEXITCODE

if ($exitCode -eq 2) {
    throw (
        "MeitY v3.4.3.3 completed safely, but governed validation failed. " +
        "Inspect meity_new_scheme_validation_summary_v3_4_3_3.json."
    )
}

if ($exitCode -ne 0) {
    throw "MeitY v3.4.3.3 identity/evidence validation failed."
}
