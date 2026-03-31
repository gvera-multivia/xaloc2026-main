from core.sqlserver_utils import build_sqlserver_connection_string
import pyodbc 

ids = [
    104400, 104388, 104386, 104364, 104340, 104287, 104117, 103842, 103841, 104236, 104214,
    104136, 104129, 104127, 104109, 104108, 104105, 104103, 104102, 104089, 104083, 104072
]

conn_str = build_sqlserver_connection_string()
conn = pyodbc.connect(conn_str)
cursor = conn.cursor()

placeholders = ','.join('?' for _ in ids)
query = f"""
    SELECT r.idRecurso, o.Organisme, r.Estado
    FROM Recursos.RecursosExp r
    LEFT JOIN Recursos.ConfigOrganismes o ON r.idOrganisme = o.idOrganisme
    WHERE r.idRecurso IN ({placeholders})
"""

cursor.execute(query, ids)
rows = cursor.fetchall()

print('ID | ESTADO | ORGANISMO')
for row in rows:
    print(f'{row[0]} | {row[2]} | {row[1]}')
