"""Script de debug para verificar qué datos se están obteniendo de SQL Server"""
import os
import sys
from dotenv import load_dotenv

try:
    import pyodbc
except Exception:
    print("ERROR: pyodbc no instalado")
    sys.exit(1)

load_dotenv()

# Query simplificada
QUERY = """
SELECT 
    rs.idRecurso,
    rs.Expedient,
    rs.cif,
    rs.Empresa,
    rs.SujetoRecurso,
    c.nif AS cliente_nif,
    c.Nombre AS cliente_nombre,
    c.Apellido1 AS cliente_apellido1,
    c.Apellido2 AS cliente_apellido2
FROM Recursos.RecursosExp rs
INNER JOIN clientes c ON rs.numclient = c.numerocliente
INNER JOIN expedientes e ON rs.idExp = e.idexpediente
WHERE rs.idExp = ?
"""

# Construir connection string
driver = (os.getenv("SQLSERVER_DRIVER") or "SQL Server").strip()
server = (os.getenv("SQLSERVER_SERVER") or "").strip()
database = (os.getenv("SQLSERVER_DATABASE") or "").strip()
username = (os.getenv("SQLSERVER_USERNAME") or "").strip()
password = (os.getenv("SQLSERVER_PASSWORD") or "").strip()
trusted = (os.getenv("SQLSERVER_TRUSTED_CONNECTION") or "").strip().lower() in {"1", "true", "yes", "y"}

if not (server and database):
    print("ERROR: Faltan SQLSERVER_SERVER y SQLSERVER_DATABASE")
    sys.exit(1)

parts = [
    f"DRIVER={{{driver}}}",
    f"SERVER={server}",
    f"DATABASE={database}",
]

if trusted:
    parts.append("Trusted_Connection=yes")
else:
    if not (username and password):
        print("ERROR: Faltan credenciales")
        sys.exit(1)
    parts.append(f"UID={username}")
    parts.append(f"PWD={password}")

connection_string = ";".join(parts)

# ID a verificar (el de RUBIOL BCN SL)
id_exp = 848781

print(f"\n{'='*80}")
print(f"DEBUG: Verificando datos de SQL Server para idExp = {id_exp}")
print(f"{'='*80}\n")

conn = pyodbc.connect(connection_string)
try:
    cursor = conn.cursor()
    cursor.execute(QUERY, (id_exp,))
    columns = [c[0] for c in cursor.description]
    
    row = cursor.fetchone()
    if not row:
        print(f"ERROR: No se encontró registro con idExp = {id_exp}")
        sys.exit(1)
    
    row_dict = dict(zip(columns, row))
    
    print("Datos obtenidos de SQL Server:")
    print("-" * 80)
    for key, value in row_dict.items():
        value_repr = f"'{value}'" if value else "NULL/EMPTY"
        print(f"  {key:20} = {value_repr}")
    
    print("\n" + "="*80)
    print("Análisis de tipo de persona:")
    print("="*80)
    
    cif_raw = row_dict.get("cif")
    empresa_raw = row_dict.get("Empresa")
    
    cif_clean = (cif_raw or "").strip()
    empresa_clean = (empresa_raw or "").strip()
    
    print(f"  cif (raw):     {repr(cif_raw)}")
    print(f"  cif (clean):   {repr(cif_clean)}")
    print(f"  Empresa (raw): {repr(empresa_raw)}")
    print(f"  Empresa (clean): {repr(empresa_clean)}")
    
    if cif_clean or empresa_clean:
        tipo = "JURIDICA"
    else:
        tipo = "FISICA"
    
    print(f"\n  >>> TIPO DETECTADO: {tipo}")
    
    if tipo == "FISICA":
        print("\n  ⚠️  PROBLEMA: Se detectó como FISICA pero debería ser JURIDICA")
        print("  ⚠️  Verifica que los campos 'cif' o 'Empresa' tengan datos en SQL Server")
    else:
        print("\n  ✓ OK: Se detectó correctamente como JURIDICA")
    
    print("\n" + "="*80 + "\n")

finally:
    conn.close()
