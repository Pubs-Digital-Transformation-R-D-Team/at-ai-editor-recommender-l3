"""Quick DB data check — run to see current memory state."""
import psycopg, json

uri = "postgresql://mspubs_user:mspubs_user@mspubs-dev.cdeku8g0y28t.us-east-1.rds.amazonaws.com:5432/mspubs?options=-csearch_path%3Dmspubs"

with psycopg.connect(uri) as conn:
    with conn.cursor() as cur:

        # ── Table counts ─────────────────────────────────────────────────────
        print("=" * 60)
        print("TABLE ROW COUNTS")
        print("=" * 60)
        for tbl in ["checkpoints", "checkpoint_blobs", "checkpoint_writes", "store"]:
            cur.execute(f"SELECT COUNT(*) FROM mspubs.{tbl}")
            print(f"  {tbl:<25}: {cur.fetchone()[0]}")

        # ── All threads ──────────────────────────────────────────────────────
        print()
        print("=" * 60)
        print("SESSION MEMORY — ALL WORKFLOW THREADS")
        print("=" * 60)
        cur.execute("""
            SELECT thread_id,
                   COUNT(*) AS chk_count,
                   MAX(metadata->>'step') AS last_step
            FROM mspubs.checkpoints
            GROUP BY thread_id
            ORDER BY MAX(checkpoint_id) DESC
        """)
        for r in cur.fetchall():
            print(f"  {r[0]:<35} checkpoints={r[1]}  last_step={r[2]}")

        # ── Store (long-term memory) full details ────────────────────────────
        print()
        print("=" * 60)
        print("LONG-TERM MEMORY — STORE (all entries)")
        print("=" * 60)
        cur.execute("""
            SELECT prefix, key, value
            FROM mspubs.store
            ORDER BY COALESCE(value->>'timestamp', '1970') DESC
        """)
        for row in cur.fetchall():
            prefix, key, val = row
            print(f"\n  [{prefix}]  key={key}")
            print(f"    editor_person_id : {val.get('editor_person_id', 'N/A')}")
            print(f"    editor_id (orcid): {val.get('editor_id', 'N/A')}")
            print(f"    runner_up        : {val.get('runner_up', 'N/A')}")
            print(f"    journal_id       : {val.get('journal_id', 'N/A')}")
            print(f"    timestamp        : {val.get('timestamp', 'N/A')}")
            print(f"    topics           : {str(val.get('topics', ''))[:100]}")
            print(f"    reasoning        : {str(val.get('reasoning', ''))[:120]}")

        # ── Checkpoint writes for new ja journal threads ─────────────────────
        print()
        print("=" * 60)
        print("CHECKPOINT WRITES FOR NEW JA THREADS")
        print("=" * 60)
        for tid in ["ja-ja-2024-01133b", "ja-ja-2026-00100"]:
            cur.execute("""
                SELECT channel, COUNT(*) AS writes
                FROM mspubs.checkpoint_writes
                WHERE thread_id = %s
                GROUP BY channel ORDER BY channel
            """, (tid,))
            rows = cur.fetchall()
            if rows:
                print(f"\n  thread: {tid}")
                for r in rows:
                    print(f"    {r[0]}: {r[1]} writes")
            else:
                print(f"\n  thread: {tid}  → no checkpoint_writes found")
