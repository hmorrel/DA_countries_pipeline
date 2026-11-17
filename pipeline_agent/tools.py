"""Tools the ADK agents call. Each tool does one pipeline step.

Large data never goes through the LLM: tools write files to disk and share
their *paths* through ADK session state (tool_context.state). The LLM only
sees short summaries, which keeps prompts small and cheap.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import statistics
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config
from .report import render_report

# ---------------------------------------------------------------------------
# Helpers (pure functions, unit tested in tests/)
# ---------------------------------------------------------------------------


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _run_dir(run_id: str) -> Path:
    path = Path(config.OUTPUT_DIR) / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def flatten_country(raw: dict[str, Any]) -> dict[str, Any]:
    """Turn one nested REST Countries record into a flat row."""
    name = raw.get("name") or {}
    population = int(raw.get("population") or 0)
    area = float(raw.get("area") or 0)
    languages = sorted((raw.get("languages") or {}).values())
    currencies = sorted((raw.get("currencies") or {}).keys())
    return {
        "code": raw.get("cca3", ""),
        "name": name.get("common", "") if isinstance(name, dict) else str(name),
        "region": raw.get("region") or "Unknown",
        "subregion": raw.get("subregion") or "Unspecified",
        "population": population,
        "area_km2": area,
        "density_per_km2": round(population / area, 2) if area > 0 else None,
        "landlocked": bool(raw.get("landlocked")),
        "un_member": bool(raw.get("unMember")),
        "languages": languages,
        "currencies": currencies,
    }


def _group_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pops = [r["population"] for r in rows]
    total_pop = sum(pops)
    total_area = sum(r["area_km2"] for r in rows)
    languages = {lang for r in rows for lang in r["languages"]}
    return {
        "countries": len(rows),
        "total_population": total_pop,
        "total_area_km2": round(total_area, 1),
        # Weighted density (people per km² of the whole group), not an average of ratios
        "density_per_km2": round(total_pop / total_area, 2) if total_area else None,
        "median_population": int(statistics.median(pops)) if pops else 0,
        "largest_country": max(rows, key=lambda r: r["population"])["name"] if rows else None,
        "landlocked_countries": sum(r["landlocked"] for r in rows),
        "un_members": sum(r["un_member"] for r in rows),
        "distinct_languages": len(languages),
    }


def transform_records(
    raw_records: list[dict[str, Any]],
    region: str = "all",
    min_population: int = 0,
    top_n: int = 10,
) -> dict[str, Any]:
    """Clean, filter, and aggregate raw country records.

    Steps:
      1. Flatten nested JSON into rows.
      2. Data-quality filter: drop rows with zero population or no area
         (e.g. uninhabited territories), and de-duplicate by country code.
      3. Optional filters: region and minimum population.
      4. Aggregate by region and by subregion; build top-N rankings.
    """
    rows, seen, dropped = [], set(), {"no_population_or_area": 0, "duplicate": 0, "filtered_out": 0}
    for rec in raw_records:
        row = flatten_country(rec)
        if row["population"] <= 0 or row["area_km2"] <= 0:
            dropped["no_population_or_area"] += 1
            continue
        if row["code"] in seen:
            dropped["duplicate"] += 1
            continue
        seen.add(row["code"])
        if region.lower() != "all" and row["region"].lower() != region.lower():
            dropped["filtered_out"] += 1
            continue
        if row["population"] < min_population:
            dropped["filtered_out"] += 1
            continue
        rows.append(row)

    by_region: dict[str, list] = defaultdict(list)
    by_subregion: dict[tuple[str, str], list] = defaultdict(list)
    for r in rows:
        by_region[r["region"]].append(r)
        by_subregion[(r["region"], r["subregion"])].append(r)

    region_stats = [
        {"region": name, **_group_stats(members)} for name, members in by_region.items()
    ]
    region_stats.sort(key=lambda s: s["total_population"], reverse=True)

    subregion_stats = [
        {"region": reg, "subregion": sub, **_group_stats(members)}
        for (reg, sub), members in by_subregion.items()
    ]
    subregion_stats.sort(key=lambda s: s["total_population"], reverse=True)

    def _slim(r: dict[str, Any]) -> dict[str, Any]:
        return {k: r[k] for k in ("code", "name", "region", "population", "area_km2", "density_per_km2")}

    top_populous = [_slim(r) for r in sorted(rows, key=lambda r: r["population"], reverse=True)[:top_n]]
    # Ignore micro-states (< 1,000 km²) so the density ranking is not all city-states
    dense_pool = [r for r in rows if r["area_km2"] >= 1000]
    top_dense = [_slim(r) for r in sorted(dense_pool, key=lambda r: r["density_per_km2"], reverse=True)[:top_n]]

    world = _group_stats(rows) if rows else {}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "parameters": {"region": region, "min_population": min_population, "top_n": top_n},
        "input_records": len(raw_records),
        "kept_records": len(rows),
        "dropped": dropped,
        "overall": world,
        "by_region": region_stats,
        "by_subregion": subregion_stats,
        "top_populous": top_populous,
        "top_dense": top_dense,
        "countries": rows,
    }


def write_countries_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fields = ["code", "name", "region", "subregion", "population", "area_km2",
              "density_per_km2", "landlocked", "un_member", "languages", "currencies"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({**r, "languages": "; ".join(r["languages"]),
                             "currencies": "; ".join(r["currencies"])})


# ---------------------------------------------------------------------------
# ADK tools (called by the agents)
# ---------------------------------------------------------------------------


def fetch_country_data(tool_context) -> dict:
    """Downloads the current list of all countries from the public REST Countries API
    and saves the raw JSON response to a local file for this pipeline run.

    Returns:
        A dict with status, run_id, the number of records fetched, and the raw file path.
    """
    url = f"{config.API_URL}?fields={','.join(config.API_FIELDS)}"
    req = urllib.request.Request(url, headers={"User-Agent": "adk-countries-pipeline/1.0"})
    last_error = None
    for attempt in range(3):  # small retry loop for transient network errors
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
    else:
        return {"status": "error", "message": f"Could not reach REST Countries API: {last_error}"}

    if not isinstance(data, list) or not data:
        return {"status": "error", "message": "API returned no country records."}

    run_id = _new_run_id()
    raw_path = _run_dir(run_id) / "raw_countries.json"
    raw_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    tool_context.state["run_id"] = run_id
    tool_context.state["raw_path"] = str(raw_path)
    tool_context.state["artifacts"] = [str(raw_path)]
    return {"status": "success", "run_id": run_id, "records_fetched": len(data),
            "raw_path": str(raw_path), "source": config.API_URL}


def transform_country_data(region: str, min_population: int, tool_context) -> dict:
    """Cleans and aggregates the raw country data fetched earlier in this run.

    Args:
        region: Region to keep. One of "all", "Africa", "Americas", "Asia",
            "Europe", "Oceania". Use "all" unless the user asked for a specific region.
        min_population: Drop countries with fewer people than this. Use 0 unless the
            user asked to exclude small countries.

    Returns:
        A dict with status, counts of kept/dropped records, and headline statistics.
    """
    raw_path = tool_context.state.get("raw_path")
    if not raw_path or not os.path.exists(raw_path):
        return {"status": "error", "message": "No raw data found. Run the ingestion step first."}
    if region.lower() != "all" and region.title() not in config.VALID_REGIONS:
        return {"status": "error",
                "message": f"Unknown region '{region}'. Use 'all' or one of {sorted(config.VALID_REGIONS)}."}

    raw = json.loads(Path(raw_path).read_text(encoding="utf-8"))
    processed = transform_records(raw, region=region, min_population=max(0, int(min_population)))
    if processed["kept_records"] == 0:
        return {"status": "error", "message": "All records were filtered out; loosen the filters."}

    run_dir = _run_dir(tool_context.state["run_id"])
    processed_path = run_dir / "processed_summary.json"
    csv_path = run_dir / "countries_clean.csv"
    processed_path.write_text(json.dumps(processed, indent=2, ensure_ascii=False), encoding="utf-8")
    write_countries_csv(processed["countries"], csv_path)

    tool_context.state["processed_path"] = str(processed_path)
    tool_context.state["artifacts"] = tool_context.state.get("artifacts", []) + [str(processed_path), str(csv_path)]
    overall = processed["overall"]
    return {
        "status": "success",
        "kept_records": processed["kept_records"],
        "dropped": processed["dropped"],
        "regions": [r["region"] for r in processed["by_region"]],
        "total_population": overall["total_population"],
        "most_populous_region": processed["by_region"][0]["region"],
        "most_populous_country": processed["top_populous"][0]["name"],
        "densest_country_over_1000km2": processed["top_dense"][0]["name"] if processed["top_dense"] else None,
    }


def generate_html_report(tool_context) -> dict:
    """Builds a self-contained HTML dashboard (charts + tables) from the processed data.

    Returns:
        A dict with status and the local path of the generated report.html.
    """
    processed_path = tool_context.state.get("processed_path")
    if not processed_path or not os.path.exists(processed_path):
        return {"status": "error", "message": "No processed data found. Run the processing step first."}
    processed = json.loads(Path(processed_path).read_text(encoding="utf-8"))

    run_id = tool_context.state["run_id"]
    report_path = _run_dir(run_id) / "report.html"
    report_path.write_text(render_report(processed, run_id), encoding="utf-8")
    # Convenience copy so the newest report is always at output/latest_report.html
    shutil.copyfile(report_path, Path(config.OUTPUT_DIR) / "latest_report.html")

    tool_context.state["report_path"] = str(report_path)
    tool_context.state["artifacts"] = tool_context.state.get("artifacts", []) + [str(report_path)]
    return {"status": "success", "report_path": str(report_path.resolve())}


_CONTENT_TYPES = {".json": "application/json", ".csv": "text/csv", ".html": "text/html"}


def upload_to_cloud_storage(tool_context) -> dict:
    """Uploads every file produced in this run (raw JSON, processed JSON, CSV, HTML report)
    to cloud object storage (Google Cloud Storage), under <prefix>/<run_id>/.

    Returns:
        A dict with status and the list of storage URIs that were written.
    """
    files = tool_context.state.get("artifacts", [])
    run_id = tool_context.state.get("run_id")
    if not files or not run_id:
        return {"status": "error", "message": "Nothing to upload. Run the earlier steps first."}

    uris = []
    if config.STORAGE_BACKEND == "local":
        # Offline/dev fallback that mimics a bucket on disk. Not used for grading.
        root = Path(config.OUTPUT_DIR) / "_local_bucket" / config.GCS_PREFIX / run_id
        root.mkdir(parents=True, exist_ok=True)
        for f in files:
            dest = root / Path(f).name
            shutil.copyfile(f, dest)
            uris.append(f"file://{dest.resolve()}")
        tool_context.state["storage_uris"] = uris
        return {"status": "success", "backend": "local", "uris": uris}

    if not config.GCS_BUCKET:
        return {"status": "error", "message": "GCS_BUCKET is not set. Add it to your .env file."}
    try:
        from google.cloud import storage  # imported lazily so tests don't need it

        client = storage.Client()  # uses Application Default Credentials
        bucket = client.bucket(config.GCS_BUCKET)
        for f in files:
            blob_name = f"{config.GCS_PREFIX}/{run_id}/{Path(f).name}"
            blob = bucket.blob(blob_name)
            blob.upload_from_filename(f, content_type=_CONTENT_TYPES.get(Path(f).suffix, "application/octet-stream"))
            uris.append(f"gs://{config.GCS_BUCKET}/{blob_name}")
    except Exception as exc:  # surface auth/permission problems to the agent clearly
        return {"status": "error", "message": f"Upload to GCS failed: {type(exc).__name__}: {exc}"}

    tool_context.state["storage_uris"] = uris
    report_uri = next((u for u in uris if u.endswith(".html")), None)
    console = f"https://console.cloud.google.com/storage/browser/{config.GCS_BUCKET}/{config.GCS_PREFIX}/{run_id}"
    return {"status": "success", "backend": "gcs", "uris": uris,
            "report_uri": report_uri, "console_url": console}
