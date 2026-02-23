import os
import time
import requests
import sys

# Windows compatibility for stdout
sys.stdout.reconfigure(encoding='utf-8')

api_url = os.environ.get("AEGIS_API_URL", "http://localhost:8080/api")
card_id = os.environ.get("AEGIS_CARD_ID")
agent_name = os.environ.get("AEGIS_INSTANCE_NAME", os.environ.get("AEGIS_AGENT_ID", "Unknown Agent"))
goal = os.environ.get("AEGIS_CONFIG_GOALS", "No specific goal provided.")

if not card_id or card_id == "0":
    print(f"[{agent_name}] Booting up in idle mode (no card assigned).")
    print(f"[{agent_name}] My Goal: {goal}")
    print(f"[{agent_name}] Waiting for assignments...")
    time.sleep(5)
    exit(0)

print(f"[{agent_name}] Booting up...")
print(f"[{agent_name}] My Goal: {goal}")
print(f"[{agent_name}] Fetching details for Card #{card_id}...")

try:
    card_req = requests.get(f"{api_url}/cards/{card_id}")
    card_req.raise_for_status()
    card = card_req.json()
    print(f"[{agent_name}] Card Title: {card.get('title')}")
    print(f"[{agent_name}] Card Description: {card.get('description')}")
except Exception as e:
    print(f"[{agent_name}] Failed to fetch card: {e}")
    exit(1)

print(f"[{agent_name}] Analyzing task requirements...")
time.sleep(2)
print(f"[{agent_name}] Executing work according to my goal...")
time.sleep(3)
print(f"[{agent_name}] Generating artifacts...")
# Create a dummy artifact file
with open("output.txt", "w", encoding="utf-8") as f:
    f.write(f"Task completed by {agent_name}\nGoal followed: {goal}\n")
time.sleep(2)
print(f"[{agent_name}] Work complete. Validating results...")
time.sleep(1)

print(f"[{agent_name}] Moving card #{card_id} to Review...")
try:
    update_req = requests.patch(f"{api_url}/cards/{card_id}", json={"column": "Review"}, headers={"X-Aegis-Agent": "true"})
    update_req.raise_for_status()
    print(f"[{agent_name}] Card successfully moved to Review.")
except Exception as e:
    print(f"[{agent_name}] Error moving card: {e}")
    exit(1)

print(f"[{agent_name}] Shutting down.")
exit(0)
