import json
import unittest
from uuid import uuid4

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.types import Message, Part, SendMessageRequest, TaskState

from agents.housekeeping_agent.agent import a2a_app as housekeeping_app
from agents.maintenance_agent.agent import a2a_app as maintenance_app
from agents.restaurant_agent.agent import a2a_app as restaurant_app

DEPARTMENT_CASES = (
    {
        "app": maintenance_app,
        "name": "maintenance_agent",
        "port": 8001,
        "request": "部屋のエアコンが壊れており、修理をお願いします",
        "expected_text": "夕食後",
    },
    {
        "app": housekeeping_app,
        "name": "housekeeping_agent",
        "port": 8002,
        "request": "エアコン故障のため代替部屋を確認してください",
        "expected_text": "ご用意できます",
    },
    {
        "app": restaurant_app,
        "name": "restaurant_agent",
        "port": 8003,
        "request": json.dumps(
            {"action": "propose_change", "requested_time": "20:00"}
        ),
        "expected_text": '"status": "proposed"',
    },
)


class DepartmentA2AContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_agent_cards_and_a2a_tasks_match_the_contract(self) -> None:
        for case in DEPARTMENT_CASES:
            with self.subTest(agent=case["name"]):
                app = case["app"]
                async with app.router.lifespan_context(app):
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=app),
                        base_url=f"http://localhost:{case['port']}",
                    ) as http:
                        card_response = await http.get(
                            "/.well-known/agent-card.json"
                        )
                        self.assertEqual(card_response.status_code, 200)
                        card = card_response.json()
                        self.assertEqual(card["name"], case["name"])
                        self.assertTrue(card["description"])
                        self.assertTrue(card["skills"])
                        interface = card["supportedInterfaces"][0]
                        self.assertEqual(
                            interface["url"],
                            f"http://localhost:{case['port']}",
                        )
                        self.assertEqual(interface["protocolBinding"], "JSONRPC")
                        self.assertEqual(interface["protocolVersion"], "1.0")

                        client = await ClientFactory(
                            ClientConfig(httpx_client=http)
                        ).create_from_url(f"http://localhost:{case['port']}")
                        request = SendMessageRequest(
                            message=Message(
                                message_id=str(uuid4()),
                                role="ROLE_USER",
                                parts=[Part(text=case["request"])],
                            )
                        )
                        answers: list[str] = []
                        states = []
                        async for event in client.send_message(request):
                            payload = event.WhichOneof("payload")
                            if payload == "status_update":
                                status = event.status_update.status
                                states.append(status.state)
                                if status.message:
                                    answers.extend(
                                        part.text
                                        for part in status.message.parts
                                        if part.text
                                    )
                            elif payload == "artifact_update":
                                answers.extend(
                                    part.text
                                    for part in event.artifact_update.artifact.parts
                                    if part.text
                                )
                        await client.close()

                        self.assertTrue(states)
                        self.assertEqual(
                            states[-1], TaskState.TASK_STATE_COMPLETED
                        )
                        self.assertTrue(answers)
                        self.assertTrue(
                            any(case["expected_text"] in answer for answer in answers),
                            answers,
                        )


if __name__ == "__main__":
    unittest.main()
