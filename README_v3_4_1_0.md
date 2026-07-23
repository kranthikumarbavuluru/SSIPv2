# SSIP v3.4.1.0 — Governed Nightly Agent Platform

## Purpose

This package replaces one-off sector scripts with a governed agent system under
the `agents/` directory.

It performs:

1. Active catalogue discovery
2. Official-source evidence retrieval
3. Scheme-by-scheme sector classification
4. Startup relevance validation
5. Deterministic classification
6. LM Studio adjudication for ambiguous records
7. Independent LLM verifier pass
8. Controlled-taxonomy validation
9. Manual-review queue creation
10. Atomic publication and backup
11. Dashboard restart
12. Midnight Windows Task Scheduler execution

## Accuracy policy

No model can guarantee 100% semantic accuracy. This platform instead guarantees:

- 100% rows processed
- zero blank sector values
- controlled taxonomy only
- exact evidence retained
- LLM labels rejected unless they use the taxonomy
- LLM evidence rejected unless found verbatim
- two-pass LLM agreement for ambiguous records
- review flags retained
- atomic publication
- versioned backups and manifests

## Installation

Extract into the SSIP project root:

`D:\WebSite\DASHBOARD\Code\SSIP`

Then run:

```powershell
cd D:\WebSite\DASHBOARD\Code\SSIP
python -m pip install -r .\requirements-v3_4_1_0.txt
python -m pytest .\tests\test_agent_platform_v3_4_1_0.py -q
.\RUN_AGENTS_NOW_v3_4_1_0.ps1
```

## Install midnight schedule

Open PowerShell as Administrator:

```powershell
cd D:\WebSite\DASHBOARD\Code\SSIP
Set-ExecutionPolicy -Scope Process Bypass -Force
.\INSTALL_MIDNIGHT_TASK_v3_4_1_0.ps1
```

## LM Studio

Start the LM Studio local server on port 1234 and load one instruction model.
The agent auto-detects the loaded model through `/v1/models`.

For a 16 GB Windows system, begin with an 8B instruction model in a 4-bit
quantization. Larger 12B–14B models may be usable but leave less memory for
Python, Streamlit and the operating system.

The deterministic classifier remains active when LM Studio is unavailable.
Ambiguous rows are marked for review rather than silently accepted.

## Outputs

- `data/agent_state/ssip_agents_v3_4_1_0.sqlite3`
- `data/agent_state/runs/<run_id>/sector_audit.csv`
- `data/agent_state/runs/<run_id>/manual_review_queue.csv`
- `data/agent_state/runs/<run_id>/summary.json`
- `data/agent_state/runs/<run_id>/validation.json`
- `data/publication/current_manifest.json`
- `data/publication/<run_id>/catalogue.csv`
- `logs/agents/`

## Active dashboard catalogue

The platform atomically updates:

`data\catalogue_preview\v3_3_2\catalogue_preview_v3_3_2.csv`

This is intentional because the current public dashboard reads that file.
Every publication first creates a versioned backup.
