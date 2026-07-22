# SSIP media intake folders

The v3.4.7.0 foundation accepts flyer images and PDFs in a dated inbox:

```text
media/inbox/YYYY-MM-DD/
```

Original files are never edited or deleted by the intake scan. Generated
manifests and reports are written to:

```text
data/media_runs/YYYY-MM-DD/
```

The scan registers file metadata and SHA-256 hashes. Reviewed records are
published through the hash-verified bundle in
`data/media_publication/v3_4_7_0/`; the dashboard never publishes directly
from an inbox image. OCR and QR decoding remain follow-up evidence tasks when
the flyer does not expose a durable application URL. Do not place credentials
or unrelated personal documents in the inbox.

Run a batch scan from the project root:

```powershell
python .\scripts\media_intake_v3_4_7_0.py --ingest-date 2026-07-22
```

Supported intake types currently include common image formats and PDF. Other
files are recorded as `UNSUPPORTED_MEDIA` so they are visible in the run
report rather than silently ignored.
