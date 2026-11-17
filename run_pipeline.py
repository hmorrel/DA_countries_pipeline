"""Run the agentic pipeline from the command line.

Usage:
    python run_pipeline.py
    python run_pipeline.py "Analyze only Europe, skipping countries under 1 million people"
"""
import asyncio
import sys

from google.adk.runners import InMemoryRunner
from google.genai import types

from pipeline_agent.agent import root_agent

APP_NAME = "countries_pipeline"
USER_ID = "cli_user"
DEFAULT_REQUEST = "Run the full country data pipeline for all regions."


async def main(request: str) -> int:
    runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
    session = await runner.session_service.create_session(app_name=APP_NAME, user_id=USER_ID)
    message = types.Content(role="user", parts=[types.Part(text=request)])

    print(f"\n>>> Request: {request}\n")
    async for event in runner.run_async(user_id=USER_ID, session_id=session.id, new_message=message):
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            if part.function_call:
                args = dict(part.function_call.args or {})
                print(f"[{event.author}] -> calling {part.function_call.name}({args})")
            elif part.function_response:
                status = (part.function_response.response or {}).get("status")
                print(f"[{event.author}] <- {part.function_response.name} returned status={status}")
            elif part.text and part.text.strip():
                print(f"[{event.author}] {part.text.strip()}\n")

    final = await runner.session_service.get_session(app_name=APP_NAME, user_id=USER_ID, session_id=session.id)
    uris = final.state.get("storage_uris")
    if not uris:
        print("Pipeline did not finish uploading to cloud storage. See messages above.")
        return 1
    print("Artifacts stored:\n  " + "\n  ".join(uris))
    print(f"Open the dashboard locally: {final.state.get('report_path')}")
    return 0


async def main_with_retry(request: str, attempts: int = 4) -> int:
    """Retry the whole run when Gemini is temporarily overloaded (503) or rate-limited (429)."""
    from google.genai import errors

    for attempt in range(1, attempts + 1):
        try:
            return await main(request)
        except (errors.ServerError, errors.ClientError) as exc:
            code = getattr(exc, "code", None)
            if code not in (429, 500, 503) or attempt == attempts:
                raise
            wait = 15 * attempt
            print(f"\nGemini is busy (HTTP {code}). Retrying in {wait}s (attempt {attempt + 1}/{attempts})...")
            await asyncio.sleep(wait)
    return 1


if __name__ == "__main__":
    request = " ".join(sys.argv[1:]) or DEFAULT_REQUEST
    sys.exit(asyncio.run(main_with_retry(request)))
