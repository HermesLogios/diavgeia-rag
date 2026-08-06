import requests
import json

BASE = "https://diavgeia.gov.gr/luminapi/opendata"

params = {
    "q": "*",
    "size": 3,
}

print(f"Καλώ: {BASE}/search.json")
response = requests.get(f"{BASE}/search.json", params=params, timeout=30)

print(f"Κωδικός απάντησης: {response.status_code}")
print(f"Τύπος περιεχομένου: {response.headers.get('content-type')}")
print("-" * 60)

if response.status_code == 200:
    data = response.json()
    print("Κλειδιά πρώτου επιπέδου:", list(data.keys()))
    print("-" * 60)
    print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])
else:
    print("Δεν πήγε καλά. Οι πρώτοι 1000 χαρακτήρες της απάντησης:")
    print(response.text[:1000])