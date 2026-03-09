"""Quick DB inspection script - run via kubectl exec"""
import asyncio, selectors, psycopg, json

async def check():
    uri = 'postgresql://mspubs_user:mspubs_user@mspubs-dev.cdeku8g0y28t.us-east-1.rds.amazonaws.com:5432/mspubs?options=-csearch_path%3Dmspubs'
    async with await psycopg.AsyncConnection.connect(uri) as conn:
        async with conn.cursor() as cur:
            # List all tables in mspubs schema
            await cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'mspubs' ORDER BY table_name"
            )
            rows = await cur.fetchall()
            print(f"=== {len(rows)} tables in mspubs schema ===")
            for r in rows:
                print(f"  {r[0]}")

sel = selectors.SelectSelector()
loop = asyncio.SelectorEventLoop(sel)
loop.run_until_complete(check())
loop.close()
