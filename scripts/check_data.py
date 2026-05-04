import sqlite3
con = sqlite3.connect('data_by_turbine/kelmarsh_data_by_turbine.db')
cur = con.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
print('Tables:', [r[0] for r in cur.fetchall()])
cur.execute('PRAGMA table_info(turbine_1)')
cols = [r[1] for r in cur.fetchall()]
print('Data columns:', cols)
cur.execute('SELECT MIN("Date and time"), MAX("Date and time") FROM turbine_1')
print('Range:', cur.fetchone())
con.close()

