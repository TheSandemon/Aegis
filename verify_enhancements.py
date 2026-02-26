import httpx
import asyncio
import json

async def test_a2a_status():
    url = "http://localhost:8080/api/a2a/messages"
    payload = {
        "sender": "test-agent",
        "type": "task.status",
        "payload": {
            "title": "🧠 THINKING",
            "description": "Consulting LLM for architecture design",
        },
        "timestamp": "2026-02-26T12:00:00Z"
    }
    
    async with httpx.AsyncClient() as client:
        print("Sending A2A status update...")
        resp = await client.post(url, json=payload)
        print(f"Response: {resp.status_code}")
        print(resp.json())

async def test_broker_submit():
    url = "http://localhost:8080/api/broker/submit"
    payload = {
        "card_id": 1,
        "agent_name": "test-agent",
        "prompt": "Analyze the codebase and suggest security improvements."
    }
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        print("Submitting prompt to broker...")
        resp = await client.post(url, json=payload)
        print(f"Response: {resp.status_code}")
        print(resp.json())

if __name__ == "__main__":
    asyncio.run(test_a2a_status())
    asyncio.run(test_broker_submit())
