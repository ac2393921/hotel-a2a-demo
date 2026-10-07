"""Guest UIの公開HTTP操作をADKの評価入力へ接続する。"""
import json
import os
from datetime import date, timedelta
from urllib.parse import urlparse

import httpx
from google.adk.agents import BaseAgent
from google.adk.events import Event, EventActions
from google.genai import types


class GuestUIEvaluationAgent(BaseAgent):
    async def _run_async_impl(self, ctx):
        command = json.loads("".join(part.text or "" for part in ctx.user_content.parts))
        if set(command) - {"actor", "action", "text"}:
            raise ValueError("評価入力に未定義のフィールドがあります")
        actor = command.get("actor", "guest")
        if not isinstance(actor, str) or not actor or len(actor) > 40:
            raise ValueError("評価ゲスト名が不正です")
        if not isinstance(command.get("text", ""), str):
            raise ValueError("評価発話は文字列が必要です")
        action = command.get("action", "send")
        if action not in {"send", "approve", "reject"}:
            raise ValueError("評価操作はsend/approve/rejectのみです")
        base_url = os.environ.get("EVAL_GUEST_UI_URL", "http://127.0.0.1:8800")
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("評価先はローカルのGuest UIだけを指定してください")
        baseline = date.fromisoformat(os.environ["EVAL_BASE_DATE"])
        text = command.get("text", "").replace("{tomorrow}", (baseline + timedelta(days=1)).isoformat())
        text = text.replace("{race_day}", (baseline + timedelta(days=2)).isoformat())
        # 予約storeやFront Deskの承認資格には触れず、ブラウザーと同じ入口を使う。
        actors = dict(ctx.session.state.get("eval_actors", {}))
        async with httpx.AsyncClient(base_url=base_url, timeout=240) as client:
            if actor not in actors:
                created = await client.post("/api/sessions")
                created.raise_for_status()
                actors[actor] = {"session_id": created.json()["session_id"], "proposal_id": None}
            guest = dict(actors[actor])
            payload = {"text": text}
            if action != "send":
                if not guest["proposal_id"]:
                    raise ValueError("承認・拒否の対象提案がありません")
                payload.update(decision=action, proposal_id=guest["proposal_id"])
            response = await client.post(f"/api/sessions/{guest['session_id']}/messages", json=payload)
            response.raise_for_status()
            if "approval_token" in response.text:
                raise ValueError("Guest UI応答に承認資格が露出しています")
            result = response.json()
        pending = result.get("pending_proposal")
        guest["proposal_id"] = pending.get("proposal_id") if pending else None
        actors[actor] = guest
        # 生のHTTPレスポンスや資格は評価イベントへ保存しない。
        output = {"reply": result["reply"], "proposal": pending.get("text") if pending else None,
                  "delegated": any(task.get("agent_id") == "restaurant_agent" and task.get("task_id")
                                   for task in result.get("tasks", []))}
        print(json.dumps(output, ensure_ascii=False), flush=True)
        yield Event(author=self.name, invocation_id=ctx.invocation_id,
                    content=types.Content(role="model", parts=[types.Part.from_text(text=json.dumps(output, ensure_ascii=False))]),
                    actions=EventActions(state_delta={"eval_actors": actors}))


root_agent = GuestUIEvaluationAgent(name="guest_ui_eval")
