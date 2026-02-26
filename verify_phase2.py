import requests
import json
import time
import os

BASE_URL = "http://localhost:8080/api"

def test_phase2():
    print("--- Verifying Phase 2 Enhancements ---")
    
    # 1. Create a test card
    print("\n1. Creating test card...")
    res = requests.post(f"{BASE_URL}/cards", json={
        "title": "Phase 2 Test Card",
        "description": "Testing activity persistence",
        "column": "In Progress"
    })
    card = res.json()
    card_id = card['id']
    print(f"Created card ID: {card_id}")

    # 2. Simulate A2A Status Update
    print("\n2. Sending A2A status update...")
    a2a_payload = {
        "sender": "test-agent",
        "type": "task.status",
        "payload": {
            "title": "Thinking deeply about code...",
            "description": "",
            "metadata": {
                "card_id": card_id,
                "instance_id": "test-instance-123"
            }
        }
    }
    res = requests.post(f"http://localhost:8080/api/a2a/messages", json=a2a_payload)
    print(f"A2A response: {res.json()}")

    # 3. Verify persistence in DB
    print("\n3. Verifying database persistence...")
    res = requests.get(f"{BASE_URL}/cards/{card_id}")
    updated_card = res.json()
    activity = updated_card.get('activity')
    print(f"Card activity in DB: '{activity}'")
    if activity == "Thinking deeply about code...":
        print("✅ Activity persistence verified!")
    else:
        print(f"❌ Persistence failed. Got: {activity}")

    # 4. Verify Prompt Broker (using dummy instances.json)
    print("\n4. Verifying Prompt Broker with fake instance...")
    # We need to simulate the instances.json file
    if not os.path.exists("aegis_data"):
        os.makedirs("aegis_data")
    
    instances = [
        {
            "instance_id": "test-instance-123",
            "instance_name": "Test-Worker",
            "env_vars": {
                "OPENROUTER_API_KEY": "sk-fake-key-for-testing"
            },
            "model": "anthropic/claude-3-haiku"
        }
    ]
    with open("aegis_data/instances.json", "w") as f:
        json.dump(instances, f)
    
    # Assign the card to the test worker
    requests.patch(f"{BASE_URL}/cards/{card_id}", json={"assignee": "Test-Worker"})

    print("Submitting prompt to broker (will try to hit OpenRouter)...")
    broker_payload = {
        "card_id": card_id,
        "agent_name": "Test-Worker",
        "prompt": "Hello from Aegis test script!"
    }
    # This might take a moment due to broker rate limiting (1 PPM default)
    res = requests.post(f"{BASE_URL}/broker/submit", json=broker_payload)
    broker_res = res.json()
    print(f"Broker response: {broker_res}")
    
    # We expect a 401/403 Error from OpenRouter since the key is fake, but we check if it tried.
    if broker_res.get("status") == "error" and "LLM Error" in broker_res.get("message", ""):
        print("✅ Broker integration verified (it reached the OpenRouter call stage)!")
    elif broker_res.get("status") == "success":
        print("✅ Broker integration verified (it succeeded? maybe you have a real key?)")
    else:
        print(f"❌ Broker verification failed. Got: {broker_res}")

if __name__ == "__main__":
    test_phase2()
