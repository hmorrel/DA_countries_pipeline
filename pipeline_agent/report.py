"""Renders the processed data as a single self-contained HTML page (Chart.js from CDN)."""
from __future__ import annotations

import html
import json
from typing import Any


def _fmt_int(n: Any) -> str:
    return f"{int(n):,}" if n is not None else "–"


def _fmt_num(n: Any, digits: int = 1) -> str:
    return f"{float(n):,.{digits}f}" if n is not None else "–"


def _table(headers: list[str], rows: list[list[str]], numeric_cols: set[int]) -> str:
    head = "".join(f'<th class="{"num" if i in numeric_cols else ""}">{html.escape(h)}</th>'
                   for i, h in enumerate(headers))
    body = "".join(
        "<tr>" + "".join(f'<td class="{"num" if i in numeric_cols else ""}">{html.escape(str(c))}</td>'
                         for i, c in enumerate(row)) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def render_report(p: dict[str, Any], run_id: str) -> str:
    o = p["overall"]
    regions = p["by_region"]
    chart_data = {
        "regions": [r["region"] for r in regions],
        "population_m": [round(r["total_population"] / 1e6, 1) for r in regions],
        "density": [r["density_per_km2"] for r in regions],
        "countries": [r["countries"] for r in regions],
    }
    # Escape "</" so embedded JSON can never close the <script> tag
    data_json = json.dumps(chart_data).replace("</", "<\\/")

    region_table = _table(
        ["Region", "Countries", "Population", "Land area (km²)", "People / km²", "Median pop.",
         "Largest country"],
        [[r["region"], r["countries"], _fmt_int(r["total_population"]), _fmt_int(r["total_area_km2"]),
          _fmt_num(r["density_per_km2"]), _fmt_int(r["median_population"]), r["largest_country"]] for r in regions],
        numeric_cols={1, 2, 3, 4, 5},
    )
    sub_table = _table(
        ["Income group", "Region", "Countries", "Population", "People / km²", "Largest country"],
        [[s["subregion"], s["region"], s["countries"], _fmt_int(s["total_population"]),
          _fmt_num(s["density_per_km2"]), s["largest_country"]] for s in p["by_subregion"]],
        numeric_cols={2, 3, 4},
    )
    pop_table = _table(
        ["#", "Country", "Region", "Population"],
        [[i + 1, c["name"], c["region"], _fmt_int(c["population"])] for i, c in enumerate(p["top_populous"])],
        numeric_cols={0, 3},
    )
    dense_table = _table(
        ["#", "Country", "Region", "People / km²"],
        [[i + 1, c["name"], c["region"], _fmt_num(c["density_per_km2"])] for i, c in enumerate(p["top_dense"])],
        numeric_cols={0, 3},
    )
    params = p["parameters"]
    scope = "All regions" if params["region"].lower() == "all" else html.escape(params["region"])
    dropped = p["dropped"]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>World Countries Report – {html.escape(run_id)}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {{ --ink:#1d2433; --muted:#5b6475; --line:#e3e6ec; --bg:#f7f8fa; --accent:#2f6fde; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; color:var(--ink); background:var(--bg); }}
  main {{ max-width:1100px; margin:0 auto; padding:32px 20px 60px; }}
  h1 {{ margin:0 0 4px; font-size:28px; }}
  h2 {{ font-size:18px; margin:0 0 12px; }}
  .sub {{ color:var(--muted); margin:0 0 24px; font-size:14px; }}
  .kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:12px; margin-bottom:24px; }}
  .kpi, .card {{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:16px; }}
  .kpi .label {{ color:var(--muted); font-size:13px; }}
  .kpi .value {{ font-size:24px; font-weight:650; margin-top:4px; font-variant-numeric:tabular-nums; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:16px; margin-bottom:16px; }}
  .card {{ margin-bottom:16px; overflow-x:auto; }}
  canvas {{ max-height:300px; }}
  table {{ border-collapse:collapse; width:100%; font-size:14px; }}
  th, td {{ text-align:left; padding:7px 10px; border-bottom:1px solid var(--line); white-space:nowrap; }}
  th {{ color:var(--muted); font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:.03em; }}
  .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  footer {{ color:var(--muted); font-size:12px; margin-top:24px; }}
</style>
</head>
<body>
<main>
  <h1>World Countries: Population &amp; Density by Region</h1>
  <p class="sub">Scope: {scope} · min population {params["min_population"]:,} · run {html.escape(run_id)} ·
     generated {html.escape(p["generated_at"])} · source: World Bank Open Data API</p>

  <section class="kpis">
    <div class="kpi"><div class="label">Countries analyzed</div><div class="value">{_fmt_int(p["kept_records"])}</div></div>
    <div class="kpi"><div class="label">Total population</div><div class="value">{_fmt_num(o["total_population"] / 1e9, 2)} B</div></div>
    <div class="kpi"><div class="label">Avg. people / km²</div><div class="value">{_fmt_num(o["density_per_km2"])}</div></div>
    <div class="kpi"><div class="label">Most populous</div><div class="value">{html.escape(p["top_populous"][0]["name"])}</div></div>
    <div class="kpi"><div class="label">Records dropped</div><div class="value">{sum(dropped.values())}</div></div>
  </section>

  <section class="grid">
    <div class="card"><h2>Population by region (millions)</h2><canvas id="popChart"></canvas></div>
    <div class="card"><h2>People per km² by region</h2><canvas id="densityChart"></canvas></div>
  </section>

  <section class="card"><h2>Region summary</h2>{region_table}</section>
  <section class="grid">
    <div class="card"><h2>Most populous countries</h2>{pop_table}</div>
    <div class="card"><h2>Most densely populated (area ≥ 1,000 km²)</h2>{dense_table}</div>
  </section>
  <section class="card"><h2>Region × income group</h2>{sub_table}</section>

  <footer>Data quality: {dropped["no_population_or_area"]} records without population/area removed,
    {dropped["duplicate"]} duplicates removed, {dropped["filtered_out"]} excluded by filters.
    Population and land area are each country's most recent World Bank value. Density is total population ÷ total land area of the group (population-weighted).</footer>
</main>
<script>
  const D = {data_json};
  const base = {{ responsive:true, plugins:{{ legend:{{ display:false }} }},
                 scales:{{ y:{{ beginAtZero:true, grid:{{ color:"#eef0f4" }} }}, x:{{ grid:{{ display:false }} }} }} }};
  if (window.Chart) {{
    new Chart(document.getElementById("popChart"), {{ type:"bar",
      data:{{ labels:D.regions, datasets:[{{ data:D.population_m, backgroundColor:"#2f6fde", borderRadius:4 }}] }}, options:base }});
    new Chart(document.getElementById("densityChart"), {{ type:"bar",
      data:{{ labels:D.regions, datasets:[{{ data:D.density, backgroundColor:"#16a394", borderRadius:4 }}] }}, options:base }});
  }}
</script>
</body>
</html>
"""
