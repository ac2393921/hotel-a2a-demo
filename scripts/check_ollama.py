"""Verify that ADK can send a prompt to the configured Ollama model."""

import asyncio
import os

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types


async def main() -> None:
    load_dotenv()
    model_name = os.getenv("FRONT_DESK_MODEL", "ollama_chat/qwen3.5:latest")
    api_base = os.getenv("OLLAMA_API_BASE", "http://localhost:11434")
    os.environ["OLLAMA_API_BASE"] = api_base

    agent = Agent(
        name="ollama_connection_check",
        model=LiteLlm(model=model_name),
        instruction="Reply with only `OK` in Japanese. Do not explain or show reasoning.",
        generate_content_config=types.GenerateContentConfig(max_output_tokens=32),
        timeout=120,
    )
    app_name = "hotel_a2a_demo_connection_check"
    user_id = "local_check"
    session_service = InMemorySessionService()
    session = await session_service.create_session(app_name=app_name, user_id=user_id)
    runner = Runner(
        app_name=app_name,
        agent=agent,
        session_service=session_service,
    )

    response_received = False
    try:
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session.id,
            new_message=types.Content(
                role="user", parts=[types.Part(text="接続確認です。一言で返答してください。")]
            ),
        ):
            if event.is_final_response() and event.content:
                response = "".join(
                    part.text or "" for part in event.content.parts or []
                ).strip()
                if response:
                    response_received = True
        if not response_received:
            raise RuntimeError("モデルから最終応答がありませんでした")
        print(f"Ollama接続成功 ({model_name})")
    except Exception as error:
        raise SystemExit(
            f"Ollama接続に失敗しました ({api_base}, {model_name}): {error}\n"
            "Ollamaが起動していることと、`ollama list`にモデルがあることを確認してください。"
        ) from error


if __name__ == "__main__":
    asyncio.run(main())
