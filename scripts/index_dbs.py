"""Add datetime indexes to all SQLite databases in data_by_turbine/."""
import sqlite3
import glob
import os

BASE = os.path.join(os.path.dirname(__file__), '..', 'data_by_turbine')

for db_path in glob.glob(os.path.join(BASE, '*.db')):
    print(f"Indexing {db_path}...")
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    for table in tables:
        cur.execute(f'PRAGMA table_info("{table}")')
        cols = [(r[1], r[2]) for r in cur.fetchall()]
        ts_col = None
        for key in ['Date and time', 'Timestamp start', 'Timestamp', 'Time', 'Date']:
            for c in cols:
                if key.lower() in c[0].lower():
                    ts_col = c[0]
                    break
            if ts_col:
                break
        if ts_col:
            idx_name = f'idx_{table[:30].replace(" ","_")}_ts'
            try:
                con.execute(f'CREATE INDEX IF NOT EXISTS "{idx_name}" ON "{table}" ("{ts_col}")')
                print(f'  [{table}] index on "{ts_col}" OK')
            except Exception as e:
                print(f'  [{table}] ERROR: {e}')
    con.commit()
    con.close()
print('Done.')

