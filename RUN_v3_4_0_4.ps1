$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

& .\BUILD_v3_4_0_4.ps1
if ($LASTEXITCODE -ne 0) { throw "Build failed; dashboard was not opened." }

& .\OPEN_DASHBOARD_v3_4_0_4.ps1
