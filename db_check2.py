"""Query manuscript_submitted for recent records"""
import asyncio, selectors, psycopg

async def check():
    uri = 'postgresql://mspubs_user:mspubs_user@mspubs-dev.cdeku8g0y28t.us-east-1.rds.amazonaws.com:5432/mspubs?options=-csearch_path%3Dmspubs'
    async with await psycopg.AsyncConnection.connect(uri) as conn:
        async with conn.cursor() as cur:
            # Get columns first
            await cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'mspubs' AND table_name = 'manuscript_submitted' "
                "ORDER BY ordinal_position LIMIT 20"
            )
            cols = await cur.fetchall()
            print("=== manuscript_submitted columns ===")
            for c in cols:
                print(f"  {c[0]}")
            
            # Count
            await cur.execute("SELECT count(*) FROM manuscript_submitted")
            count = (await cur.fetchone())[0]
            print(f"\n=== Total rows: {count} ===")
            
            # Get some recent journal_id + manuscript_number combos
            await cur.execute(
                "SELECT manuscript_number, journal_id FROM manuscript_submitted "
                "ORDER BY manuscript_number DESC LIMIT 10"
            )
            rows = await cur.fetchall()
            print("\n=== Recent manuscripts ===")
            for r in rows:
                print(f"  ms={r[0]}  journal={r[1]}")

sel = selectors.SelectSelector()
loop = asyncio.SelectorEventLoop(sel)
loop.run_until_complete(check())
loop.close()
