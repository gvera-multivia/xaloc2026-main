from __future__ import annotations

import argparse
import json

SITE_HINTS = {
    "madrid": {
        "primary": [
            "Direccion del cliente mal escrita",
            "Pagina de Madrid caida",
        ],
        "action": "Revisar direccion; si parece correcta, tratar como caida de pagina y reintentar.",
    },
    "palma": {
        "primary": [
            "Pagina caida",
        ],
        "action": "Priorizar reintento y ver si hay incidencia temporal de sede.",
    },
    "redsara": {
        "primary": [
            "Direccion mal escrita",
            "Municipio no valido",
            "Excepcion de escritura por nomenclatura propia de Redsara",
        ],
        "action": "Revisar direccion completa y municipio; no asumir caida de pagina hasta descartar escritura.",
    },
    "xaloc_girona": {
        "primary": [
            "Pagina caida o inestable",
        ],
        "action": "Asumir fallo de pagina antes que fallo de automatizacion; candidato a reintento.",
    },
    "base_online": {
        "primary": [
            "Pagina caida",
            "Mala identificacion",
        ],
        "action": "Primero reintentar; si persiste, revisar identificacion.",
    },
    "diputacio_bcn": {
        "primary": [
            "Identificacion incorrecta",
            "Expediente pasado",
            "Pagina caida",
        ],
        "action": "Revisar identificacion y vigencia del expediente antes de culpar a la pagina.",
    },
    "atc": {
        "primary": [
            "Pagina caida",
            "Popup no contemplado",
        ],
        "action": "Reintentar y revisar si aparecieron popups.",
    },
    "terrassa": {
        "primary": [
            "Pagina caida",
            "DNI caducado",
            "DNI mal escrito",
        ],
        "action": "Reintentar si huele a sede; si no, validar DNI y su vigencia.",
    },
}

INCIDENT_ACTIONS = {
    "falta_documentacion": "Poner la autorizacion en la carpeta del cliente y reintentar.",
    "datos_incorrectos": "Corregir dato faltante/incorrecto; si es expediente valido rechazado, usar xaloc-site-rule-tuning.",
    "otro_usuario": "Tratar como bloqueo operativo; no reintentar a ciegas.",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Heuristicas operativas rapidas por sede e incidencia.")
    parser.add_argument("--site-id", required=True, help="site_id del caso")
    parser.add_argument("--incident-type", default="", help="tipo de incidencia opcional")
    args = parser.parse_args()

    site_id = str(args.site_id).strip()
    incident_type = str(args.incident_type).strip().lower()

    site_info = SITE_HINTS.get(site_id, {
        "primary": ["Sin heuristica especifica; usar runtime debugger."],
        "action": "Escalar a xaloc-runtime-failure-debugger.",
    })
    incident_action = INCIDENT_ACTIONS.get(incident_type) if incident_type else None

    payload = {
        "site_id": site_id,
        "site_heuristics": site_info,
        "incident_type": incident_type or None,
        "incident_action": incident_action,
        "requeue_rule": "Si el job debe volver a correr, ir a la lista de bloqueos y usar reintentar o bloquear segun el caso.",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
