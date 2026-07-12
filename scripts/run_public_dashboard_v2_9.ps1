param(
    [ValidateSet("CATALOGUE_PREVIEW", "PUBLISHED_ONLY")]
    [string]$CatalogueMode = "CATALOGUE_PREVIEW",
    [int]$Port = 8501
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$env:SSIP_PUBLIC_CATALOGUE_MODE = $CatalogueMode

$Python = "python"
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    # The bundled environment may exist without the optional dashboard package.
    # Probe it without allowing PowerShell's native-command error promotion to
    # abort the documented system-Python fallback.
    $PreviousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $VenvPython -c "import streamlit" 1>$null 2>$null
    $VenvImportExitCode = $LASTEXITCODE
    $ErrorActionPreference = $PreviousErrorActionPreference
    if ($VenvImportExitCode -eq 0) {
        $Python = $VenvPython
    }
    else {
        Write-Warning "Project virtual environment does not have Streamlit; using system Python."
    }
}

Write-Host "Starting SSIP public dashboard v2.9"
Write-Host "Catalogue mode: $CatalogueMode"
Write-Host "URL: http://localhost:$Port"

& $Python -m streamlit run `
    (Join-Path $ProjectRoot "apps\public_dashboard_app_v2_9.py") `
    --server.port $Port `
    --server.address "localhost"
