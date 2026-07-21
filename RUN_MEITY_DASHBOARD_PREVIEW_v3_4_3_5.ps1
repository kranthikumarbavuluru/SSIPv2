param(
    [int]$Port = 8502
)

$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

$Preview = Join-Path `
    $ProjectRoot `
    "data\catalogue_preview\v3_4_3_5\catalogue_preview_v3_4_3_5.csv"

if (-not (Test-Path -LiteralPath $Preview)) {
    throw "v3.4.3.5 preview catalogue not found: $Preview"
}

$env:SSIP_PUBLIC_CATALOGUE_MODE = "CATALOGUE_PREVIEW"
$env:SSIP_CATALOGUE_PREVIEW_PATH = $Preview

Write-Host ""
Write-Host "SSIP v3.4.3.5 governed-action dashboard preview"
Write-Host "----------------------------------------------------"
Write-Host "Catalogue: $Preview"
Write-Host "Port:      $Port"
Write-Host "Mode:      $env:SSIP_PUBLIC_CATALOGUE_MODE"
Write-Host ""

python -m streamlit run `
    ".\apps\public_dashboard_app_v2_9.py" `
    --server.port $Port
