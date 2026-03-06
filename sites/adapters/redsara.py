from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.client_documentation import build_required_client_documents_for_payload
from core.repositories import ResourceRepository
from core.sqlserver_utils import build_sqlserver_connection_string
from .site_adapter import SiteAdapter

JEFATURA_REGEX_LIST = [
    r"^\d{2}/\d{9}/\d$",
    r"^\d{12}$",
    r"^\d{11}$",
    r"^\d{12}-$",
    r"^\d{10}$",
    r"^\d{2}-\d{9}-\d$",
    r"^\d{2}-\d{3}-\d{3}\.\d{3}-\d$",
]

JEFATURA_RULE_ROWS: list[tuple[str, str, list[str]]] = [
    ("JEFATURA DE TRAFICO DE BALEARES", "E03099801", ["JEFATURA PROVINCIAL DE TRÁFICO DE LAS ISLAS BALEARES"]),
    ("JEFATURA PROVINCIAL DE LLEIDA", "E03101601", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO ALBACETE", "E03099301", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO CÁDIZ", "E03100201", []),
    ("JEFATURA PROVINCIAL DE TRAFICO DE A CORUÑA", "E03100601", ["JEFATURA PROVINCIAL DE TRÁFICO DE LA CORUÑA"]),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE ALICANTE", "E03099401", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE ALMERÍA", "E03099501", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE ASTURIAS", "E03102501", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE ÁVILA", "E03099601", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE BADAJOZ", "E03099701", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE BARCELONA", "E03099901", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE BURGOS", "E03100001", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE CÁCERES", "E03100101", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE CANTABRIA", "E03103101", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE CASTELLÓN", "E03100301", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE CIUDAD REAL", "E03100401", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE CÓRDOBA", "E03100501", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE CUENCA", "E03100701", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE GIRONA", "E03100801", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE GRANADA", "E03100901", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE GUADALAJARA", "E03101001", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE HUELVA", "E03101201", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE HUESCA", "E03101301", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE JAEN", "E03101401", []),
    ("JEFATURA PROVINCIAL DE TRAFICO DE LA RIOJA", "E03101701", ["JEFATURA PROVINCIAL DE TRÁFICO DE LA RIOJA"]),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE LAS PALMAS", "E03102701", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE LEÓN", "E03101501", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE LUGO", "E03101801", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE MADRID", "E03101901", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE MÁLAGA", "E03102001", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE MURCIA", "E03102101", []),
    ("JEFATURA PROVINCIAL DE TRAFICO DE NAVARRA", "E03102301", ["JEFATURA PROVINCIAL DE TRÁFICO DE NAVARRA"]),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE OURENSE", "E03102401", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE OVIEDO", "E00130201", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE PALENCIA", "E03102601", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE PAMPLONA", "E00130201", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE PONTEVEDRA", "E03102801", ["JEFATURA TERRITORIAL DE PONTEVEDRA - SERVICIO DE MOVILIDAD"]),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE SALAMANCA", "E03102901", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE SANTA CRUZ DE TENERIFE", "E03103001", ["JEFATURA PROVINCIAL DE TRÁFICO DE TENERIFE"]),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE SEGOVIA", "E03103201", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE SEVILLA", "E03103301", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE SORIA", "E03103401", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE TARRAGONA", "E03103501", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE TERUEL", "E03103601", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE TOLEDO", "E03103701", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE VALENCIA", "E03103801", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE VALLADOLID", "E03103901", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE VIZCAYA", "E03104001", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE ZAMORA", "E03104101", []),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE ZARAGOZA", "E03104201", []),
]


class RedsaraAdapter(SiteAdapter):
    """
    REDSARA multi-organismo.
    Fuente oficial embebida: LIKE de organismo + codigo destino + patrones de expediente.
    """

    # Query con OR explícito para los organismos activos de la fase inicial.
    OFFICIAL_QUERY_ORGANISME = (
        "%AJUNTAMENT DE BARCELONA%|"
        "%SECTOR DE SEGURIDAD Y MOVILIDAD DEL AYUNTAMIENTO DE BARCELONA%|"
        "%ISLAS BALEARES, AGENCIA TRIBUTARIA MUNICIPAL%|"
        "%AGENCIA TRIBUTARIA MUNICIPAL DE ISLAS BALEARES%|"
        "%AGENCIA TRIBITARIA ISLAS BALEARES (ATIB)%|"
        "%CENTRO DE TRATAMIENTO DE DENUNCIAS AUTOMATIZADAS DE LEON%|"
        "%AJUNTAMENT MIGJORN GRAN%|"
        "%AYUNTAMIENTO DE SANTIAGO DE COMPOSTELA%|"
        "%AYUNTAMIENTO DE MOSTOLES%|"
        "%JEFATURA DE TRAFICO%|"
        "%JEFATURA PROVINCIAL DE TRAFICO%|"
        "%JEFATURA PROVINCIAL DE TRÁFICO%|"
        "%JEFATURA TERRITORIAL DE PONTEVEDRA - SERVICIO DE MOVILIDAD%"
    )

    ORGANISM_RULES: list[dict[str, Any]] = [
        {
            "name": "AJUNTAMENT DE BARCELONA",
            "like_patterns": [
                "%AJUNTAMENT DE BARCELONA%",
                "%AYUNTAMIENTO DE BARCELONA%",
                "%SECTOR DE SEGURIDAD Y MOVILIDAD DEL AYUNTAMIENTO DE BARCELONA%",
            ],
            "destination_code": "LA0006797",
            "regex_list": [
                r"^\d{4}SACR\d{7}$",
                r"^EI\d{15}$",
                r"^\d{4}SACG\d{7}$",
                r"^\d{11}$",
                r"^EB\d{15}$",
                r"^\d{4}SACH\d{7}$",
                r"^MX\d{15}$",
                r"^\d{4}SABE\d{7}$",
                r"^EH\d{15}$",
                r"^EJ\d{15}$",
                r"^ET\d{15}$",
                r"^\d{4}SAGA\d{7}$",
                r"^\d{4}SARP\d{7}$",
                r"^\d{4}SACR\d{6}$",
                r"^\d{4}SACH\d{6}$",
                r"^\d{10}$",
                r"^\d{4}EBVH\d{7}$",
                r"^\d{4}SACG\d{6}$",
                r"^I\d{15}$",
                r"^\d{7}$",
            ],
        },
        {
            "name": "CTDA LEON",
            "like_patterns": ["%CENTRO DE TRATAMIENTO DE DENUNCIAS AUTOMATIZADAS DE LEON%"],
            "destination_code": "E00130201",
            "regex_list": [
                r"^\d{2}-\d{3}-\d{3}\.\d{3}-\d$",
                r"^\d{2}-\d{3}-\d{3}-\d{3}-\d$",
            ],
        },
        {
            "name": "AJUNTAMENT MIGJORN GRAN",
            "like_patterns": ["%AJUNTAMENT MIGJORN GRAN%", "%AYUNTAMIENTO DE MIGJORN GRAN%"],
            "destination_code": "L01079028",
            "regex_list": [r"^\d{10}$"],
        },
        {
            "name": "AYUNTAMIENTO DE MOSTOLES",
            "like_patterns": ["%AYUNTAMIENTO DE MOSTOLES%"],
            "destination_code": "LA0007892",
            "regex_list": [r"^\d{9}$"],
        },
        {
            "name": "AYUNTAMIENTO DE SANTIAGO DE COMPOSTELA",
            "like_patterns": ["%AYUNTAMIENTO DE SANTIAGO DE COMPOSTELA%"],
            "destination_code": "L01150780",
            "regex_list": [
                r"^\d{4}/\d{5}$",
                r"^\d{10}$",
            ],
        },
        {
            "name": "ATIB ISLAS BALEARES",
            "like_patterns": [
                "%ISLAS BALEARES, AGENCIA TRIBUTARIA MUNICIPAL%",
                "%AGENCIA TRIBUTARIA MUNICIPAL DE ISLAS BALEARES%",
                "%AGENCIA TRIBITARIA ISLAS BALEARES (ATIB)%",
            ],
            "destination_code": "A04013587",
            "regex_list": [
                r"^\d{3}-\d{2}-\d{6}$",
                r"^\d{7}MU\d{11}$",
                r"^\d{12}$",
                r"^\d{3}-\d{2}-IG-\d{6}$",
                r"^\d{2}/\d{6}$",
            ],
        },
        # Preparado para crecimiento posterior.
        {
            "name": "TRIBUNAL ECONOMICO-ADMINISTRATIVO (GIPUZKOA/DONOSTIA)",
            "like_patterns": ["%TRIBUNAL ECONOMICO ADMINISTRATIVO GIPUZKOA%", "%TRIBUNAL ECONOMICO ADMINISTRATIVO DONOSTIA%"],
            "destination_code": "A16041373",
            "regex_list": [r"^[A-Z0-9][A-Z0-9\-/\.]{5,24}$"],
        },
        *[
            {
                "name": name,
                "like_patterns": [f"%{name}%"] + [f"%{alias}%" for alias in aliases],
                "destination_code": destination_code,
                "regex_list": list(JEFATURA_REGEX_LIST),
            }
            for (name, destination_code, aliases) in JEFATURA_RULE_ROWS
        ],
    ]

    def __init__(self):
        super().__init__(site_id="redsara", priority=4)
        self._compiled_rules: list[tuple[dict[str, Any], list[re.Pattern[str]]]] = []
        for rule in self.ORGANISM_RULES:
            compiled = [re.compile(pattern) for pattern in list(rule.get("regex_list") or [])]
            self._compiled_rules.append((rule, compiled))
        self._re_dni = re.compile(r"^\d{8}[A-Z]$")
        self._re_nie = re.compile(r"^[XYZ]\d{7}[A-Z]$")
        self._re_cif = re.compile(r"^[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]$")
        self._re_pasaporte = re.compile(r"^[A-Z]{2,3}\d{5,9}$")

    @staticmethod
    def _clean_str(v: Any) -> str:
        return str(v).strip() if v is not None else ""

    @staticmethod
    def _is_company_by_cliente_tipo(cliente_tipo: Any) -> bool:
        try:
            return int(str(cliente_tipo).strip()) == 2
        except Exception:
            return False

    @classmethod
    def _merge_query_organisme(cls, configured: Any) -> str:
        """
        Une la query de BD con la oficial del adapter en formato OR por '|',
        para evitar quedarnos con configuraciones antiguas en organismo_config.
        """
        merged: list[str] = []
        seen: set[str] = set()

        def _add_chunk(raw_chunk: Any) -> None:
            token = cls._clean_str(raw_chunk)
            if not token:
                return
            key = token.upper()
            if key in seen:
                return
            seen.add(key)
            merged.append(token)

        configured_text = cls._clean_str(configured)
        if configured_text:
            for chunk in configured_text.split("|"):
                _add_chunk(chunk)

        for chunk in cls.OFFICIAL_QUERY_ORGANISME.split("|"):
            _add_chunk(chunk)

        return "|".join(merged) if merged else cls.OFFICIAL_QUERY_ORGANISME

    @staticmethod
    def _normalize_for_match(text: Any) -> str:
        import unicodedata

        normalized = " ".join(str(text or "").upper().split())
        return "".join(c for c in unicodedata.normalize("NFD", normalized) if unicodedata.category(c) != "Mn")

    @staticmethod
    def _normalize_expediente(expediente: Any) -> str:
        txt = str(expediente or "").strip().upper()
        return re.sub(r"\s+", "", txt)

    @staticmethod
    def _normalize_document_id(doc: Any) -> str:
        text = str(doc or "").strip().upper()
        if text.startswith("ES") and len(text) > 2:
            text = text[2:]
        return re.sub(r"[^A-Z0-9]+", "", text)

    def _detect_document_type(self, doc: str) -> str:
        """
        Clasificación robusta del documento para REDSARA.
        """
        d = self._normalize_document_id(doc)
        if not d:
            return "NIF"
        if self._re_nie.match(d) or re.match(r"^[XYZ]\d{7,8}$", d):
            return "NIE"
        if self._re_dni.match(d):
            return "NIF"
        if self._re_cif.match(d):
            return "CIF"
        if self._re_pasaporte.match(d) or (re.search(r"[A-Z]", d) and re.search(r"\d", d) and 6 <= len(d) <= 15):
            return "PASAPORTE"
        return "NIF"

    def _build_document_type_bundle(self, candidates: list[dict]) -> dict[str, str]:
        """
        Bundle por lote (como patrón BASE): idRecurso -> tipo_doc.
        """
        out: dict[str, str] = {}
        for r in candidates:
            rid = str(r.get("idRecurso") or "").strip()
            if not rid:
                continue
            # Prioridad empresa: nifempresa > cif > nif cliente.
            doc = self._normalize_document_id(
                r.get("cliente_nif_empresa")
                or r.get("cif")
                or r.get("cliente_nif")
            )
            out[rid] = self._detect_document_type(doc)
        return out

    @classmethod
    def _load_motivos_config(cls) -> dict[str, Any]:
        path = Path("config_motivos.json")
        if not path.exists():
            return {}
        try:
            import json as _json

            return _json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    @staticmethod
    def _normalize_text(text: Any) -> str:
        import unicodedata

        t = str(text or "").strip().lower()
        return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")

    @classmethod
    def _build_subject_exposes_solicit(cls, *, fase_raw: str, expediente: str, sujeto: str) -> tuple[str, str, str]:
        config = cls._load_motivos_config()
        fase_norm = cls._normalize_text(fase_raw)

        selected: dict[str, Any] | None = None
        for key, value in (config or {}).items():
            if cls._normalize_text(key) in fase_norm:
                selected = value
                break

        if not selected:
            subject = f"Recurso expediente {expediente}"
            exposes = f"Expongo que en relacion con el expediente {expediente} procede revisar las circunstancias del caso."
            solicit = f"Solicito que se admita este escrito en el expediente {expediente} y se practique la revision solicitada."
            return subject, exposes, solicit

        subject = cls._clean_str(selected.get("asunto")).replace("{expediente}", expediente).replace("{sujeto_recurso}", sujeto)
        exposes = cls._clean_str(selected.get("expone")).replace("{expediente}", expediente).replace("{sujeto_recurso}", sujeto)
        solicit = cls._clean_str(selected.get("solicita")).replace("{expediente}", expediente).replace("{sujeto_recurso}", sujeto)
        if not subject:
            subject = f"Recurso expediente {expediente}"
        if not exposes:
            exposes = f"Expongo que en relacion con el expediente {expediente} procede revisar las circunstancias del caso."
        if not solicit:
            solicit = f"Solicito que se admita este escrito en el expediente {expediente} y se practique la revision solicitada."
        return subject, exposes, solicit

    def resolve_rule_by_organisme(self, organisme_raw: Any) -> Optional[dict[str, Any]]:
        text = self._normalize_for_match(organisme_raw)
        if not text:
            return None
        for rule, _compiled in self._compiled_rules:
            for like in list(rule.get("like_patterns") or []):
                token = self._normalize_for_match(like.replace("%", "").strip())
                if token and token in text:
                    return rule
        return None

    def validate_expediente_for_organisme(self, organisme_raw: Any, expediente: str) -> bool:
        normalized = self._normalize_expediente(expediente)
        if not normalized:
            return False
        text = self._normalize_for_match(organisme_raw)
        for rule, compiled in self._compiled_rules:
            matched_rule = False
            for like in list(rule.get("like_patterns") or []):
                token = self._normalize_for_match(like.replace("%", "").strip())
                if token and token in text:
                    matched_rule = True
                    break
            if not matched_rule:
                continue
            return any(rx.match(normalized) for rx in compiled)
        return False

    def fetch_candidates(
        self,
        *,
        config: dict,
        conn_str: str,
        authenticated_user: Optional[str],
        limit: int,
        on_discard: Optional[SiteAdapter.DiscardCallback] = None,
        resource_repo: Any | None = None,
    ) -> list[dict]:
        repo = resource_repo
        if repo is None:
            repo = ResourceRepository(conn_str=conn_str)

        cfg = dict(config or {})
        cfg["query_organisme"] = self._merge_query_organisme(cfg.get("query_organisme"))

        resources = repo.get_pending_resources(site_id=self.site_id, config=cfg, limit=limit)
        out: list[dict] = []

        for resource in resources:
            if limit and len(out) >= limit:
                break
            recurso = dict(resource.metadata or {})
            expediente = self._normalize_expediente(recurso.get("Expedient"))
            recurso["Expedient"] = expediente
            organisme = self._clean_str(recurso.get("Organisme"))

            if not self.validate_expediente_for_organisme(organisme, expediente):
                if on_discard:
                    on_discard(
                        {
                            "site_id": self.site_id,
                            "idRecurso": recurso.get("idRecurso"),
                            "Expedient": expediente,
                            "tipo_incidencia": "REGEX_DISCARDED",
                            "motivo": f"Expediente no valido para REDSARA ({organisme}): {expediente}",
                        }
                    )
                continue

            estado = int(recurso.get("Estado") or 0)
            usuario = self._clean_str(recurso.get("UsuarioAsignado"))
            if estado == 1 and authenticated_user and not self._same_user_identity(usuario, authenticated_user):
                continue
            if estado == 1 and not authenticated_user:
                continue

            out.append(recurso)
        return out

    async def build_payloads(
        self,
        candidates: list[dict],
        on_discard: Optional[SiteAdapter.DiscardCallback] = None,
    ) -> list[dict]:
        payloads: list[dict] = []
        if not candidates:
            return payloads

        conn_str = build_sqlserver_connection_string()
        doc_type_bundle = self._build_document_type_bundle(candidates)

        for r in candidates:
            organisme = self._clean_str(r.get("Organisme"))
            rule = self.resolve_rule_by_organisme(organisme)
            if not rule:
                if on_discard:
                    on_discard(
                        {
                            "site_id": self.site_id,
                            "idRecurso": r.get("idRecurso"),
                            "Expedient": r.get("Expedient"),
                            "tipo_incidencia": "SITE_RULE_DISCARDED",
                            "motivo": f"Organismo sin regla REDSARA: {organisme}",
                        }
                    )
                continue

            expediente = self._normalize_expediente(r.get("Expedient"))
            fase = self._clean_str(r.get("FaseProcedimiento"))
            sujeto = self._clean_str(r.get("SujetoRecurso")).upper()
            subject, exposes, solicit = self._build_subject_exposes_solicit(
                fase_raw=fase,
                expediente=expediente,
                sujeto=sujeto,
            )

            street_type = self._clean_str(r.get("address_sigla"))
            street = self._clean_str(r.get("cliente_domicilio"))
            province = self._clean_str(r.get("cliente_provincia")).upper()
            city = self._clean_str(r.get("cliente_municipio")).upper()
            zip_code = re.sub(r"\D+", "", self._clean_str(r.get("cliente_cp")))[:5].zfill(5) if self._clean_str(r.get("cliente_cp")) else ""

            is_company = self._is_company_by_cliente_tipo(r.get("cliente_tipo"))
            cif_doc = self._normalize_document_id(r.get("cif"))
            empresa_doc = self._normalize_document_id(r.get("cliente_nif_empresa"))
            nif_persona = self._normalize_document_id(r.get("cliente_nif"))
            if is_company:
                nif = self._normalize_document_id(cif_doc or empresa_doc)
                if not nif:
                    if on_discard:
                        on_discard(
                            {
                                "site_id": self.site_id,
                                "idRecurso": r.get("idRecurso"),
                                "Expedient": r.get("Expedient"),
                                "tipo_incidencia": "SITE_RULE_DISCARDED",
                                "motivo": "Empresa (cliente_tipo=2) sin CIF en rs.cif ni clientes.nifempresa; recurso descartado para evitar presentacion incorrecta.",
                            }
                        )
                    continue
            else:
                nif = self._normalize_document_id(empresa_doc or cif_doc or nif_persona)
            rid = str(r.get("idRecurso") or "")
            interested_doc_type = "CIF" if is_company else (doc_type_bundle.get(rid) or self._detect_document_type(nif))
            razon_social = self._clean_str(r.get("cliente_razon_social")).upper()
            name = self._clean_str(r.get("SujetoRecurso") or r.get("cliente_nombre")).upper()
            surname1 = self._clean_str(r.get("cliente_apellido1")).upper()
            surname2 = self._clean_str(r.get("cliente_apellido2")).upper()

            phone = (
                self._clean_str(r.get("cliente_movil"))
                or self._clean_str(r.get("cliente_tel1"))
                or self._clean_str(r.get("cliente_tel2"))
            )
            email = self._clean_str(r.get("cliente_email")).lower()

            payload: dict[str, Any] = {
                "idRecurso": r.get("idRecurso"),
                "idExp": r.get("idExp"),
                "numclient": r.get("numclient"),
                "cliente_tipo": r.get("cliente_tipo"),
                "interested_is_company": is_company,
                "expediente": expediente,
                "sujeto_recurso": sujeto,
                "fase_procedimiento": fase,
                "nif": nif,
                "interested_doc_number": nif,
                "name": name,
                "surname1": surname1,
                "surname2": surname2,
                "address_sigla": street_type,
                "address_street": street,
                "address_zip": zip_code,
                "address_city": city,
                "address_province": province,
                "user_phone": phone,
                "user_email": email,
                "interested_doc_type": interested_doc_type,
                "razon_social": razon_social,
                "interested_razon_social": razon_social,
                "destination_organism_code": self._clean_str(rule.get("destination_code")),
                "subject": subject,
                "exposes": exposes,
                "solicit": solicit,
                "skip_auto_complete": False,
                "adjuntos": list(r.get("adjuntos") or []),
                "source": "brain_orchestrator",
                "claimed_at": datetime.now().isoformat(),
            }

            try:
                client_docs = await build_required_client_documents_for_payload(
                    payload,
                    sqlserver_conn_str=conn_str,
                    strict=False,
                )
                payload["archivos"] = [str(p) for p in client_docs]
            except Exception:
                payload["archivos"] = []

            payloads.append(payload)

        return payloads
