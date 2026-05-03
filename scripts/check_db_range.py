import sqlite3, sys
db = 'data_by_turbine/kelmarsh_data_by_turbine.db'
con = sqlite3.connect(db)
cur = con.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
sys.stdout.write(f"Tables: {tables}\n")
sys.stdout.flush()
if 'turbine_2' in tables:
    cur.execute('SELECT * FROM turbine_2 LIMIT 1')
    cols = [d[0] for d in cur.description]
    sys.stdout.write(f"Cols: {cols}\n")
    sys.stdout.flush()
    dt_col = cols[0]
    cur.execute(f'SELECT MIN("{dt_col}"), MAX("{dt_col}") FROM turbine_2')
    sys.stdout.write(f"Range: {cur.fetchone()}\n")
    sys.stdout.flush()
con.close()

