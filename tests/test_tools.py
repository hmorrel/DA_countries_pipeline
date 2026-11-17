"""Unit tests for the pipeline tools. No network, LLM or cloud account needed.

Run with:  python -m pytest -q
"""
import json
from types import SimpleNamespace

import pytest

from pipeline_agent import config, tools

SAMPLE = [
    {"name": {"common": "Germany"}, "cca3": "DEU", "region": "Europe", "subregion": "Western Europe",
     "population": 83_000_000, "area": 357_114, "landlocked": False, "unMember": True,
     "languages": {"deu": "German"}, "currencies": {"EUR": {}}},
    {"name": {"common": "Austria"}, "cca3": "AUT", "region": "Europe", "subregion": "Central Europe",
     "population": 9_000_000, "area": 83_871, "landlocked": True, "unMember": True,
     "languages": {"deu": "German"}, "currencies": {"EUR": {}}},
    {"name": {"common": "India"}, "cca3": "IND", "region": "Asia", "subregion": "Southern Asia",
     "population": 1_400_000_000, "area": 3_287_590, "landlocked": False, "unMember": True,
     "languages": {"eng": "English", "hin": "Hindi"}, "currencies": {"INR": {}}},
    {"name": {"common": "Bouvet Island"}, "cca3": "BVT", "region": "Antarctic", "subregion": None,
     "population": 0, "area": 49, "landlocked": False, "unMember": False},
    {"name": {"common": "Germany"}, "cca3": "DEU", "region": "Europe", "subregion": "Western Europe",
     "population": 83_000_000, "area": 357_114},  # duplicate
]


def test_transform_cleans_and_aggregates():
    out = tools.transform_records(SAMPLE)
    assert out["kept_records"] == 3
    assert out["dropped"]["no_population_or_area"] == 1
    assert out["dropped"]["duplicate"] == 1
    europe = next(r for r in out["by_region"] if r["region"] == "Europe")
    assert europe["countries"] == 2
    assert europe["total_population"] == 92_000_000
    assert europe["landlocked_countries"] == 1
    assert europe["distinct_languages"] == 1
    # weighted density = total pop / total area
    assert europe["density_per_km2"] == round(92_000_000 / (357_114 + 83_871), 2)
    assert out["top_populous"][0]["name"] == "India"


def test_region_and_population_filters():
    out = tools.transform_records(SAMPLE, region="europe", min_population=10_000_000)
    assert [c["name"] for c in out["countries"]] == ["Germany"]


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(config, "STORAGE_BACKEND", "local")
    context = SimpleNamespace(state={"run_id": "test"})
    raw = tmp_path / "test" / "raw_countries.json"
    raw.parent.mkdir()
    raw.write_text(json.dumps(SAMPLE))
    context.state.update(raw_path=str(raw), artifacts=[str(raw)])
    return context


def test_tool_chain_end_to_end(ctx):
    assert tools.transform_country_data("all", 0, ctx)["status"] == "success"
    assert tools.generate_html_report(ctx)["status"] == "success"
    html = open(ctx.state["report_path"], encoding="utf-8").read()
    assert "<canvas" in html and "India" in html
    result = tools.upload_to_cloud_storage(ctx)
    assert result["status"] == "success"
    assert len(result["uris"]) == 4  # raw, processed json, csv, report


def test_invalid_region_returns_error(ctx):
    assert tools.transform_country_data("Atlantis", 0, ctx)["status"] == "error"


def test_steps_out_of_order_return_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", str(tmp_path))
    empty = SimpleNamespace(state={})
    assert tools.transform_country_data("all", 0, empty)["status"] == "error"
    assert tools.generate_html_report(empty)["status"] == "error"
    assert tools.upload_to_cloud_storage(empty)["status"] == "error"


def test_fetch_parses_world_bank_responses(tmp_path, monkeypatch):
    """Mock the three World Bank calls and check they are merged correctly."""
    monkeypatch.setattr(config, "OUTPUT_DIR", str(tmp_path))
    meta = {"page": 1, "pages": 1}
    responses = {
        "/country?": [meta, [
            {"id": "DEU", "name": "Germany", "region": {"value": "Europe & Central Asia"},
             "incomeLevel": {"value": "High income"}, "capitalCity": "Berlin"},
            {"id": "WLD", "name": "World", "region": {"value": "Aggregates"}},
        ]],
        "SP.POP.TOTL": [meta, [{"countryiso3code": "DEU", "value": 83_000_000},
                               {"countryiso3code": "WLD", "value": 8_000_000_000}]],
        "AG.LND.TOTL.K2": [meta, [{"countryiso3code": "DEU", "value": 349_390}]],
    }
    monkeypatch.setattr(tools, "_get_json",
                        lambda url: next(v for k, v in responses.items() if k in url))
    context = SimpleNamespace(state={})
    result = tools.fetch_country_data(context)
    assert result["status"] == "success" and result["records_fetched"] == 1
    raw = json.loads(open(context.state["raw_path"]).read())
    assert raw[0]["population"] == 83_000_000 and raw[0]["area"] == 349_390
    out = tools.transform_records(raw, region="Europe")
    assert out["kept_records"] == 1 and out["by_subregion"][0]["subregion"] == "High income"
