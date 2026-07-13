Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = (
    Resolve-Path (
        Join-Path $PSScriptRoot ".."
    )
).Path

Set-Location $projectRoot

& python `
  ".\scripts\meity_governed_publish_v3_4_2_0_2.py" `
  --confirm-publish

if ($LASTEXITCODE -ne 0) {
    throw "MeitY v3.4.2.0.2 governed publication failed."
}
