Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = (
    Resolve-Path (
        Join-Path $PSScriptRoot ".."
    )
).Path

Set-Location $projectRoot

& python `
  ".\scripts\meity_department_discovery_agent_v3_4_3_0.py" `
  --max-pages 300 `
  --max-depth 4 `
  --delay 0.25 `
  --use-llm auto `
  --llm-max 40

if ($LASTEXITCODE -ne 0) {
    throw "MeitY v3.4.3.0 department-wide discovery failed."
}
