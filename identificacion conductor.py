import pyodbc

def obtener_datos_expediente(id_recurso):
    # 1. Configuración de la conexión (ajusta tus credenciales)
    conn_str = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        "SERVER=tu_servidor;"
        "DATABASE=tu_base_de_datos;"
        "UID=usuario;"
        "PWD=contraseña"
    )

    # 2. SQL con la lógica de selección de tablas (TExp 2 vs TExp 3)
    query = """
    SELECT 
        R.TExp,
        CASE WHEN R.TExp = 2 THEN R.ConducNom ELSE D.ConducNom END AS ConducNom,
        CASE WHEN R.TExp = 2 THEN R.Conducdni ELSE D.Conducdni END AS Conducdni,
        CASE WHEN R.TExp = 2 THEN R.ConducAdr ELSE D.ConducAdr END AS ConducAdr,
        CASE WHEN R.TExp = 2 THEN R.ConducCodpost ELSE D.ConducCodpost END AS ConducCodpost,
        CASE WHEN R.TExp = 2 THEN R.ConducPobl ELSE D.ConducPobl END AS ConducPobl,
        CASE WHEN R.TExp = 2 THEN R.Conducprov ELSE NULL END AS ConducProvOriginal
    FROM recursos.recursosExp R
    LEFT JOIN DadesIdentif D ON R.idExp = D.idExp
    WHERE R.idRecurso = ?
    """

    try:
        with pyodbc.connect(conn_str) as conn:
            cursor = conn.cursor()
            cursor.execute(query, (id_recurso,))
            row = cursor.fetchone()

            if not row:
                return "No se encontró el recurso."

            # Mapeo de columnas del cursor
            data = {
                "Nom": row.ConducNom,
                "DNI": row.Conducdni,
                "Adr": row.ConducAdr,
                "CP": str(row.ConducCodpost).strip().zfill(5) if row.ConducCodpost else None,
                "Pobl": row.ConducPobl,
                "ProvOriginal": row.ConducProvOriginal
            }

            # 3. Prevalidación y Inferencia
            provincia_inferida = inferir_provincia(data["CP"])
            
            # Si el TExp era 2 y ya tenía provincia, la respetamos a menos que sea nula
            final_prov = data["ProvOriginal"] if data["ProvOriginal"] else provincia_inferida

            return {
                "ConducNom": data["Nom"],
                "Conducdni": data["DNI"],
                "ConducAdr": data["Adr"],
                "ConducCodpost": data["CP"],
                "ConducPobl": data["Pobl"],
                "ConducProv": final_prov
            }

    except Exception as e:
        return f"Error de conexión: {e}"

def inferir_provincia(cp):
    """Lógica completa de prevalidación e inferencia"""
    if not cp or len(cp) != 5 or not cp.isdigit():
        return "CP No Válido"
    
    p2 = cp[:2]
    p3 = cp[:3]
    
    if int(p2) < 1 or int(p2) > 52:
        return "Fuera de Rango (ES)"

    # Diccionario de provincias (2 dígitos)
    provincias = {
        "01": "Álava", "02": "Albacete", "03": "Alicante", "04": "Almería", "05": "Ávila",
        "06": "Badajoz", "08": "Barcelona", "09": "Burgos", "10": "Cáceres", "11": "Cádiz",
        "12": "Castellón", "13": "Ciudad Real", "14": "Córdoba", "15": "A Coruña", "16": "Cuenca",
        "17": "Girona", "18": "Granada", "19": "Guadalajara", "20": "Guipúzcoa", "21": "Huelva",
        "22": "Huesca", "23": "Jaén", "24": "León", "25": "Lleida", "26": "La Rioja",
        "27": "Lugo", "28": "Madrid", "29": "Málaga", "30": "Murcia", "31": "Navarra",
        "32": "Ourense", "33": "Asturias", "34": "Palencia", "36": "Pontevedra", "37": "Salamanca",
        "39": "Cantabria", "40": "Segovia", "41": "Sevilla", "42": "Soria", "43": "Tarragona",
        "44": "Teruel", "45": "Toledo", "46": "Valencia", "47": "Valladolid", "48": "Vizcaya",
        "49": "Zamora", "50": "Zaragoza", "51": "Ceuta", "52": "Melilla"
    }

    # Excepciones Islas (3 dígitos)
    if p2 == "07":
        if "070" <= p3 <= "076": return "Mallorca"
        if p3 == "077": return "Menorca"
        return "Ibiza/Formentera"
    if p2 == "35":
        if "350" <= p3 <= "354": return "Gran Canaria"
        if p3 == "355": return "Lanzarote"
        return "Fuerteventura"
    if p2 == "38":
        if "380" <= p3 <= "386": return "Tenerife"
        if p3 == "387": return "La Palma"
        if p3 == "388": return "La Gomera"
        return "El Hierro"

    return provincias.get(p2, "Desconocida")

# --- PRUEBA DEL SCRIPT ---
resultado = obtener_datos_expediente(88991)
print(resultado)