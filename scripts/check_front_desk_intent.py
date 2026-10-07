"""Run the approved hotel scenario through the local Front Desk model."""

import asyncio

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agents.front_desk_agent.intent import intent_agent, validate_intent_output

APP_NAME = "front_desk_intent_check"
USER_ID = "local_check"
SCENARIO = "部屋のエアコンが壊れていて、19時からレストランも予約しています"


async def main() -> None:
    sessions = InMemorySessionService()
    session = await sessions.create_session(app_name=APP_NAME, user_id=USER_ID)
    runner = Runner(app_name=APP_NAME, agent=intent_agent, session_service=sessions)
    output = None
    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part.from_text(text=SCENARIO)],
        ),
    ):
        if event.is_final_response() and event.content:
            output = "".join(part.text or "" for part in event.content.parts or [])

    if not output:
        raise SystemExit("Front Deskから構造化された最終応答がありませんでした")
    result = validate_intent_output(output)
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
