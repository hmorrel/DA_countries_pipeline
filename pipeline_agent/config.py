"""Central configuration, read from environment variables (see .env.example)."""
import os

try:  # python-dotenv is optional at import time so unit tests run without it
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

# LLM used by every ADK agent
MODEL = os.getenv("ADK_MODEL", "gemini-2.5-flash")

# REST Countries API (public, no API key needed).
# The /all endpoint requires an explicit field list (max 10 fields).
API_URL = "https://restcountries.com/v3.1/all"
API_FIELDS = [
    "name", "cca3", "region", "subregion", "population",
    "area", "landlocked", "unMember", "languages", "currencies",
]
VALID_REGIONS = {"Africa", "Americas", "Asia", "Europe", "Oceania", "Antarctic"}

# Storage: "gcs" (default, used for the assignment) or "local" (offline dev only)
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "gcs").lower()
GCS_BUCKET = os.getenv("GCS_BUCKET", "")
GCS_PREFIX = os.getenv("GCS_PREFIX", "countries-pipeline")

# Local working directory for run artifacts
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")
