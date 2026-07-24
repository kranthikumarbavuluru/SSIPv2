$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\")).Path
Push-Location $ProjectRoot
try {
    python -m unittest tests.test_mymsme_agent_v3_4_6_0 -v
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally { Pop-Location }
