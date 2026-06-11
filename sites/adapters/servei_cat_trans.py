from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.contact_defaults import get_default_contact_email, get_default_contact_mobile
from .site_adapter import SiteAdapter
from sites.servei_cat_trans.controller import ServeiCatTransController


class ServeiCatTransAdapter(SiteAdapter):
    ADJUNTO_URL_TEMPLATE = (
        "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/expedientes/pdf-adjuntos/{id}"
    )
    DEFAULT_QUERY_ORGANISME = "%SERVEI CATALA DE TRANSIT DE%"
    DEFAULT_REGEX_EXPEDIENTE = r"^\d{2}[-/]\d{8}-\d$"
    TARGET_ORGANISME_PREFIXES = (
        "SERVEI CATALA DE TRANSIT DE",
        "SERVEI CATALA DE TRANSIT",
    )

    def __init__(self) -> None:
        super().__init__(site_id="servei_cat_trans", priority=8)
        self._regex_cache: dict[str, re.Pattern[str]] = {}
        self._fallback_regex = re.compile(self.DEFAULT_REGEX_EXPEDIENTE)

    @staticmethod
    def _clean(value: Any) -> str:
        return str(value).strip() if value is not None else ""

    @classmethod
    def _norm(cls, value: Any) -> str:
        txt = cls._clean(value).upper()
        if not txt:
            return ""
        txt = "".join(ch for ch in unicodedata.normalize("NFD", txt) if unicodedata.category(ch) != "Mn")
        return re.sub(r"\s+", " ", txt).strip()

    @classmethod
    def _normalize_document(cls, doc: Any) -> str:
        value = cls._clean(doc).upper()
        if value.startswith("ES") and len(value) > 2:
            value = value[2:]
        return re.sub(r"[^A-Z0-9]+", "", value)

    @classmethod
    def _load_motivos(cls) -> dict[str, dict[str, Any]]:
        cfg_path = Path("config_motivos.json")
        if not cfg_path.exists():
            return {}
        try:
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return {cls._norm(key): value for key, value in raw.items() if isinstance(value, dict)}

    @classmethod
    def _build_texts(cls, *, expediente: str, fase: str, sujeto_recurso: str) -> tuple[str, str]:
        fase_norm = cls._norm(fase)
        motivos = cls._load_motivos()
        selected: dict[str, Any] | None = motivos.get(fase_norm)
        if selected is None:
            for key_norm, value in motivos.items():
                if key_norm and key_norm in fase_norm:
                    selected = value
                    break

        if selected:
            context = {"expediente": expediente, "sujeto_recurso": sujeto_recurso}
            expone_tpl = cls._clean(selected.get("expone"))
            solicita_tpl = cls._clean(selected.get("solicita"))
            try:
                expone = expone_tpl.format(**context) if expone_tpl else ""
            except Exception:
                expone = expone_tpl
            try:
                solicita = solicita_tpl.format(**context) if solicita_tpl else ""
            except Exception:
                solicita = solicita_tpl
            if expone and solicita:
                return expone, solicita

        return (
            f"Se presenta escrito relacionado con el expediente {expediente}.",
            f"Se solicita la admision y tramitacion del expediente {expediente}.",
        )

    @classmethod
    def _merge_query_organisme(cls, configured: Any) -> str:
        raw = cls._clean(configured)
        if not raw:
            return cls.DEFAULT_QUERY_ORGANISME
        chunks = [cls._clean(part) for part in re.split(r"[|;,]+", raw)]
        chunks = [part for part in chunks if part]
        existing_upper = {part.upper() for part in chunks}
        if cls.DEFAULT_QUERY_ORGANISME.upper() not in existing_upper:
            chunks.append(cls.DEFAULT_QUERY_ORGANISME)
        return "|".join(chunks)

    @classmethod
    def _is_target_organisme(cls, organisme: Any) -> bool:
        norm = cls._norm(organisme)
        if not norm:
            return False
        return any(norm.startswith(prefix) for prefix in cls.TARGET_ORGANISME_PREFIXES)

    @classmethod
    def _normalize_expediente(cls, expediente: Any) -> str:
        exp = cls._clean(expediente).upper().replace(" ", "")
        if re.fullmatch(r"\d{11}", exp):
            return f"{exp[:2]}/{exp[2:10]}-{exp[10]}"
        return exp

    @classmethod
    def _split_identificado_name_parts(
        cls,
        *,
        nombre: Any,
        apellido1: Any,
        apellido2: Any,
    ) -> tuple[str, str, str]:
        return ServeiCatTransController._split_full_name_if_needed(
            nombre=cls._clean(nombre),
            apellido1=cls._clean(apellido1),
            apellido2=cls._clean(apellido2),
        )

    @classmethod
    def _is_identificacion_phase(cls, fase: Any, procedim: Any) -> bool:
        fase_norm = cls._norm(fase)
        procedim_norm = cls._norm(procedim)
        blob = f"{fase_norm} {procedim_norm}"
        return "IDENTIFICAC" in blob

    @classmethod
    def _infer_tramite_tipo(cls, fase: Any, procedim: Any) -> str:
        return "identificacion" if cls._is_identificacion_phase(fase, procedim) else "normal"

    @classmethod
    def _materialize_from_canonical_if_present(cls, record: dict[str, Any]) -> dict[str, Any]:
        out = dict(record or {})
        canonical = out.get("__canonical_v1")
        if not isinstance(canonical, dict):
            return out

        resource = canonical.get("resource") or {}
        client = canonical.get("client") or {}
        vehicle = canonical.get("vehicle") or {}
        attachments = canonical.get("attachments") or []
        client_doc = client.get("document") or {}
        client_name = client.get("name") or {}
        client_address = client.get("address") or {}
        plate = vehicle.get("plate") or {}

        out["idRecurso"] = out.get("idRecurso", resource.get("id"))
        out["idExp"] = out.get("idExp", resource.get("exp_id"))
        out["numclient"] = out.get("numclient", resource.get("numclient"))
        out["Expedient"] = out.get("Expedient", resource.get("expedient"))
        out["Procedim"] = out.get("Procedim", resource.get("procedure"))
        out["Organisme"] = out.get("Organisme", resource.get("organism"))
        out["TExp"] = out.get("TExp", resource.get("texp"))
        out["Estado"] = out.get("Estado", resource.get("state"))
        out["UsuarioAsignado"] = out.get("UsuarioAsignado", resource.get("assigned_user"))
        out["FaseProcedimiento"] = out.get("FaseProcedimiento", resource.get("phase"))
        out["SujetoRecurso"] = out.get("SujetoRecurso", resource.get("subject_name"))

        out["cliente_tipo"] = out.get("cliente_tipo", client.get("type"))
        out["cliente_nif"] = out.get("cliente_nif", client_doc.get("nif"))
        out["cliente_nif_empresa"] = out.get("cliente_nif_empresa", client_doc.get("cif"))
        out["cif"] = out.get("cif", client_doc.get("cif"))
        out["cliente_nombre"] = out.get("cliente_nombre", client_name.get("first"))
        out["cliente_apellido1"] = out.get("cliente_apellido1", client_name.get("last1"))
        out["cliente_apellido2"] = out.get("cliente_apellido2", client_name.get("last2"))
        out["cliente_razon_social"] = out.get("cliente_razon_social", client_name.get("business"))
        out["Nombrefiscal"] = out.get("Nombrefiscal", client_name.get("business"))
        out["cliente_municipio"] = out.get("cliente_municipio", client_address.get("city"))
        out["cliente_provincia"] = out.get("cliente_provincia", client_address.get("province"))
        out["cl_calle"] = out.get("cl_calle", client_address.get("street_name"))
        out["cl_numero"] = out.get("cl_numero", client_address.get("number"))
        out["cl_cp"] = out.get("cl_cp", client_address.get("zip"))
        out["cl_poblacion"] = out.get("cl_poblacion", client_address.get("city"))
        out["cl_provincia"] = out.get("cl_provincia", client_address.get("province"))

        out["matricula"] = out.get("matricula", plate.get("value"))
        out["adjuntos"] = out.get("adjuntos", attachments)
        return out

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
        if resource_repo is None:
            raise RuntimeError("[servei_cat_trans] fetch_candidates requires injected resource_repo (consultor/repository).")

        cfg = dict(config or {})
        cfg["query_organisme"] = self._merge_query_organisme(cfg.get("query_organisme"))

        configured_regex = self._clean(cfg.get("regex_expediente")) or self.DEFAULT_REGEX_EXPEDIENTE
        regex = self._regex_cache.get(configured_regex)
        if regex is None:
            try:
                regex = re.compile(configured_regex)
            except re.error:
                regex = self._fallback_regex
            self._regex_cache[configured_regex] = regex

        out: list[dict] = []
        resources = resource_repo.get_pending_resources(site_id=self.site_id, config=cfg, limit=limit)
        for resource in resources:
            if limit and len(out) >= limit:
                break
            item = self._materialize_from_canonical_if_present(dict(resource.metadata or {}))
            rid = item.get("idRecurso")
            expediente = self._normalize_expediente(item.get("Expedient"))
            item["Expedient"] = expediente
            organisme = self._clean(item.get("Organisme"))
            fase = self._clean(item.get("FaseProcedimiento"))
            procedim = self._clean(item.get("Procedim"))

            if not self._is_target_organisme(organisme):
                if on_discard:
                    on_discard(
                        {
                            "site_id": self.site_id,
                            "idRecurso": rid,
                            "Expedient": expediente,
                            "tipo_incidencia": "SITE_RULE_DISCARDED",
                            "motivo": f"Organismo fuera de servei_cat_trans: {organisme}",
                        }
                    )
                continue

            if not expediente or not regex.match(expediente):
                if on_discard:
                    on_discard(
                        {
                            "site_id": self.site_id,
                            "idRecurso": rid,
                            "Expedient": expediente,
                            "tipo_incidencia": "REGEX_DISCARDED",
                            "motivo": f"Expediente no valido para servei_cat_trans: {expediente}",
                        }
                    )
                continue

            estado = int(item.get("Estado") or 0)
            usuario = self._clean(item.get("UsuarioAsignado"))
            if estado == 1 and authenticated_user and not self._same_user_identity(usuario, authenticated_user):
                continue
            if estado == 1 and not authenticated_user:
                continue

            adjuntos = list(item.get("adjuntos") or [])
            for adj in adjuntos:
                if "url" not in adj and adj.get("id") is not None:
                    adj["url"] = self.ADJUNTO_URL_TEMPLATE.format(id=int(adj["id"]))
            item["adjuntos"] = adjuntos
            out.append(item)

        return out

    async def build_payloads(
        self,
        candidates: list[dict],
        on_discard: Optional[SiteAdapter.DiscardCallback] = None,
    ) -> list[dict]:
        payloads: list[dict] = []
        for r in candidates:
            rid = r.get("idRecurso")
            expediente = self._normalize_expediente(r.get("Expedient"))
            if not expediente:
                continue

            tipodecliente = self._clean(r.get("cliente_tipo") or r.get("tipodecliente"))
            is_company = tipodecliente == "2" or bool(self._clean(r.get("cliente_nif_empresa")) or self._clean(r.get("cif")))
            nif_persona = self._normalize_document(r.get("cliente_nif"))
            nif_empresa = self._normalize_document(r.get("cliente_nif_empresa") or r.get("cif"))
            nombre = self._clean(r.get("cliente_nombre") or r.get("SujetoRecurso"))
            apellido1 = self._clean(r.get("cliente_apellido1"))
            apellido2 = self._clean(r.get("cliente_apellido2"))
            razon_social = self._clean(r.get("cliente_razon_social") or r.get("Nombrefiscal") or r.get("SujetoRecurso"))
            fase = self._clean(r.get("FaseProcedimiento"))
            procedim = self._clean(r.get("Procedim"))
            tramite_tipo = self._infer_tramite_tipo(fase, procedim)
            sujeto_recurso = self._clean(r.get("SujetoRecurso") or razon_social or nombre)
            expone, solicita = self._build_texts(expediente=expediente, fase=fase, sujeto_recurso=sujeto_recurso)

            identificado_nombre = self._clean(
                r.get("identificado_nombre")
                or r.get("ConducNom")
                or r.get("conduc_nom")
            )
            identificado_apellido1 = self._clean(
                r.get("identificado_apellido1")
                or r.get("ConducApellido1")
                or r.get("conduc_apellido1")
            )
            identificado_apellido2 = self._clean(
                r.get("identificado_apellido2")
                or r.get("ConducApellido2")
                or r.get("conduc_apellido2")
            )
            identificado_apellido1_raw = identificado_apellido1
            identificado_apellido2_raw = identificado_apellido2
            (
                identificado_nombre,
                identificado_apellido1,
                identificado_apellido2,
            ) = self._split_identificado_name_parts(
                nombre=identificado_nombre,
                apellido1=identificado_apellido1,
                apellido2=identificado_apellido2,
            )
            identificado_nif = self._normalize_document(
                r.get("identificado_nif")
                or r.get("ConducDni")
                or r.get("conduc_dni")
            )
            identificado_nif_empresa = self._normalize_document(
                r.get("identificado_nif_empresa")
                or r.get("identificado_cif")
                or r.get("ConducCif")
                or r.get("conduc_cif")
            )
            identificado_razon_social = self._clean(
                r.get("identificado_razon_social")
                or r.get("ConducRazonSocial")
                or r.get("conduc_razon_social")
            )
            identificado_calle_raw = self._clean(
                r.get("identificado_calle_raw")
                or r.get("identificado_calle")
                or r.get("ConducAdr")
                or r.get("conduc_adr")
            )
            identificado_numero_raw = self._clean(
                r.get("identificado_numero_raw")
                or r.get("identificado_numero")
                or r.get("ConducNumero")
                or r.get("conduc_numero")
            )
            identificado_cp = self._clean(
                r.get("identificado_cp")
                or r.get("ConducCodpost")
                or r.get("conduc_codpost")
            )
            identificado_municipio = self._clean(
                r.get("identificado_municipio")
                or r.get("identificado_poblacion")
                or r.get("ConducPobl")
                or r.get("conduc_pobl")
            )
            identificado_provincia = self._clean(
                r.get("identificado_provincia")
                or r.get("ConducProv")
                or r.get("conduc_prov")
            )
            same_identificado_as_solicitante = bool(
                identificado_nif and nif_persona and identificado_nif == nif_persona
            )
            identified_matches_client_identity = (
                same_identificado_as_solicitante
                and (
                    not apellido1
                    or self._norm(identificado_apellido1) == self._norm(apellido1)
                )
                and (
                    not nombre
                    or self._norm(identificado_nombre).startswith(self._norm(nombre))
                    or self._norm(nombre).startswith(self._norm(identificado_nombre))
                )
            )
            if identified_matches_client_identity and not identificado_apellido1_raw:
                identificado_apellido1 = apellido1
            if identified_matches_client_identity and not identificado_apellido2_raw:
                if apellido2:
                    identificado_apellido2 = apellido2
            if same_identificado_as_solicitante:
                if not identificado_calle_raw:
                    identificado_calle_raw = self._clean(
                        r.get("cl_calle")
                        or r.get("cliente_domicilio")
                        or r.get("calle")
                    )
                if not identificado_numero_raw:
                    identificado_numero_raw = self._clean(
                        r.get("cl_numero")
                        or r.get("cliente_numero")
                        or r.get("numero")
                    )
                if not identificado_cp:
                    identificado_cp = self._clean(
                        r.get("cl_cp")
                        or r.get("cliente_cp")
                    )
                if not identificado_municipio:
                    identificado_municipio = self._clean(
                        r.get("cl_poblacion")
                        or r.get("cliente_municipio")
                    )
                if not identificado_provincia:
                    identificado_provincia = self._clean(
                        r.get("cl_provincia")
                        or r.get("cliente_provincia")
                    )
            identificado_ai = ServeiCatTransController._enrich_address_fields(
                direccion_raw=identificado_calle_raw,
                cp_raw=identificado_cp,
                numero_raw=identificado_numero_raw,
                municipio_raw=identificado_municipio,
                provincia_raw=identificado_provincia,
                default_provincia="",
                piso_raw=self._clean(r.get("identificado_piso")),
                puerta_raw=self._clean(r.get("identificado_puerta")),
                tipo_via_raw=self._clean(r.get("identificado_tipo_via")),
                nombre_via_raw=self._clean(r.get("identificado_nombre_via")),
            )

            tipo_identificado_raw = self._clean(
                r.get("identificado_tipo_persona")
                or r.get("identificado_tipodecliente")
            ).lower()
            if tipo_identificado_raw in {"juridica", "2", "empresa", "pj"}:
                identificado_tipo_persona = "juridica"
            elif tipo_identificado_raw in {"fisica", "1", "pf", "particular"}:
                identificado_tipo_persona = "fisica"
            else:
                identificado_tipo_persona = "juridica" if identificado_nif_empresa else "fisica"

            if is_company and not nif_empresa:
                if on_discard:
                    on_discard(
                        {
                            "site_id": self.site_id,
                            "idRecurso": rid,
                            "Expedient": expediente,
                            "tipo_incidencia": "SITE_RULE_DISCARDED",
                            "motivo": "Persona juridica sin nifempresa/cif.",
                        }
                    )
                continue

            if tramite_tipo == "identificacion":
                if identificado_tipo_persona == "juridica":
                    if not identificado_nif_empresa or not identificado_razon_social:
                        if on_discard:
                            on_discard(
                                {
                                    "site_id": self.site_id,
                                    "idRecurso": rid,
                                    "Expedient": expediente,
                                    "tipo_incidencia": "SITE_RULE_DISCARDED",
                                    "motivo": "Identificacion juridica sin nif_empresa o razon_social del identificado.",
                                }
                            )
                        continue
                else:
                    if not identificado_nif or not identificado_nombre:
                        if on_discard:
                            on_discard(
                                {
                                    "site_id": self.site_id,
                                    "idRecurso": rid,
                                    "Expedient": expediente,
                                    "tipo_incidencia": "SITE_RULE_DISCARDED",
                                    "motivo": "Identificacion fisica sin documento o nombre del identificado.",
                                }
                            )
                        continue

            payloads.append(
                {
                    "idRecurso": r.get("idRecurso"),
                    "idExp": r.get("idExp"),
                    "numclient": r.get("numclient"),
                    "expediente": expediente,
                    "Expedient": expediente,
                    "FaseProcedimiento": fase,
                    "fase_procedimiento": fase,
                    "Procedim": procedim,
                    "procedim": procedim,
                    "tramite_tipo": tramite_tipo,
                    "SujetoRecurso": sujeto_recurso,
                    "tipodecliente": tipodecliente,
                    "tipo_persona": "juridica" if is_company else "fisica",
                    "nombre": nombre,
                    "apellido1": apellido1,
                    "apellido2": apellido2,
                    "razon_social": razon_social,
                    "nif": nif_persona,
                    "nifempresa": nif_empresa,
                    "representado_calle_raw": self._clean(
                        r.get("cl_calle")
                        or r.get("cliente_domicilio")
                        or r.get("calle")
                    ),
                    "representado_numero_raw": self._clean(
                        r.get("cl_numero")
                        or r.get("cliente_numero")
                        or r.get("numero")
                    ),
                    "representado_cp": self._clean(
                        r.get("cl_cp")
                        or r.get("cliente_cp")
                    ),
                    "representado_poblacion": self._clean(
                        r.get("cl_poblacion")
                        or r.get("cliente_municipio")
                    ),
                    "representado_provincia": self._clean(
                        r.get("cl_provincia")
                        or r.get("cliente_provincia")
                    ),
                    "identificado_tipo_persona": identificado_tipo_persona,
                    "identificado_nombre": identificado_nombre,
                    "identificado_apellido1": identificado_apellido1,
                    "identificado_apellido2": identificado_apellido2,
                    "identificado_nif": identificado_nif,
                    "identificado_nif_empresa": identificado_nif_empresa,
                    "identificado_razon_social": identificado_razon_social,
                    "identificado_calle_raw": identificado_calle_raw,
                    "identificado_numero_raw": identificado_ai.get("numero") or identificado_numero_raw,
                    "identificado_cp": identificado_ai.get("cp") or identificado_cp,
                    "identificado_tipo_via": identificado_ai.get("tipo_via") or self._clean(r.get("identificado_tipo_via")),
                    "identificado_nombre_via": identificado_ai.get("nombre_via") or self._clean(r.get("identificado_nombre_via")),
                    "identificado_municipio": identificado_ai.get("municipio") or identificado_municipio,
                    "identificado_provincia": identificado_ai.get("provincia") or identificado_provincia,
                    "identificado_comarca": identificado_ai.get("comarca") or self._clean(r.get("identificado_comarca")),
                    "identificado_same_as_solicitante": same_identificado_as_solicitante,
                    "expongo": expone,
                    "solicito": solicita,
                    "email": get_default_contact_email(),
                    "telefono_movil": get_default_contact_mobile(),
                    "adjuntos": list(r.get("adjuntos") or []),
                    "archivos": [],
                    "source": "brain_orchestrator",
                    "claimed_at": datetime.now().isoformat(),
                }
            )
        return payloads
