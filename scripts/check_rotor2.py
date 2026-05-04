import sqlite3
con = sqlite3.connect('data_by_turbine/kelmarsh_data_by_turbine.db')
cur = con.cursor()

for t in ['turbine_1', 'turbine_2']:
    cur.execute(f'SELECT MIN("Rotor speed (RPM)"), MAX("Rotor speed (RPM)"), '
                f'MIN("Generator RPM (RPM)"), MAX("Generator RPM (RPM)") '
                f'FROM {t} WHERE "Rotor speed (RPM)" IS NOT NULL')
    rotor_min, rotor_max, gen_min, gen_max = cur.fetchone()
    print(f"{t}: Rotor speed range [{float(rotor_min):.2f} – {float(rotor_max):.2f}]  "
          f"Generator RPM range [{float(gen_min):.2f} – {float(gen_max):.2f}]")

# Check a known turbine_1 row used by the crawler
cur.execute('''
    SELECT "Date and time", "Rotor speed (RPM)", "Generator RPM (RPM)", "Power (kW)"
    FROM turbine_1
    WHERE "Date and time" LIKE "2020-01-08 03:%"
''')
print("\nturbine_1 2020-01-08 h03:")
for r in cur.fetchall(): print(r)

con.close()

