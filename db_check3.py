"""Find recent JA manuscripts with editors"""
import asyncio, selectors, psycopg

async def check():
    uri = 'postgresql://mspubs_user:mspubs_user@mspubs-dev.cdeku8g0y28t.us-east-1.rds.amazonaws.com:5432/mspubs?options=-csearch_path%3Dmspubs'
    async with await psycopg.AsyncConnection.connect(uri) as conn:
        async with conn.cursor() as cur:
            # Recent JA manuscripts
            await cur.execute(
                "SELECT manuscript_number, journal_id, manuscript_title, "
                "manuscript_status, editor_id, assigned_editor_person_id "
                "FROM manuscript_submitted "
                "WHERE journal_id = 'ja' "
                "ORDER BY manuscript_number DESC LIMIT 10"
            )
            rows = await cur.fetchall()
            print("=== Recent JA (JACS) manuscripts ===")
            for r in rows:
                ms, jid, title, status, eid, pid = r
                title_short = (title[:60] + '...') if title and len(title) > 60 else title
                print(f"  {ms} | status={status} | editor={eid} | person={pid}")
                print(f"    title: {title_short}")
            
            # Also check other journals
            await cur.execute(
                "SELECT journal_id, count(*) FROM manuscript_submitted "
                "GROUP BY journal_id ORDER BY count(*) DESC LIMIT 15"
            )
            rows = await cur.fetchall()
            print("\n=== Top 15 journals by manuscript count ===")
            for jid, cnt in rows:
                print(f"  {jid:10s} {cnt:>8} manuscripts")

sel = selectors.SelectSelector()
loop = asyncio.SelectorEventLoop(sel)
loop.run_until_complete(check())
loop.close()
