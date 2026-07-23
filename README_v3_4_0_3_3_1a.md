# SSIP v3.4.0.3.3.1a — Accessibility Classification Allow-list Hotfix

This is a drop-in correction for the completed DST v3.4.0.3.3.1 run.

## Confirmed cause

The run correctly classified two rows as `ACCESSIBILITY_LINK`, but that legitimate terminal classification was missing from `ALLOWED_FINAL_CLASSES`. This alone caused:

- `all_final_classifications_valid: false`
- `calibration_validation_passed: false`
- `ready_for_v3_4_0_4: false`

`identity_locked: false` is expected at this stage. Canonical identities are deliberately not locked until v3.4.0.4.

## Install

Extract this ZIP directly into:

```text
D:\WebSite\DASHBOARD\Code\SSIP
```

Allow Windows to replace the existing script and test file.

## Verify and rerun

```powershell
cd D:\WebSite\DASHBOARD\Code\SSIP

python -m py_compile `
  .\scripts\dst_selective_queue_calibration_v3_4_0_3_3_1.py

python .\scripts\dst_selective_queue_calibration_v3_4_0_3_3_1.py --self-test

python -m pytest `
  .\tests\test_dst_selective_queue_calibration_v3_4_0_3_3_1.py `
  -q

python .\scripts\dst_selective_queue_calibration_v3_4_0_3_3_1.py `
  --project-root "D:\WebSite\DASHBOARD\Code\SSIP" `
  --config .\config\dst_selective_queue_calibration_rules_v3_4_0_3_3_1.json `
  --run-selective-crawl `
  --strict
```

The crawl output is resumable. The previously fetched target should be reused; the run should not need to rediscover or recursively crawl the site.

## Required result

```json
{
  "all_final_classifications_valid": true,
  "identity_locked": false,
  "calibration_validation_passed": true,
  "ready_for_v3_4_0_4": true
}
```
