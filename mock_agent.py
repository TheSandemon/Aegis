import time
import sys

print("Mock agent started...")
sys.stdout.flush()
time.sleep(1)

for i in range(5):
    print(f"Working on step {i+1}/5...")
    sys.stdout.flush()
    time.sleep(1)

print("Mock agent completed successfully!")
sys.stdout.flush()
