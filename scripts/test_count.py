import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from dashboard_api import app

client = TestClient(app)

response = client.get("/count")
print("Status Code:", response.status_code)
print("Response JSON:")
print(response.json())
