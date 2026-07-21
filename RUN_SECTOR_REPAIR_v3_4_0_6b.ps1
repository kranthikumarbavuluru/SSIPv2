param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Invoke-PythonChecked {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$PythonArguments
    )

    $previousPreference = $ErrorActionPreference
    try {
        # Python/pytest may write warnings to stderr even when the exit code is zero.
        $ErrorActionPreference = "Continue"
        & python @PythonArguments
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }

    if ($exitCode -ne 0) {
        throw ("Python failed with exit code {0}: python {1}" -f $exitCode, ($PythonArguments -join " "))
    }
}

function Assert-RequiredFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required file is missing: $Path`nRe-extract the complete v3.4.0.6d ZIP into D:\WebSite\DASHBOARD\Code\SSIP and allow file replacement."
    }
}

Write-Host "SSIP v3.4.0.6d - Complete Active Catalogue Sector Repair" -ForegroundColor Cyan
Write-Host "=========================================================" -ForegroundColor Cyan

$requiredFiles = @(
    ".\requirements-v3_4_0_6b.txt",
    ".\config\sector_rules_v3_4_0_6b.json",
    ".\scripts\sector_catalogue_repair_v3_4_0_6b.py",
    ".\scripts\verify_dashboard_sector_source_v3_4_0_6b.py",
    ".\data\catalogue_preview\v3_3_2\catalogue_preview_v3_3_2.csv"
)

if (-not $SkipTests) {
    $requiredFiles += ".\tests\test_sector_catalogue_repair_v3_4_0_6b.py"
}

foreach ($file in $requiredFiles) {
    Assert-RequiredFile $file
}

Invoke-PythonChecked -PythonArguments @("-m", "pip", "install", "-r", ".\requirements-v3_4_0_6b.txt")
Invoke-PythonChecked -PythonArguments @("-m", "py_compile", ".\scripts\sector_catalogue_repair_v3_4_0_6b.py", ".\scripts\verify_dashboard_sector_source_v3_4_0_6b.py")
Invoke-PythonChecked -PythonArguments @(".\scripts\sector_catalogue_repair_v3_4_0_6b.py", "--project-root", $PSScriptRoot, "--self-test")

if (-not $SkipTests) {
    Invoke-PythonChecked -PythonArguments @("-m", "pytest", ".\tests\test_sector_catalogue_repair_v3_4_0_6b.py", "-q")
}
else {
    Write-Host "Automated pytest step skipped by explicit -SkipTests flag." -ForegroundColor Yellow
}

Invoke-PythonChecked -PythonArguments @(
    ".\scripts\sector_catalogue_repair_v3_4_0_6b.py",
    "--project-root", $PSScriptRoot,
    "--input", ".\data\catalogue_preview\v3_3_2\catalogue_preview_v3_3_2.csv",
    "--allow-network",
    "--apply",
    "--progress"
)

Invoke-PythonChecked -PythonArguments @(
    ".\scripts\verify_dashboard_sector_source_v3_4_0_6b.py",
    "--project-root", $PSScriptRoot
)

$validationPath = ".\data\sector_verification\v3_4_0_6b\sector_validation_v3_4_0_6b.json"
$summaryPath = ".\data\sector_verification\v3_4_0_6b\sector_summary_v3_4_0_6b.json"
$mappingPath = ".\data\sector_verification\v3_4_0_6b\sector_scheme_mapping_v3_4_0_6b.csv"

Assert-RequiredFile $validationPath
Assert-RequiredFile $summaryPath
Assert-RequiredFile $mappingPath

Write-Host "`n=== VALIDATION ===" -ForegroundColor Green
Get-Content $validationPath -Encoding UTF8
Write-Host "`n=== SUMMARY ===" -ForegroundColor Green
Get-Content $summaryPath -Encoding UTF8
Write-Host "`n=== SCHEME TO SECTOR MAP ===" -ForegroundColor Green
Import-Csv $mappingPath |
    Select-Object scheme_name, primary_sector, confidence, method, review_required |
    Format-Table -AutoSize -Wrap

Write-Host "`nRestarting Streamlit on port 8502..." -ForegroundColor Yellow
Get-NetTCPConnection -LocalPort 8502 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object {
        Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
    }

Invoke-PythonChecked -PythonArguments @("-m", "streamlit", "cache", "clear")

Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy", "Bypass",
    "-Command",
    "cd '$PSScriptRoot'; python -m streamlit run .\apps\public_dashboard_app_v2_9.py --server.address 127.0.0.1 --server.port 8502"
)

Start-Sleep -Seconds 4
Start-Process "http://localhost:8502"
Write-Host "`nSector repair completed. Press Ctrl+F5 in the browser." -ForegroundColor Green
