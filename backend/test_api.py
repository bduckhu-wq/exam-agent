import requests

print("Testing Exam Agent API...")

try:
    response = requests.get('http://localhost:8000/')
    print('Status code:', response.status_code)
    print('Response:', response.json())
    print("✅ API is working!")
except Exception as e:
    print('Error:', e)
    print("❌ API is not working")
