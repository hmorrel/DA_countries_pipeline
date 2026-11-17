# Agentic Countries Data Pipeline (Google ADK + GCS)

An end-to-end data engineering pipeline where **Google Agent Development Kit (ADK) agents** orchestrate every step:

1. **Ingest** – pull every country's population and land area from the public [World Bank Open Data API](https://datahelpdesk.worldbank.org/knowledgebase/articles/889392) (no API key needed)
2. **Process** – clean, de-duplicate, filter, and aggregate population, land area, and density by World Bank region and income group
3. **Visualize** – generate an HTML dashboard (Chart.js bar charts + summary tables)
4. **Store** – upload raw JSON, processed JSON, cleaned CSV, and the HTML report to **Google Cloud Storage**
5. **Report** – a final agent summarizes the run and key insights

## Architecture

```
User request ("Analyze only Europe, skip countries under 1M people")
        │
        ▼
countries_pipeline  (ADK SequentialAgent = orchestrator)
  ├── ingestion_agent      (LlmAgent) ── tool: fetch_country_data      → output/<run_id>/raw_countries.json
  ├── processing_agent     (LlmAgent) ── tool: transform_country_data  → processed_summary.json, countries_clean.csv
  │        └─ the agent reads the user's request and picks the region / min_population filters itself
  ├── visualization_agent  (LlmAgent) ── tool: generate_html_report    → report.html
  ├── storage_agent        (LlmAgent) ── tool: upload_to_cloud_storage → gs://<bucket>/<prefix>/<run_id>/*
  └── reporter_agent       (LlmAgent) ── no tools; writes the final run summary
```

Design notes:
- **One agent, one responsibility, one tool.** The `SequentialAgent` guarantees order; each `LlmAgent` decides how to call its tool and how to handle errors (e.g. the processing agent retries with `region='all'` if it chose an invalid region).
- **Agents communicate through ADK session state.** Each agent saves its reply under an `output_key` (`ingestion_result`, `processing_result`, …) that the next agent's instruction reads. Tools share file paths via `tool_context.state`, so large data never passes through the LLM.
- **Failures stop cleanly.** Every tool returns `{"status": "error", "message": ...}` instead of crashing; later agents see the failure and skip their step, and the reporter explains which step failed.

### Processing logic
| Step | What happens |
|---|---|
| Merge | Join three World Bank calls (country list, population `SP.POP.TOTL`, land area `AG.LND.TOTL.K2`) on ISO3 code; drop regional aggregates like "World" |
| Data quality | Drop records with no population or area data; de-duplicate by ISO code |
| Filter | Optional region and minimum-population filters chosen by the agent from the user's request |
| Derive | People per km² for each country |
| Aggregate by region & income group | Country count, total population, total land area, **population-weighted density**, median population, largest country |
| Rank | Top 10 most populous; top 10 densest (countries ≥ 1,000 km², so the list isn't only micro-states) |

## Project layout
```
pipeline_agent/
  agent.py     # ADK agents (root_agent = SequentialAgent)
  tools.py     # tool functions: fetch, transform, upload (+ pure helpers)
  report.py    # HTML dashboard renderer
  config.py    # settings from environment variables
run_pipeline.py  # CLI runner (ADK InMemoryRunner)
tests/           # unit tests (no network / LLM / cloud needed)
.env.example     # template for your secrets (copy to .env)
```

## Setup

**Prerequisites:** Python 3.10+, a Google Cloud project with a GCS bucket, and the [gcloud CLI](https://cloud.google.com/sdk/docs/install).

```bash
git clone <this-repo-url>
cd adk-countries-pipeline
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

1. **Gemini API key** (powers the agents): create a free key at <https://aistudio.google.com/apikey>.
2. **Cloud Storage bucket**:
   ```bash
   gcloud auth login
   gcloud config set project YOUR_PROJECT_ID
   gcloud storage buckets create gs://YOUR_BUCKET_NAME --location=us-central1
   gcloud auth application-default login     # lets the Python client upload
   ```
3. **Config**: `cp .env.example .env` and fill in `GOOGLE_API_KEY` and `GCS_BUCKET`. The `.env` file is git-ignored — no credentials are committed.

## Run

**Option A – command line**
```bash
python run_pipeline.py
python run_pipeline.py "Analyze only Europe and skip countries with fewer than 1 million people"
```
The console shows each agent's tool calls and replies, then lists the `gs://` URIs. Open `output/latest_report.html` in a browser to view the dashboard (it is also stored in the bucket as `report.html`).

**Option B – ADK web UI** (shows the agent trace, events, and state)
```bash
adk web
```
Open <http://localhost:8000>, pick `pipeline_agent`, and type a request such as *"Run the pipeline for Europe"*.

**Verify the upload**
```bash
gcloud storage ls gs://YOUR_BUCKET_NAME/countries-pipeline/
```

**Unit tests** (no keys or network needed)
```bash
python -m pytest -q
```

### No cloud account?
Set `STORAGE_BACKEND=local` in `.env` to write the "bucket" to `output/_local_bucket/` instead. This exists only for offline development; the intended configuration is GCS.

## Troubleshooting
| Symptom | Fix |
|---|---|
| `GCS_BUCKET is not set` | Add `GCS_BUCKET=...` to `.env` |
| `DefaultCredentialsError` / 403 on upload | Run `gcloud auth application-default login`; make sure your account has *Storage Object Creator* on the bucket |
| `API key not valid` / 429 from Gemini | Check `GOOGLE_API_KEY`; on free-tier rate limits wait a minute or check the model name in `ADK_MODEL` |
| Charts don't show | The report loads Chart.js from a CDN; open it with internet access (tables render either way) |

## Future improvements
See the separate *Future Improvements* document submitted with this assignment.
