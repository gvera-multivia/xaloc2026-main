"""
Datos geográficos de referencia para validación en España.
"""

PROVINCIAS_ESPANA: set[str] = {
    "ALAVA", "ALBACETE", "ALICANTE", "ALMERIA", "ASTURIAS", "AVILA", "BADAJOZ", 
    "BARCELONA", "BURGOS", "CACERES", "CADIZ", "CANTABRIA", "CASTELLON", "CIUDAD REAL", 
    "CORDOBA", "A CORUÑA", "CUENCA", "GIRONA", "GRANADA", "GUADALAJARA", "GUIPUZCOA", 
    "HUELVA", "HUESCA", "ILLES BALEARS", "JAEN", "LEON", "LLEIDA", "LUGO", "MADRID", 
    "MALAGA", "MURCIA", "NAVARRA", "OURENSE", "PALENCIA", "LAS PALMAS", "PONTEVEDRA", 
    "LA RIOJA", "SALAMANCA", "SANTA CRUZ DE TENERIFE", "SEGOVIA", "SEVILLA", "SORIA", 
    "TARRAGONA", "TERUEL", "TOLEDO", "VALENCIA", "VALLADOLID", "VIZCAYA", "ZAMORA", "ZARAGOZA", "CEUTA", "MELILLA"
}

# Lista simplificada para validación de ejemplo. 
# En un caso real, esto podría cargarse desde un JSON o base de datos.
CIUDADES_POR_PROVINCIA: dict[str, set[str]] = {
    "GIRONA": {"GIRONA", "FIGUERES", "BLANES", "LLORET DE MAR", "SALT", "OLOT", "PALAFRUGELL", "SANT FELIU DE GUIXOLS", "ROSES", "BANYOLES"},
    "MADRID": {"MADRID", "MOSTOLES", "ALCALA DE HENARES", "FUENLABRADA", "LEGANES", "GETAFE", "ALCORCON", "TORREJON DE ARDOZ", "PARLA", "ALCOBENDAS"},
    "TARRAGONA": {"TARRAGONA", "REUS", "TORTOSA", "EL VENDRELL", "CAMBRILS", "VALLS", "SALOU", "CALAFELL", "VILA-SECA", "AMPOSTA"},
}

def is_valid_province(province: str) -> bool:
    return province.upper().strip() in PROVINCIAS_ESPANA

def is_valid_city(city: str, province: str) -> bool:
    province = province.upper().strip()
    city = city.upper().strip()
    if province in CIUDADES_POR_PROVINCIA:
        return city in CIUDADES_POR_PROVINCIA[province]
    # Si no tenemos la provincia mapeada, no podemos invalidar la ciudad (fallback a True)
    return True
