import json
import requests
import os

key = "AIzaSyC1SVQa6xRT0vfUKWZWvakVvchQUfJ-ogI"
model = "gemini-flash-latest"

res = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}", 
    json={"system_instruction": {"parts": [{"text": "Hello"}]}, "contents": [{"parts":[{"text": "World"}]}], "generationConfig": {"responseMimeType": "application/json"}})

print(res.status_code)
print(res.text)

try:
    content = res.json()["candidates"][0]["content"]["parts"][0]["text"]
    print("Success:", content)
except Exception as e:
    print("Exception:", type(e), e)
