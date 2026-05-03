import sqlite3
import glob
import os

base = os.path.join(os.path.dirname(__file__), '..', 'data_by_turbine')
base = os.path.abspath(base)
print('Inspecting:', base)
for p in glob.glob(os.path.join(base, '*.db')):
    print('\nFILE:', p)
    try:
        con = sqlite3.connect(p)
        cur = con.cursor()
        cur.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view')")
        items = cur.fetchall()
        print('Tables/Views:', items)
        for name, typ in items:
            print('\nSchema for', name)
            try:
                cur.execute(f"PRAGMA table_info({name})")
                for row in cur.fetchall():
                    print(row)
            except Exception as e:
                print('  (could not get columns)', e)
        con.close()
    except Exception as e:
        print('  ERROR opening DB:', e)

