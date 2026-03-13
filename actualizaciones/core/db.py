"""
Módulo de base de datos simulada (Mock).
"""

import uuid
from datetime import datetime

class MockDatabase:
    def __init__(self):
        # Datos de prueba para cada sitio
        self._pending_tramites = {
            "xaloc_girona": [
                {
                    "id": str(uuid.uuid4()),
                    "site_id": "xaloc_girona",
                    "protocol": None,
                    "status": "pending",
                    "created_at": datetime.now().isoformat(),
                    "data": {
                        "user_email": "real_user@xaloc.com",
                        "denuncia_num": "DEN/REAL/001",
                        "plate_number": "9999ZZZ",
                        "expediente_num": "EXP/REAL/001",
                        "motivos": "Alegación generada desde base de datos real."
                    }
                }
            ],
            "base_online": [
                {
                    "id": str(uuid.uuid4()),
                    "site_id": "base_online",
                    "protocol": "P1",
                    "status": "pending",
                    "created_at": datetime.now().isoformat(),
                    "data": {
                        "user_email": "real_base@tarragona.cat",
                        "user_phone": "666777888",
                        "plate_number": "1111AAA",
                        "expediente_id_ens": "99999",
                        "expediente_any": "2023",
                        "expediente_num": "8888",
                        "num_butlleti": "BUT/REAL/001",
                        "data_denuncia": "01/01/2023",
                        "nif": "12345678Z",
                        "llicencia_conduccio": "LIC_REAL_001",
                        "name": "Juan Real",
                        "address_street": "Carrer Reial",
                        "address_number": "10",
                        "address_zip": "43000",
                        "address_city": "TARRAGONA",
                        "address_province": "TARRAGONA"
                    }
                }
            ],
            "madrid": [
                {
                    "id": str(uuid.uuid4()),
                    "site_id": "madrid",
                    "protocol": None,
                    "status": "pending",
                    "created_at": datetime.now().isoformat(),
                    "data": {
                        "plate_number": "2222BBB",
                        "user_phone": "611222333",
                        "representative_email": "abogado@madrid.es",
                        "representative_phone": "699888777",
                        "representative_street": "GRAN VIA",
                        "representative_number": "1",
                        "representative_zip": "28013",
                        "representative_city": "MADRID",
                        "notif_name": "CARLOS",
                        "notif_surname1": "LOPEZ",
                        "notif_surname2": "RUIZ",
                        "expediente_tipo": "opcion1",
                        "expediente_nnn": "911",
                        "expediente_eeeeeeeee": "102532229",
                        "expediente_d": "3",
                        "naturaleza": "A",
                        "expone": "Expongo datos reales desde DB.",
                        "solicita": "Solicito anulación desde DB."
                    }
                }
            ]
        }

    def get_pending_tramite(self, site_id: str, protocol: str | None = None) -> tuple[str, dict] | None:
        """
        Devuelve el primer trámite pendiente para el sitio (y protocolo si aplica).
        Retorna (tramite_id, data_dict) o None.
        """
        candidates = self._pending_tramites.get(site_id, [])
        for tramite in candidates:
            if tramite["status"] == "pending":
                # Si se especifica protocolo, filtrar. Si no, devolver cualquiera (o el que coincida si el tramite tiene protocolo)
                # En este mock simplificado, asumimos que si protocol viene en kwargs, debe coincidir.
                if protocol:
                     if tramite.get("protocol") == protocol:
                         return tramite["id"], tramite["data"]
                else:
                    return tramite["id"], tramite["data"]
        return None

    def mark_tramite_processed(self, tramite_id: str, status: str, result: dict | None = None) -> None:
        """
        Actualiza el estado de un trámite.
        """
        for site_list in self._pending_tramites.values():
            for t in site_list:
                if t["id"] == tramite_id:
                    t["status"] = status
                    t["processed_at"] = datetime.now().isoformat()
                    t["result"] = result
                    print(f"[DB] Trámite {tramite_id} actualizado a {status}")
                    return
        print(f"[DB] Trámite {tramite_id} no encontrado.")
