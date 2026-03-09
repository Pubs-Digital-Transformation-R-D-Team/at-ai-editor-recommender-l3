"""Find JA manuscripts - fast version"""
import asyncio, selectors, psycopg

async def check():
    uri = 'postgresql://mspubs_user:mspubs_user@mspubs-dev.cdeku8g0y28t.us-east-1.rds.amazonaws.com:5432/mspubs?options=-csearch_path%3Dmspubs'
    async with await psycopg.AsyncConnection.connect(uri) as conn:
        async with conn.cursor() as cur:
            # Quick: just grab some JA manuscripts 
            await cur.execute(
                "SELECT manuscript_number, journal_id, manuscript_status, editor_id "
                "FROM manuscript_submitted "
                "WHERE journal_id = 'ja' AND manuscript_status IS NOT NULL "
                "LIMIT 10"
            )
            rows = await cur.fetchall()
            print("=== JA manuscripts ===")
            for r in rows:
                print(f"  ms={r[0]}  journal={r[1]}  status={r[2]}  editor={r[3]}")

            # Also try ci, oc, jm journals
            for jid in ['ci', 'oc', 'jm']:
                await cur.execute(
                    "SELECT manuscript_number, journal_id, manuscript_status "
                    "FROM manuscript_submitted "
                    "WHERE journal_id = %s LIMIT 3", (jid,)
                )
                rows = await cur.fetchall()
                if rows:
                    print(f"\n=== {jid.upper()} manuscripts ===")
                    for r in rows:
                        print(f"  ms={r[0]}  journal={r[1]}  status={r[2]}")

sel = selectors.SelectSelector()
loop = asyncio.SelectorEventLoop(sel)
loop.run_until_complete(check())
loop.close()
