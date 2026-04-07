import asyncio
from fastapi import FastAPI, APIRouter
from httpx import AsyncClient, ASGITransport

app = FastAPI()
router = APIRouter()

@router.post("/api/incidents/{id:path}/claim")
async def api_claim_incident(id: str):
    return {"status": "locked", "incident_id": id}

app.include_router(router)

async def test_route():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Incident ID with slashes
        incident_id = "servei_cat_trans:104719:CLIENT_AUTHORIZATION_MISSING:08/22171472-6"
        url = f"http://test/api/incidents/{incident_id}/claim"
        
        print(f"Testing URL: {url}")
        response = await ac.post(url)
        
        if response.status_code == 200:
            print(f"SUCCESS: Received 200 OK")
            print(f"Response: {response.json()}")
            if response.json().get("incident_id") == incident_id:
                print("ID matched exactly.")
            else:
                print("ID MISMATCH.")
        else:
            print(f"FAILURE: Received {response.status_code}")
            print(f"Detail: {response.text}")

if __name__ == "__main__":
    asyncio.run(test_route())
