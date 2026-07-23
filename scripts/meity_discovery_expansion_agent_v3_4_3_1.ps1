Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = (
    Resolve-Path (
        Join-Path $PSScriptRoot ".."
    )
).Path

Set-Location $projectRoot

& python `
  ".\scripts\meity_discovery_expansion_agent_v3_4_3_1.py" `
  --max-pages 400 `
  --max-depth 5 `
  --delay 0.35 `
  --browser auto `
  --use-llm auto `
  --llm-max 60 `
  --min-pages 20 `
  --min-detail-urls 8 `
  --min-master-candidates 4

$exitCode = $LASTEXITCODE

if ($exitCode -eq 2) {
    throw (
        "MeitY v3.4.3.1 finished safely, but department-wide " +
        "coverage validation failed. Inspect the generated summary."
    )
}

if ($exitCode -ne 0) {
    throw "MeitY v3.4.3.1 discovery expansion failed."
}
