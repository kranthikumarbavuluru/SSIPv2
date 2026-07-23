Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = (
    Resolve-Path (
        Join-Path $PSScriptRoot ".."
    )
).Path

Set-Location $projectRoot

& python ".\scripts\meity_application_link_hotfix_v3_4_2_0_3.py"

if ($LASTEXITCODE -ne 0) {
    throw "MeitY v3.4.2.0.3 application-link hotfix failed."
}
