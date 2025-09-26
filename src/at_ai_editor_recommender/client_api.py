import httpx
import asyncio

API_URL = "http://localhost:8012/execute_workflow"

async def invoke_langgraph_agent(manuscript_number: str, coden: str):
    payload = {
        "manuscript_number": manuscript_number,
        "coden": coden
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(API_URL, json=payload)
        response.raise_for_status()
        return response.json()

async def main():
    result = await invoke_langgraph_agent("TEST_43", "JRN002")
    print("Langgraph agent response:", result)

if __name__ == "__main__":
    asyncio.run(main())