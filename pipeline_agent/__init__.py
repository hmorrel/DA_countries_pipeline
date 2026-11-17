import importlib.util

# Lets `adk web` / `adk run` find root_agent. Skipped when google-adk isn't
# installed, so the unit tests for the plain-Python tools can still run.
if importlib.util.find_spec("google.adk") is not None:
    from . import agent  # noqa: F401
