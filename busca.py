import os
import re
import subprocess

# 1. Configuracion de carpeta de red (UNC nativa de Windows)
# Puedes sobreescribirla con variable de entorno NETWORK_BASE_PATH
DEFAULT_BASE_PATH = r"\\SERVER-DOC\dptos multivia\4 DPTO -  JURIDICO\CARPETAS VIRTUALES\RECURSOS AUTOMATICOS\TRAMITADOS"
BASE_PATH = os.getenv("NETWORK_BASE_PATH", DEFAULT_BASE_PATH)


def _build_path_candidates(base_path: str) -> list[str]:
    """
    Genera variantes seguras de la ruta para intentar conexion en Windows.
    """
    value = base_path.strip().strip('"').strip("'")
    candidates: list[str] = []

    # Ruta tal cual
    if value:
        candidates.append(value)

    # Corrige formato //server/share -> \\server\share
    if value.startswith("//"):
        candidates.append("\\" + value.replace("/", "\\"))

    # Corrige formato mixto
    candidates.append(value.replace("/", "\\"))
    candidates.append(value.replace("\\", "/"))

    # Variantes con espacios normalizados para tolerar dobles espacios en nombres UNC.
    spaced_candidates: list[str] = []
    for candidate in candidates:
        normalized = _normalize_spaces_in_path(candidate)
        spaced_candidates.append(candidate)
        spaced_candidates.append(normalized)
        # Variante frecuente en este share: " - JURIDICO" vs " -  JURIDICO"
        spaced_candidates.append(normalized.replace(" - JURIDICO", " -  JURIDICO"))

    # Quita duplicados preservando orden
    return list(dict.fromkeys([c for c in spaced_candidates if c]))


def _resolve_network_path(base_path: str) -> str | None:
    for candidate in _build_path_candidates(base_path):
        if os.path.exists(candidate):
            return candidate
    return None


def _list_mapped_drive_roots() -> list[str]:
    """
    Devuelve unidades mapeadas tipo P:\\, Z:\\ y rutas UNC detectadas en `net use`.
    """
    try:
        result = subprocess.run(["net", "use"], capture_output=True, text=True, check=False)
    except OSError:
        return []

    roots: list[str] = []
    for line in result.stdout.splitlines():
        drive_match = re.search(r"\b([A-Z]:)\b", line)
        if drive_match:
            roots.append(drive_match.group(1) + "\\")

        unc_match = re.search(r"(\\\\[^\s]+\\[^\s]+)", line, flags=re.IGNORECASE)
        if unc_match:
            roots.append(unc_match.group(1))
    return list(dict.fromkeys(roots))


def _normalize_spaces_in_path(path: str) -> str:
    raw = path.replace("/", "\\")
    is_unc = raw.startswith("\\\\")
    parts = [segment for segment in raw.split("\\") if segment]
    normalized_parts = [" ".join(segment.split()) for segment in parts]
    normalized = "\\".join(normalized_parts)
    return f"\\\\{normalized}" if is_unc else normalized


def _build_mount_tail_variants(base_path: str) -> list[str]:
    """
    Genera sufijos de la ruta para mounts que empiezan en subcarpetas mas profundas.
    """
    path = base_path.replace("/", "\\").strip("\\")
    parts = [segment for segment in path.split("\\") if segment]

    # Si es UNC, quitamos el servidor para generar sufijos de carpeta.
    if base_path.startswith("\\\\") and len(parts) > 1:
        parts = parts[1:]

    tails: list[str] = []
    for i in range(len(parts)):
        tail = "\\".join(parts[i:])
        tails.append(tail)
        tails.append(_normalize_spaces_in_path(tail))

    return list(dict.fromkeys([t for t in tails if t]))


def _resolve_mounted_path(base_path: str) -> str | None:
    env_mounts = [m.strip() for m in os.getenv("MOUNT_BASE_PATHS", "").split(";") if m.strip()]
    mount_roots = env_mounts + _list_mapped_drive_roots() + [r"P:\\", r"Z:\\"]
    mount_roots = list(dict.fromkeys(mount_roots))

    for root in mount_roots:
        for tail in _build_mount_tail_variants(base_path):
            candidate = os.path.join(root, tail)
            if os.path.exists(candidate):
                return candidate
    return None


def _extract_server_from_unc(path: str) -> str | None:
    value = path.replace("/", "\\").lstrip("\\")
    if not value:
        return None
    return value.split("\\", 1)[0] if "\\" in value else None


def _try_connect_network_share(base_path: str) -> bool:
    server = _extract_server_from_unc(base_path)
    if not server:
        return False

    target = f"\\\\{server}\\IPC$"
    user = os.getenv("NETWORK_USER")
    password = os.getenv("NETWORK_PASSWORD")

    cmd = ["net", "use", target]
    if user and password:
        cmd.extend([password, f"/user:{user}", "/persistent:no"])
    else:
        cmd.append("/persistent:no")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return result.returncode == 0
    except OSError:
        return False

raw_data = """
945220250739127                                   
945220250736289                                   
 945220250897142                                  
945220251011520                                   
DIL20254023406                                    
DIL20253996444                                    
 DIL20253914545                                   
 DIL20253793137                                   
DIL20253811601                                    
945220261473565
94522026111897
DIL20260456691
945220261118970
DIL20260446764
DIL20260457037
DIL20253786064                                    
DIL20253850314                                    
DIL20260636234
DIL20260452776
20250000800477 945220258291430
945220259396996
20250001489745 945220258757555
20250001502136 945220258903404
20250001503412 945220258746126
20250001502961 945220258754849
20250001504066 945220258849284
20250001472146 945220259401870
20250001489635 945220258936085
20250001488736 945220258915702
20250001498820
20250001458136 945220259257879
20250001458060 945220259265931
20250001458271 945220259257934
20250001495390  945220258901171
20250001035057 DIL20251579969
20260000159527 DIL20260092644
20250001458323 945220259263159
20250001494997
20250000202556 
20250001489687 945220258914745
945220261119211
20250001502371 945220259306895
20250001495365 945220259161706
945220261188600
20250000989758 945220258500991
20250001014609 945220258480608
945220261297741
20250001026470 945220258480289
20250001214042 945220258518217
20250001154832 945220258569081
945220261231741
20250001463797 
20250000240935 945220243910965
20250001504779 945220258757291
20250001494927 945220259183080
20250001107841 945220258673262
20250000242662 945220244014211
20250001469193
DIL20260432189
20240000165972 DIL20233215745
20240001357236 945220243467610
20250000780514
20250000961218 DIL20251596004
20250001214501 945220258501200
20250001472188 945220258756180
945220261206265
20250001503946 945220258756521
945220261155324
20250000827256 DIL20251578984
20250001500139 
20250001462211 
20250000349596 
945220261154015
20250001154832 
20250001188831 945220258555342
20250001214506 
20250001487480  945220258799377
20250001214601 
20250001488725 945220258912149
945220261213910
20250001495216 945220258855433
20250001104770 945220258653462
20250001026481 945220258500452
945220261119717
945220261032003
20250000614493 945220245492700
20250001322049 945220258669049
20250000812942 DIL20251429392
20250001026475 945220258668477
20250001502440 945220258756147
20250000989773 945220258688090
20250001214503 945220258481103
20250001462212 945220259256670
20250001462211 945220259255316
20250000366035 945220245374317
945220261236823
20250000349596 945220245192993
945220261525232
945220261077170
945220261185860
945220261121830
20250001494800 945220259147153
"""

# Limpiamos la lista: extrae cada cÃ³digo por separado
search_list = sorted(list(set(re.findall(r'[\w\d]+', raw_data))))

print(f"--- Iniciando bÃºsqueda de {len(search_list)} Ã­tems ---")

# --- PRUEBA DE CONEXION ---
resolved_base_path = _resolve_network_path(BASE_PATH)

if not resolved_base_path:
    # Fallback: ruta montada que puede empezar en una subcarpeta mas profunda
    resolved_base_path = _resolve_mounted_path(BASE_PATH)

if not resolved_base_path:
    print("[INFO] Ruta no accesible al primer intento. Probando conexion a red...")
    _try_connect_network_share(BASE_PATH)
    resolved_base_path = _resolve_network_path(BASE_PATH) or _resolve_mounted_path(BASE_PATH)

if not resolved_base_path:
    print(f"[ERROR] No se puede acceder a la carpeta de red: {BASE_PATH}")
    print("Variantes UNC probadas:")
    for candidate in _build_path_candidates(BASE_PATH):
        print(f"  - {candidate}")
    print("Mount roots detectados:")
    for root in _list_mapped_drive_roots():
        print(f"  - {root}")
    print("Comprueba conectividad, permisos y credenciales del recurso compartido.")
    print(r"Tip: prueba en PowerShell: net use \\SERVER-DOC\IPC$ /user:DOMINIO\usuario *")
    print("Tip: opcionalmente define NETWORK_USER y NETWORK_PASSWORD para conexion automatica.")
    print("Tip: opcionalmente define MOUNT_BASE_PATHS (separado por ';'), ej: P:\\;Z:\\")
    raise SystemExit(1)

print(f"[OK] Ruta accesible: {resolved_base_path}")
print("Escaneando contenido...")

file_count = 0
found_count = 0

try:
    for root, dirs, files in os.walk(resolved_base_path):
        # Si encuentra archivos, sumamos al contador para saber si "ve" algo
        file_count += len(files)
        
        for file in files:
            file_upper = file.upper()
            for item in search_list:
                # BUSQUEDA POR SUBSTRING (si el codigo esta contenido en el nombre)
                if item.upper() in file_upper:
                    print(f"[ENCONTRADO] El item '{item}' esta en el archivo: {file}")
                    found_count += 1

except Exception as e:
    print(f"[ERROR] Error durante el escaneo: {e}")

print("\n" + "="*50)
print(f"Archivos totales analizados en la carpeta: {file_count}")
print(f"Coincidencias encontradas: {found_count}")
print("="*50)

if file_count == 0:
    print("[WARN] El script no ha visto archivos. Puede ser permisos de red o carpeta vacia.")




