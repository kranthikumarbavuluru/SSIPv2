$ErrorActionPreference = "Stop"
$ProjectRoot = "D:\WebSite\DASHBOARD\Code\SSIP"
Set-Location $ProjectRoot

python -m pip install -r .\requirements-v3_4_0_3_3_1.txt
python -m py_compile .\scripts\dst_selective_queue_calibration_v3_4_0_3_3_1.py
python .\scripts\dst_selective_queue_calibration_v3_4_0_3_3_1.py --self-test
python -m pytest .\tests\test_dst_selective_queue_calibration_v3_4_0_3_3_1.py -q

python .\scripts\dst_selective_queue_calibration_v3_4_0_3_3_1.py `
  --project-root $ProjectRoot `
  --config .\config\dst_selective_queue_calibration_rules_v3_4_0_3_3_1.json `
  --prepare-only

Write-Host "Prepared calibrated queue. Review it before the network crawl." -ForegroundColor Cyan
Write-Host "Then run:" -ForegroundColor Yellow
Write-Host "python .\scripts\dst_selective_queue_calibration_v3_4_0_3_3_1.py --project-root `"$ProjectRoot`" --config .\config\dst_selective_queue_calibration_rules_v3_4_0_3_3_1.json --run-selective-crawl --max-targets 5"
