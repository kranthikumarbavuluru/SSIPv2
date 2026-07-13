# SSIP v3.4.0.3.3.1 — DST Selective Queue Calibration and Unresolved Target Triage

This bundle fixes the v3.4.0.3.3 queue gate that rejected all unresolved targets when `main_content_occurrences` was zero. It performs deterministic non-entity closure, weighted scoring, a small resumable depth-0 crawl, and manual-review routing.

## Extract location

Extract the ZIP directly into:

```text
D:\WebSite\DASHBOARD\Code\SSIP
```

The ZIP already contains the correct `scripts`, `config`, and `tests` folders.

## Required v3.4.0.3.3 inputs

```text
data\departments\dst\v3_4_0_3_3\
├── dst_gap_link_context_v3_4_0_3_3.csv
├── dst_final_gap_review_queue_v3_4_0_3_3.csv
├── dst_final_corrected_schemes_v3_4_0_3_3.csv
├── dst_final_corrected_programmes_v3_4_0_3_3.csv
└── dst_gap_resolution_summary_v3_4_0_3_3.json
```

The optional file `dst_calibrated_unresolved_targets.csv` is also read when present.

## Verify

```powershell
cd D:\WebSite\DASHBOARD\Code\SSIP

python -m pip install `
  -r .\requirements-v3_4_0_3_3_1.txt

python -m py_compile `
  .\scripts\dst_selective_queue_calibration_v3_4_0_3_3_1.py

python `
  .\scripts\dst_selective_queue_calibration_v3_4_0_3_3_1.py `
  --self-test

python -m pytest `
  .\tests\test_dst_selective_queue_calibration_v3_4_0_3_3_1.py `
  -q
```

Expected: `self_test_passed: true` and `8 passed`.

## Prepare without network access

```powershell
python `
  .\scripts\dst_selective_queue_calibration_v3_4_0_3_3_1.py `
  --project-root "D:\WebSite\DASHBOARD\Code\SSIP" `
  --config .\config\dst_selective_queue_calibration_rules_v3_4_0_3_3_1.json `
  --prepare-only
```

## Controlled crawl pilot

```powershell
python `
  .\scripts\dst_selective_queue_calibration_v3_4_0_3_3_1.py `
  --project-root "D:\WebSite\DASHBOARD\Code\SSIP" `
  --config .\config\dst_selective_queue_calibration_rules_v3_4_0_3_3_1.json `
  --run-selective-crawl `
  --max-targets 5
```

## Complete and validate

```powershell
python `
  .\scripts\dst_selective_queue_calibration_v3_4_0_3_3_1.py `
  --project-root "D:\WebSite\DASHBOARD\Code\SSIP" `
  --config .\config\dst_selective_queue_calibration_rules_v3_4_0_3_3_1.json `
  --run-selective-crawl `
  --strict
```

Successful completion requires:

```json
{
  "calibration_validation_passed": true,
  "ready_for_v3_4_0_4": true
}
```

## Output directory

```text
data\departments\dst\v3_4_0_3_3_1\
```

This stage does not lock canonical identities and does not write to the production database. New scheme/programme candidates remain `PROVISIONAL_NOT_LOCKED` for v3.4.0.4 curation and dashboard publication preparation.
