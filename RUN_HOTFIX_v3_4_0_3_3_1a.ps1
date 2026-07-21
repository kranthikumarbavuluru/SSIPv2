$ErrorActionPreference = "Stop"
$ProjectRoot = "D:\WebSite\DASHBOARD\Code\SSIP"
Set-Location $ProjectRoot

python -m py_compile .\scripts\dst_selective_queue_calibration_v3_4_0_3_3_1.py
python .\scripts\dst_selective_queue_calibration_v3_4_0_3_3_1.py --self-test
python -m pytest .\tests\test_dst_selective_queue_calibration_v3_4_0_3_3_1.py -q

python .\scripts\dst_selective_queue_calibration_v3_4_0_3_3_1.py `
  --project-root $ProjectRoot `
  --config .\config\dst_selective_queue_calibration_rules_v3_4_0_3_3_1.json `
  --run-selective-crawl `
  --strict

Write-Host "`n=== VALIDATION ===" -ForegroundColor Green
Get-Content .\data\departments\dst\v3_4_0_3_3_1\dst_calibration_validation_v3_4_0_3_3_1.json -Encoding UTF8
