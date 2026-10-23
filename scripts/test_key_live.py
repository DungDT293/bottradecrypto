import requests
import json

key = 'AIzaSyARn5gkO4Rjubb3pYbYk1tQGIe6p2VhbeA'
url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}'
payload = {
    "contents": [{"parts": [{"text": "Hello, are you online? Respond with JSON {\"status\": \"ok\"}"}]}],
    "generationConfig": {"response_mime_type": "application/json"}
}

try:
    r = requests.post(url, json=payload, timeout=10)
    print("Gemini 1.5 Flash HTTP Status:", r.status_code)
    print("Response Body:", r.text)
except Exception as e:
    print("Request failed:", e)
