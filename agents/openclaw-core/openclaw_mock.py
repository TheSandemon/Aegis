import time
import sys
import os

print(f"Mock Agent '{os.environ.get('AEGIS_AGENT_ID', 'unknown')}' started.", flush=True)
print("Awaiting tasks in background...", flush=True)

try:
    while True:
        time.sleep(10)
        print("Polling... no new tasks found.", flush=True)
except KeyboardInterrupt:
    print("Agent shutting down.", flush=True)
    sys.exit(0)
