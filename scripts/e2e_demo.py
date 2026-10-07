"""Run the local Front Desk scenario against four real A2A services and Ollama."""

import asyncio
import json
import os
from uuid import uuid4

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.types import Message, Part, SendMessageRequest, TaskState
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agents.front_desk_agent.agent import root_agent

APP_NAME = "front_desk_agent"
USER_ID = "local_guest"
SCENARIO = "部屋のエアコンが壊れていて、19時からレストランも予約しています"
FAILURE_SCENARIO = "エアコンの故障で修理可否と代替部屋を確認してください"
RESTAURANT_URL = os.getenv("RESTAURANT_AGENT_BASE_URL", "http://localhost:8003")
PENDING_PROPOSAL_KEY = "front_desk_pending_restaurant_proposal_id"


async def _send_a2a_text(url: str, message_text: str) -> tuple[list[str], TaskState | None]:
    async with httpx.AsyncClient(timeout=30) as http:
        client = await ClientFactory(
            ClientConfig(httpx_client=http)
        ).create_from_url(url)
        request = SendMessageRequest(
            message=Message(
                message_id=str(uuid4()),
                role="ROLE_USER",
                parts=[Part(text=message_text)],
            )
        )
        answers: list[str] = []
        final_state = None
        async for event in client.send_message(request):
            payload = event.WhichOneof("payload")
            if payload == "status_update":
                status = event.status_update.status
                final_state = status.state
                if status.message:
                    answers.extend(
                        part.text for part in status.message.parts if part.text
                    )
            elif payload == "artifact_update":
                answers.extend(
                    part.text
                    for part in event.artifact_update.artifact.parts
                    if part.text
                )
        await client.close()
        return answers, final_state


async def _reservation_time() -> str:
    answers, state = await _send_a2a_text(
        RESTAURANT_URL, json.dumps({"action": "get_status"})
    )
    if state != TaskState.TASK_STATE_COMPLETED:
        raise RuntimeError("Restaurant Agentの予約状態確認が完了しませんでした")
    for answer in reversed(answers):
        try:
            result = json.loads(answer)
        except json.JSONDecodeError:
            continue
        if isinstance(result, dict) and isinstance(
            result.get("reservation_time"), str
        ):
            return result["reservation_time"]
    raise RuntimeError("Restaurant Agentから予約時刻を確認できませんでした")


async def _run_turn(
    runner: Runner, session_id: str, message: str
) -> str:
    final_text = ""
    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session_id,
        new_message=types.Content(
            role="user", parts=[types.Part.from_text(text=message)]
        ),
    ):
        if event.author == root_agent.name and event.content:
            final_text = "\n".join(
                part.text for part in event.content.parts if part.text
            )
    if not final_text:
        raise RuntimeError("Front Deskの最終回答を受け取れませんでした")
    return final_text


def _require(text: str, *expected: str) -> None:
    missing = [part for part in expected if part not in text]
    if missing:
        raise RuntimeError(f"E2E応答に必要な内容がありません: {', '.join(missing)}\n{text}")


async def main() -> None:
    initial_time = await _reservation_time()
    if initial_time != "19:00":
        raise RuntimeError(
            "E2E開始時の予約時刻が19:00ではありません。"
            "Restaurant Agentを再起動してインメモリ状態を初期化してください。"
        )

    sessions = InMemorySessionService()
    session = await sessions.create_session(app_name=APP_NAME, user_id=USER_ID)
    runner = Runner(app_name=APP_NAME, agent=root_agent, session_service=sessions)

    print("[1/3] 代表シナリオを実行します")
    first_answer = await _run_turn(runner, session.id, SCENARIO)
    print(first_answer)
    _require(
        first_answer,
        "Maintenance Agent",
        "Housekeeping Agent",
        "Restaurant Agent",
        "20時への変更案",
    )
    if await _reservation_time() != "19:00":
        raise RuntimeError("Guest承認前に予約時刻が変更されました")
    current_session = await sessions.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session.id
    )
    if not current_session or not current_session.state.get(PENDING_PROPOSAL_KEY):
        raise RuntimeError("Front Deskの会話に変更案IDが保持されていません")

    print("[2/3] 同じ会話で変更案を承認します")
    approval_answer = await _run_turn(
        runner, session.id, "はい、20時への変更を承認します。"
    )
    print(approval_answer)
    _require(approval_answer, "予約を20時に変更しました")
    if await _reservation_time() != "20:00":
        raise RuntimeError("承認後の予約時刻が20:00になっていません")

    print("[3/3] Maintenance Agentを停止した場合の部分回答を確認します")
    original_url = os.environ.get("MAINTENANCE_AGENT_BASE_URL")
    os.environ["MAINTENANCE_AGENT_BASE_URL"] = "http://127.0.0.1:8799"
    try:
        failure_answer = await _run_turn(runner, session.id, FAILURE_SCENARIO)
    finally:
        if original_url is None:
            os.environ.pop("MAINTENANCE_AGENT_BASE_URL", None)
        else:
            os.environ["MAINTENANCE_AGENT_BASE_URL"] = original_url
    print(failure_answer)
    _require(
        failure_answer,
        "Maintenance Agent [失敗]",
        "Housekeeping Agent [完了]",
        "代替のお部屋をご用意できます",
    )
    print("E2Eシナリオがすべて成功しました。")


if __name__ == "__main__":
    asyncio.run(main())
