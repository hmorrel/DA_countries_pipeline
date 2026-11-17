"""ADK agent definitions.

Architecture (multi-agent, orchestrated by ADK):

    countries_pipeline (SequentialAgent)          <- root_agent
      ├── ingestion_agent      -> fetch_country_data
      ├── processing_agent     -> transform_country_data(region, min_population)
      ├── visualization_agent  -> generate_html_report
      ├── storage_agent        -> upload_to_cloud_storage
      └── reporter_agent       (no tools; summarizes the run for the user)

Each LlmAgent owns exactly one responsibility and one tool. The processing agent
reads the user's request and decides the filter parameters itself (e.g. "only
Europe" or "skip countries under 1 million people"). Agents share file paths
through ADK session state, and each agent saves its reply under an output_key
so later agents can read earlier results.

`adk web` / `adk run` discover `root_agent` in this module automatically.
"""
from google.adk.agents import LlmAgent, SequentialAgent

from . import config
from .tools import (
    fetch_country_data,
    generate_html_report,
    transform_country_data,
    upload_to_cloud_storage,
)

ingestion_agent = LlmAgent(
    name="ingestion_agent",
    model=config.MODEL,
    description="Pulls raw country data from the public World Bank Open Data API.",
    instruction=(
        "You are the data ingestion step of a data pipeline. "
        "Call the fetch_country_data tool exactly once. "
        "If it returns status 'error', report the error message and stop. "
        "Otherwise reply with one sentence giving the run_id and number of records fetched."
    ),
    tools=[fetch_country_data],
    output_key="ingestion_result",
)

processing_agent = LlmAgent(
    name="processing_agent",
    model=config.MODEL,
    description="Cleans, filters and aggregates the raw country data.",
    instruction=(
        "You are the processing step of a data pipeline. The ingestion step reported: "
        "{ingestion_result?}\n\n"
        "If ingestion failed, say so and do not call any tool.\n"
        "Otherwise, read the user's original request and choose filter parameters:\n"
        "- region: 'all' unless the user named a region. World Bank regions are: East Asia & Pacific, Europe & Central Asia, Latin America & Caribbean, Middle East & North Africa, North America, South Asia, Sub-Saharan Africa. A short name like 'Europe' or 'Africa' also works.\n"
        "- min_population: 0 unless the user asked to exclude small countries "
        "(e.g. 'over 1 million' -> 1000000).\n"
        "Call transform_country_data once with those parameters. If it returns an error saying no countries matched, "
        "retry once using one of the valid regions listed in the error, or 'all'. "
        "Reply with 2-3 sentences: the parameters you chose and the headline findings."
    ),
    tools=[transform_country_data],
    output_key="processing_result",
)

visualization_agent = LlmAgent(
    name="visualization_agent",
    model=config.MODEL,
    description="Builds the HTML dashboard from the processed data.",
    instruction=(
        "You are the visualization step of a data pipeline. The processing step reported: "
        "{processing_result?}\n\n"
        "If processing failed, say so and do not call any tool. "
        "Otherwise call generate_html_report once and reply with the report path."
    ),
    tools=[generate_html_report],
    output_key="visualization_result",
)

storage_agent = LlmAgent(
    name="storage_agent",
    model=config.MODEL,
    description="Uploads raw data, processed data and the report to cloud object storage.",
    instruction=(
        "You are the storage step of a data pipeline. Earlier steps reported:\n"
        "- processing: {processing_result?}\n- visualization: {visualization_result?}\n\n"
        "If an earlier step failed, say so and do not call any tool. "
        "Otherwise call upload_to_cloud_storage once and list every URI it returns. "
        "If it returns an error, repeat the error message so the user can fix their setup."
    ),
    tools=[upload_to_cloud_storage],
    output_key="storage_result",
)

reporter_agent = LlmAgent(
    name="reporter_agent",
    model=config.MODEL,
    description="Summarizes the completed pipeline run for the user.",
    instruction=(
        "Write a short final summary of this pipeline run for the user, using only these step results:\n"
        "- ingestion: {ingestion_result?}\n- processing: {processing_result?}\n"
        "- visualization: {visualization_result?}\n- storage: {storage_result?}\n\n"
        "Use a bulleted list: status of each step, 2-3 key insights from the data, "
        "where the HTML report is (local path and cloud URI). "
        "If any step failed, clearly say which one and why. Do not invent numbers."
    ),
    output_key="final_summary",
)

root_agent = SequentialAgent(
    name="countries_pipeline",
    description="End-to-end agentic data pipeline: ingest -> process -> visualize -> store -> report.",
    sub_agents=[ingestion_agent, processing_agent, visualization_agent, storage_agent, reporter_agent],
)
