# SSIP media intake and publication pipeline

Place flyer images and PDFs in `media/inbox/YYYY-MM-DD/`. Raw files are never
edited or moved by the pipeline. Every batch creates a SHA-256 asset registry
and read-only report under `data/media_runs/YYYY-MM-DD/`.

Run the complete incremental pipeline with:

```powershell
python .\scripts\run_media_pipeline_v3_4_7_4.py --ingest-date 2026-07-22
```

The stages are:

1. `v3.4.7.0` — dated inboxes, asset registry, SHA-256 deduplication and intake reports.
2. `v3.4.7.1` — optional Pillow preprocessing, OCR, script-language detection, QR/barcode engines, printed/embedded links and field-level evidence. Missing engines are recorded as warnings.
3. `v3.4.7.2` — scheme/call/challenge classification, department/agency rules, `Others / Unmapped`, duplicate candidates and parent hints.
4. `v3.4.7.3` — separate Streamlit review workspace (`ui/media_review_app_v3_4_7_3.py`), append-only corrections and decisions, and a validated public projection.
5. `v3.4.7.4` — daily incremental orchestration, run state, failure alerts and immutable publication versions for rollback.

Only an explicit `APPROVE` decision with an HTTPS official URL and mapped
department can enter the v3.4.7.3 public projection. The existing v3.4.7.0
bundle remains the fallback until a newer active projection is available.

Register the Windows daily task only when ready:

```powershell
.\scripts\register_media_task_v3_4_7_4.ps1
```

Raw images, extraction evidence and review corrections remain traceable by
asset ID and digest. QR/OCR warnings are preserved rather than silently
discarded.
