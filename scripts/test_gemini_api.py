import asyncio
import os
import aiohttp
import json

async def test_gemini():
    key = os.environ.get("GEMINI_API_KEY")
    print("Testing Gemini key len:", len(key) if key else 0)
    if not key:
        print("No GEMINI_API_KEY found")
        return
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}"
    payload = {
        "contents": [{
            "parts": [{"text": "Hello, reply with JSON: {\"status\": \"ok\", \"agent\": \"Antigravity Quant AI\"}"}]
        }],
        "generationConfig": {
            "response_mime_type": "application/json"
        }
    }
    async with aiohttp.ClientSession() as sess:
        async with sess.post(url, json=payload) as resp:
            print("Status:", resp.status)
            txt = await resp.text()
            print("Response:", txt[:300])

if __name__ == "__main__":
    asyncio.run(test_gemini())
