import requests

print("1. Testing login with admin/admin123...")
try:
    res = requests.get("http://localhost:8000/login", auth=("admin", "admin123"), timeout=10)
    print("Login admin status:", res.status_code)
    print("Login admin body:", res.json())
except Exception as e:
    print("Error login admin:", e)

print("\n2. Testing login with Hamza/marketing123...")
try:
    res = requests.get("http://localhost:8000/login", auth=("Hamza", "marketing123"), timeout=10)
    print("Login Hamza status:", res.status_code)
    print("Login Hamza body:", res.json())
except Exception as e:
    print("Error login Hamza:", e)

print("\n3. Testing chat query (RAG) for Hamza on marketing report...")
try:
    res = requests.post(
        "http://localhost:8000/chat",
        auth=("Hamza", "marketing123"),
        json={"question": "Summarize the marketing highlights from 2024"},
        timeout=15
    )
    print("Chat status:", res.status_code)
    print("Chat answer:", res.json().get("answer"))
    print("Chat sources:", res.json().get("sources"))
except Exception as e:
    print("Error chat:", e)

print("\n4. Testing chat query (RAG) for Hamza on restricted HR data...")
try:
    res = requests.post(
        "http://localhost:8000/chat",
        auth=("Hamza", "marketing123"),
        json={"question": "What is the HR salary or headcount details?"},
        timeout=15
    )
    print("Chat restricted status:", res.status_code)
    print("Chat restricted answer:", res.json().get("answer"))
except Exception as e:
    print("Error chat restricted:", e)
