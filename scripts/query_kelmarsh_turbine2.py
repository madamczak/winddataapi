import json
from app import db

site = 'kelmarsh_data_by_turbine'
table = 'turbine_2'
start = '2018-05-30 20:00:00'
end = '2018-05-30 22:00:00'

try:
    rows = db.query_rows(site, table, start=start, end=end, limit=10000)
    out = {'site': site, 'table': table, 'start': start, 'end': end, 'count': len(rows), 'rows': rows}
    print(json.dumps(out, indent=2, default=str))
except Exception as e:
    print(json.dumps({'error': str(e)}))

