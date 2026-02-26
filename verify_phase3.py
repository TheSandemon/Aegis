import requests
import time

BASE_URL = "http://localhost:8080/api"

def test_context_api():
    print("--- Verifying Phase 3: Context Optimization ---")
    
    # 1. Create a dependency card
    print("\n1. Creating dependency card...")
    res1 = requests.post(f"{BASE_URL}/cards", json={
        "title": "Database Schema (Dep)",
        "description": "Here is the schema details...",
        "column": "Done"
    })
    dep_card = res1.json()
    dep_id = dep_card['id']
    
    # 2. Create an unrelated noise card
    print("\n2. Creating unrelated noise card...")
    res2 = requests.post(f"{BASE_URL}/cards", json={
        "title": "Fix Typo in Header",
        "description": "Very long description that should be ignored by the LLM later.",
        "column": "Inbox"
    })
    
    # 3. Create the focus card that tags the dependency
    print("\n3. Creating focus card with @ tag...")
    res3 = requests.post(f"{BASE_URL}/cards", json={
        "title": "Implement Analytics API",
        "description": f"Need help with this. Make sure to check @{dep_id} for the table structure.",
        "column": "In Progress"
    })
    focus_card = res3.json()
    focus_id = focus_card['id']

    # 4. Fetch the optimized context
    print(f"\n4. Fetching smart context for Card #{focus_id}...")
    ctx_res = requests.get(f"{BASE_URL}/cards/{focus_id}/context")
    ctx = ctx_res.json()
    
    # 5. Verify the bundle structure
    focus = ctx.get("focus_card", {})
    related = ctx.get("related_context", [])
    directory = ctx.get("board_directory", [])
    
    print("\n--- Verification Results ---")
    if focus.get('id') == focus_id:
        print("✅ Focus Card: Correctly isolated.")
    else:
        print(f"❌ Focus Card: FAILED (Expected {focus_id}, got {focus.get('id')})")
        
    if len(related) == 1 and related[0].get('id') == dep_id:
        print(f"✅ Related Context: Successfully bundled tagged card @{dep_id}.")
    else:
        print(f"❌ Related Context: FAILED. Expected to bundle @{dep_id}")
        print(related)
        
    noise_in_related = any(c.get('title') == "Fix Typo in Header" for c in related)
    if not noise_in_related:
        print("✅ Noise Filter: Unrelated cards were excluded from dense context.")
    else:
        print("❌ Noise Filter: FAILED. Unrelated card snuck into dense context.")
        
    print(f"\nDEBUG: Directory items: {[c.get('title') for c in directory]}")
    
    if any(c.get('title') == "Fix Typo in Header" for c in directory):
        # Ensure that NONE of the items in directory have a 'description'
        if not any('description' in c for c in directory):
            print("✅ Board Directory: Unrelated cards exist as skinny references (no descriptions).")
        else:
            print("❌ Board Directory: FAILED. Some directory items contain full descriptions.")
    else:
        print("❌ Board Directory: FAILED. Unrelated noise card is missing from the directory entirely.")

if __name__ == "__main__":
    test_context_api()
