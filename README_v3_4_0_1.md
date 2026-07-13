# SSIP v3.4.0.1 — DST Source Registry and Department Crawler

This bundle contains the production crawler for the first department-wise SSIP pass.

## Identity rule

This phase does **not** create a canonical scheme master. It stores source pages,
page titles and crawl-role hints. A time-bound call title cannot overwrite or
be promoted to a permanent scheme name.

## Files

- `scripts/dst_source_registry_and_crawler_v3_4_0_1.py`
- `config/dst_source_registry_v3_4_0_1.json`
- `tests/test_dst_source_registry_and_crawler_v3_4_0_1.py`
- `requirements-v3_4_0_1.txt`

Copy the folder contents into the matching folders under the SSIP project root.

## Install

```powershell
cd D:\WebSite\DASHBOARD\Code\SSIP
python -m pip install -r .\requirements-v3_4_0_1.txt
```

## Compile and self-test

```powershell
python -m py_compile .\scripts\dst_source_registry_and_crawler_v3_4_0_1.py
python .\scripts\dst_source_registry_and_crawler_v3_4_0_1.py --self-test
```

## Validate the crawl plan without network or file changes

```powershell
python .\scripts\dst_source_registry_and_crawler_v3_4_0_1.py `
  --project-root "D:\WebSite\DASHBOARD\Code\SSIP" `
  --config .\config\dst_source_registry_v3_4_0_1.json `
  --dry-run
```

## Controlled first network run

```powershell
python .\scripts\dst_source_registry_and_crawler_v3_4_0_1.py `
  --project-root "D:\WebSite\DASHBOARD\Code\SSIP" `
  --config .\config\dst_source_registry_v3_4_0_1.json `
  --max-pages 25 `
  --max-depth 5 `
  --delay 1.0
```

Review `data\departments\dst\v3_4_0_1\crawl\dst_crawl_summary_v3_4_0_1.json`.

## Continue/resume the full crawl

The state database makes the process resumable. Run the same command without
`--max-pages`:

```powershell
python .\scripts\dst_source_registry_and_crawler_v3_4_0_1.py `
  --project-root "D:\WebSite\DASHBOARD\Code\SSIP" `
  --config .\config\dst_source_registry_v3_4_0_1.json `
  --max-depth 5 `
  --delay 1.0
```

## Optional document download pass

Documents are discovered and recorded by default. To download them as well:

```powershell
python .\scripts\dst_source_registry_and_crawler_v3_4_0_1.py `
  --project-root "D:\WebSite\DASHBOARD\Code\SSIP" `
  --config .\config\dst_source_registry_v3_4_0_1.json `
  --download-documents `
  --max-documents 50 `
  --delay 1.0
```

## Outputs

The crawler writes under:

`data\departments\dst\v3_4_0_1\crawl\`

Important outputs:

- `dst_source_registry_v3_4_0_1.csv`
- `dst_crawled_pages_v3_4_0_1.csv`
- `dst_discovered_documents_v3_4_0_1.csv`
- `dst_external_official_links_v3_4_0_1.csv`
- `dst_link_graph_v3_4_0_1.csv`
- `dst_crawl_frontier_v3_4_0_1.csv`
- `dst_crawl_errors_v3_4_0_1.csv`
- `dst_crawl_summary_v3_4_0_1.json`
- `dst_crawl_state_v3_4_0_1.db`
- `snapshots\html\*.html.gz`

## Restart and refresh controls

Re-crawl all known URLs while preserving the state and evidence tables:

```powershell
python .\scripts\dst_source_registry_and_crawler_v3_4_0_1.py `
  --project-root "D:\WebSite\DASHBOARD\Code\SSIP" `
  --config .\config\dst_source_registry_v3_4_0_1.json `
  --refresh
```

Delete crawl state and start again:

```powershell
python .\scripts\dst_source_registry_and_crawler_v3_4_0_1.py `
  --project-root "D:\WebSite\DASHBOARD\Code\SSIP" `
  --config .\config\dst_source_registry_v3_4_0_1.json `
  --reset-state `
  --max-pages 25
```
