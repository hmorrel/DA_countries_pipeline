"""Central configuration, read from environment variables (see .env.example)."""
import os

try:  # python-dotenv is optional at import time so unit tests run without it
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

# LLM used by every ADK agent
MODEL = os.getenv("ADK_MODEL", "gemini-3.8-flash")

# World Bank Open Data API (public, no API key needed)
WB_BASE_URL = "https://api.worldbank.org/v2"
WB_POPULATION = "SP.POP.TOTL"   # total population
WB_LAND_AREA = "AG.LND.TOTL.K2"  # land area, km²

# Storage: "gcs" (default, used for the assignment) or "local" (offline dev only)
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "gcs").lower()
GCS_BUCKET = os.getenv("GCS_BUCKET", "")
GCS_PREFIX = os.getenv("GCS_PREFIX", "countries-pipeline")

# Local working directory for run artifacts
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")
