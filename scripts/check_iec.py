import sqlite3
con = sqlite3.connect('data_by_turbine/kelmarsh_status_by_turbine.db')
cur = con.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print('Tables:', tables[:6])
cur.execute(f'PRAGMA table_info("{tables[0]}")')
cols = [r[1] for r in cur.fetchall()]
print('Columns:', cols)
cur.execute(f'SELECT DISTINCT "IEC category" FROM "{tables[0]}" WHERE "IEC category" IS NOT NULL ORDER BY "IEC category"')
print('IEC categories:', [r[0] for r in cur.fetchall()])
con.close()

