import requests
import json

API_KEY = "sk-81df44eefee74062838c70ebb7012610"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

data = {
    "model": "deepseek-chat",
    "messages": [{"role": "user", "content": "Расскажи про машинное обучение"}],
    #"max_tokens": 500,
    #"temperature": 0.3,
}

response = requests.post(
    "https://api.deepseek.com/v1/chat/completions",
    headers=headers, json=data, timeout=60
)

print(response.json())
