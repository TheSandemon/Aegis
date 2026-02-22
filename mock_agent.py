import time
import sys
import os

print("Mock agent started...")
print(f"DEBUG: Running for Card ID: {os.getenv('AEGIS_CARD_ID')}")
print(f"DEBUG: Task Title: {os.getenv('AEGIS_CARD_TITLE')}")
sys.stdout.flush()
time.sleep(1)

for i in range(10): # Longer for testing stop button
    print(f"Working on step {i+1}/10...")
    sys.stdout.flush()
    time.sleep(1)

print("Mock agent completed successfully!")
sys.stdout.flush()
