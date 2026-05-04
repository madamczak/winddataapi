import sqlite3
con = sqlite3.connect('data_by_turbine/kelmarsh_data_by_turbine.db')
cur = con.cursor()

# Check the exact known good slot from the example JSON
cur.execute('''
    SELECT "Date and time", "Rotor speed (RPM)", "Generator RPM (RPM)",
           "Wind speed (m/s)", "Power (kW)"
    FROM turbine_2
    WHERE "Date and time" LIKE "2016-06-09 01:%"
    ORDER BY "Date and time"
''')
print("turbine_2 on 2016-06-09 hour 01:")
for row in cur.fetchall():
    print(row)

# Also check what range rotor speed takes
cur.execute('SELECT MIN("Rotor speed (RPM)"), MAX("Rotor speed (RPM)"), AVG("Rotor speed (RPM)") FROM turbine_2 WHERE "Rotor speed (RPM)" IS NOT NULL')
print("\nRotor speed (RPM) min/max/avg in DB:", cur.fetchone())

cur.execute('SELECT MIN("Generator RPM (RPM)"), MAX("Generator RPM (RPM)") FROM turbine_2 WHERE "Generator RPM (RPM)" IS NOT NULL')
print("Generator RPM min/max in DB:", cur.fetchone())
con.close()

