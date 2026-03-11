import re
import pandas as pd


def extraer_numero_direccion(direccion: str) -> int:
    if not direccion or pd.isna(direccion):
        return 0

    match = re.search(r"\d+", direccion)
    if match:
        return int(match.group())

    return 0


def provincia_por_cp(cp: str) -> str:
    """
    Devuelve la provincia española a partir del código postal.
    """
    if not cp or pd.isna(cp):
        return "NO CONSTA"

    cp = cp.strip()

    if not cp.isdigit() or len(cp) != 5:
        return "NO CONSTA"

    provincia_map = {
        "01": "ALAVA",
        "02": "ALBACETE",
        "03": "ALACANT",
        "04": "ALMERIA",
        "05": "AVILA",
        "06": "BADAJOZ",
        "07": "BALEARES",
        "08": "BARCELONA",
        "09": "BURGOS",
        "10": "CACERES",
        "11": "CADIZ",
        "12": "CASTELLO",
        "13": "CIUDAD REAL",
        "14": "CORDOBA",
        "15": "LA CORU?A",
        "16": "CUENCA",
        "17": "GIRONA",
        "18": "GRANADA",
        "19": "GUADALAJARA",
        "20": "GUIPUZCOA",
        "21": "HUELVA",
        "22": "HUESCA",
        "23": "JAEN",
        "24": "LEON",
        "25": "LLEIDA",
        "26": "LA RIOJA",
        "27": "LUGO",
        "28": "MADRID",
        "29": "MALAGA",
        "30": "MURCIA",
        "31": "NAVARRA",
        "32": "ORENSE",
        "33": "ASTURIAS",
        "34": "PALENCIA",
        "35": "LAS PALMAS",
        "36": "PONTEVEDRA",
        "37": "SALAMANCA",
        "38": "SANTA CRUZ TENERIFE",
        "39": "CANTABRIA",
        "40": "SEGOVIA",
        "41": "SEVILLA",
        "42": "SORIA",
        "43": "TARRAGONA",
        "44": "TERUEL",
        "45": "TOLEDO",
        "46": "VALENCIA",
        "47": "VALLADOLID",
        "48": "VIZCAYA",
        "49": "ZAMORA",
        "50": "ZARAGOZA",
        "51": "CEUTA",
        "52": "MELILLA",
    }

    prefijo = cp[:2]

    return provincia_map.get(prefijo, "NO CONSTA")


def normalizar_documento(doc: str) -> str:
    if doc is None:
        raise ValueError("Documento vacío")

    doc = doc.strip().upper()

    # eliminar espacios, guiones y puntos
    doc = re.sub(r"[.\-\s]", "", doc)

    return doc


def tipo_identificacion(doc: str) -> str:
    doc = doc.strip().upper()

    # NIF: 8 números + letra
    if re.fullmatch(r"\d{8}[A-Z]", doc):
        return "NIF"

    # NIE: X/Y/Z + 7 números + letra
    if re.fullmatch(r"[XYZ]\d{7}[A-Z]", doc):
        return "NIE"

    # CIF: letra inicial (tipo de entidad) + 7 números + letra o número final
    if re.fullmatch(r"[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-Z]", doc):
        return "CIF"

    # Pasaporte: alfanumérico, 5-12 caracteres (cubre formatos internacionales)
    if re.fullmatch(r"[A-Z0-9]{5,12}", doc):
        return "PASAPORTE"

    raise ValueError(f"Documento no válido: {doc}")


def get_matricula(*matriculas) -> str:
    """
    Devuelve la primera matrícula válida de la lista de argumentos.
    Acepta matrículas nacionales o extranjeras (1 a 12 caracteres alfanuméricos).
    Lanza ValueError si ninguna es válida.
    """
    for m in matriculas:
        if pd.notna(m) and m:
            m_limpia = m.strip().upper().replace(" ", "")  # eliminar espacios
            if re.fullmatch(r"[A-Z0-9]{1,15}", m_limpia):
                return m_limpia

    raise ValueError(f"Ninguna matrícula válida encontrada entre: {matriculas}")
