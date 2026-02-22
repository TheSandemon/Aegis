import asyncio
import json
import websockets

async def simulate_agent():
    uri = "ws://localhost:8080/ws"
    async with websockets.connect(uri) as websocket:
        print("Connected to Aegis WS")
        
        # Simulate agent starting on card #1
        start_msg = {
            "type": "agent_started",
            "agent_id": "coder",
            "pid": 1234,
            "card_id": 1,
            "color": "#f59e0b"
        }
        await websocket.send(json.dumps(start_msg))
        print("Sent agent_started")
        
        await asyncio.sleep(5)
        
        # Simulate agent stopping
        stop_msg = {
            "type": "agent_status_changed",
            "agent_id": "coder",
            "status": "completed",
            "exit_code": 0
        }
        await websocket.send(json.dumps(stop_msg))
        print("Sent agent_status_changed (completed)")

if __name__ == "__main__":
    asyncio.run(simulate_agent())
