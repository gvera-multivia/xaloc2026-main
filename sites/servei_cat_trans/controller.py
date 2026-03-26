from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

import requests
from groq import Groq

from core.address_classifier import classify_address_fallback
from core.contact_defaults import get_default_contact_email, get_default_contact_mobile
from .config import ServeiCatTransConfig
from .data_models import ServeiCatTransTarget

_NIF_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
_CARTOCIUDAD_BASE_URLS = (
    # Producción: endpoint principal de CartoCiudad (alineado con smoke).
    "http://192.168.184.72:8020",
    # Opcional por entorno para override puntual (permanece aunque esté vacío).
    os.getenv("CARTOCIUDAD_API_URL", "").strip(),
)
logger = logging.getLogger("servei_cat_trans.controller")

_MUNICIPIO_EQUIVALENCE: dict[str, tuple[str, ...]] = {
    # Caso conocido CartoCiudad vs datos internos.
    "bigues i riells": ("Bigues i Riells del Fai",),
    "bigues i riells del fai": ("Bigues i Riells",),
}


class ServeiCatTransController:
    site_id = "servei_cat_trans"
    display_name = "Servei Cat Trans"

    def create_config(self, *, headless: bool):
        cfg = ServeiCatTransConfig()
        cfg.navegador.headless = bool(headless)
        return cfg

    @staticmethod
    def _repair_mojibake(text: str) -> str:
        raw = str(text or "")
        if not raw:
            return ""
        # Corrige casos tipicos UTF-8 interpretado como latin-1/win-1252: "Ã¨", "Ã¡", etc.
        if any(ch in raw for ch in ("Ã", "Â", "â")):
            for enc in ("latin-1", "cp1252"):
                try:
                    fixed = raw.encode(enc, errors="strict").decode("utf-8", errors="strict")
                    if fixed:
                        raw = fixed
                        break
                except Exception:
                    continue
        # Eliminar controles no imprimibles.
        return re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]+", " ", raw)

    @staticmethod
    def _clean(v: Any) -> str:
        return ServeiCatTransController._repair_mojibake(str(v or "")).strip()

    @classmethod
    def _norm(cls, v: Any) -> str:
        txt = cls._clean(v).lower()
        if not txt:
            return ""
        txt = "".join(ch for ch in unicodedata.normalize("NFD", txt) if unicodedata.category(ch) != "Mn")
        return re.sub(r"[^a-z0-9]+", " ", txt).strip()

    @classmethod
    def _sanitize_document(cls, v: Any) -> str:
        return re.sub(r"[^A-Z0-9]+", "", cls._clean(v).upper())

    @classmethod
    def _same_municipio_family(cls, left: str, right: str) -> bool:
        a = cls._norm(left)
        b = cls._norm(right)
        if not a or not b:
            return False
        if a == b:
            return True
        # Flexibilidad controlada: permitir solo extensiones por sufijo
        # ("bigues i riells" -> "bigues i riells del fai"), no similitudes amplias.
        shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
        if len(shorter) < 8:
            return False
        if " " not in shorter:
            return False
        return longer.startswith(shorter + " ")

    @classmethod
    def _municipio_variants(cls, *, municipio: str, carto_municipio: str = "") -> list[str]:
        base = cls._clean(municipio)
        out: list[str] = []
        if base:
            out.append(base)

        norm_base = cls._norm(base)
        if norm_base:
            for alias in _MUNICIPIO_EQUIVALENCE.get(norm_base, ()):
                alias_txt = cls._clean(alias)
                if alias_txt:
                    out.append(alias_txt)

        carto_txt = cls._clean(carto_municipio)
        if carto_txt and cls._same_municipio_family(base, carto_txt):
            out.append(carto_txt)

        unique: list[str] = []
        seen: set[str] = set()
        for item in out:
            key = cls._norm(item)
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    @classmethod
    def _ensure_nif_nie_letter(cls, v: Any) -> str:
        doc = cls._sanitize_document(v)
        if re.fullmatch(r"\d{8}[A-Z]", doc) or re.fullmatch(r"[XYZ]\d{7}[A-Z]", doc):
            return doc

        if re.fullmatch(r"\d{8}", doc):
            idx = int(doc) % 23
            return f"{doc}{_NIF_LETTERS[idx]}"

        if re.fullmatch(r"[XYZ]\d{7}", doc):
            map_prefix = {"X": "0", "Y": "1", "Z": "2"}
            number = f"{map_prefix[doc[0]]}{doc[1:]}"
            idx = int(number) % 23
            return f"{doc}{_NIF_LETTERS[idx]}"

        return doc

    @classmethod
    def _classify_address_with_groq(
        cls,
        *,
        direccion_raw: str,
        poblacion: str,
        numero: str,
        piso: str,
        puerta: str,
    ) -> dict[str, str]:
        fallback = classify_address_fallback(direccion_raw)
        key = (os.getenv("GROQ_API_KEY") or "").strip()
        if not key or not direccion_raw:
            logger.info(
                "Direccion: Groq omitido (key=%s, direccion=%s), usando fallback local.",
                bool(key),
                bool(direccion_raw),
            )
            return fallback

        system = (
            "Devuelve SOLO JSON con claves: via, calle, numero, escalera, planta, puerta. "
            "via debe ser un tipo de via valido en espana (CALLE/AVENIDA/PASEO/RONDA/PLAZA/CARRETERA/etc). "
            "No inventes codigo postal ni provincia. Si no sabes, deja vacio."
        )
        payload = {
            "direccion_raw": direccion_raw,
            "poblacion": poblacion,
            "numero": numero,
            "piso": piso,
            "puerta": puerta,
        }

        try:
            client = Groq(api_key=key)
            chat = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                temperature=0.1,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
            )
            parsed = json.loads(chat.choices[0].message.content or "{}")
            via = cls._clean(parsed.get("via") or fallback.get("tipo_via") or "CALLE").upper()
            return {
                "tipo_via": via,
                "calle": cls._clean(parsed.get("calle") or fallback.get("calle")),
                "numero": cls._clean(parsed.get("numero") or fallback.get("numero")),
                "escalera": cls._clean(parsed.get("escalera") or fallback.get("escalera")),
                "planta": cls._clean(parsed.get("planta") or fallback.get("planta")),
                "puerta": cls._clean(parsed.get("puerta") or fallback.get("puerta")),
            }
        except Exception as exc:
            logger.warning("Direccion: Groq fallo (%s), usando fallback local.", exc)
            return fallback

    @classmethod
    def _query_cartociudad(cls, *, query: str) -> dict[str, str]:
        if not query:
            return {}

        params = {"q": query, "limit": 1}
        for base_url in _CARTOCIUDAD_BASE_URLS:
            if not base_url:
                continue
            url = f"{base_url.rstrip('/')}/location/direccion"
            try:
                resp = requests.get(url, params=params, timeout=(3.0, 8.0))
                if resp.status_code != 200:
                    logger.info(
                        "Direccion: CartoCiudad responde status %s en %s.",
                        resp.status_code,
                        base_url,
                    )
                    continue
                data = resp.json()
                if not isinstance(data, dict):
                    logger.info("Direccion: CartoCiudad payload no-dict en %s.", base_url)
                    continue
                results = data.get("results")
                if not isinstance(results, list) or not results:
                    logger.info("Direccion: CartoCiudad sin resultados en %s.", base_url)
                    continue
                first = results[0] if isinstance(results[0], dict) else {}
                logger.info("Direccion: CartoCiudad enriquecio direccion usando %s.", base_url)
                return {
                    "municipio": cls._clean(first.get("municipio") or first.get("poblacion")),
                    "provincia": cls._clean(first.get("provincia") or first.get("province")),
                    "cp": cls._clean(first.get("cod_postal") or first.get("postalCode")),
                    "address": cls._clean(first.get("address")),
                }
            except Exception as exc:
                logger.warning("Direccion: error llamando CartoCiudad en %s (%s).", base_url, exc)
                continue
        logger.info("Direccion: CartoCiudad sin match final, se mantiene info local/LLM.")
        return {}

    @classmethod
    def _query_comarca_cartociudad(
        cls,
        *,
        provincia: str,
        municipio: str,
        carto_municipio: str = "",
    ) -> str:
        provincia_txt = cls._clean(provincia)
        if not provincia_txt:
            return ""
        municipio_candidates = cls._municipio_variants(
            municipio=municipio,
            carto_municipio=carto_municipio,
        )
        if not municipio_candidates:
            return ""
        for base_url in _CARTOCIUDAD_BASE_URLS:
            if not base_url:
                continue
            url = f"{base_url.rstrip('/')}/location/comarca"
            for municipio_txt in municipio_candidates:
                params = {"provincia": provincia_txt, "municipio": municipio_txt}
                try:
                    resp = requests.get(url, params=params, timeout=(3.0, 8.0))
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    if not isinstance(data, dict):
                        continue
                    comarca = cls._clean(data.get("comarca"))
                    if comarca:
                        logger.info(
                            "Direccion: CartoCiudad devolvio comarca=%s para %s/%s (candidatos=%s)",
                            comarca,
                            municipio_txt,
                            provincia_txt,
                            municipio_candidates,
                        )
                        return comarca
                except Exception as exc:
                    logger.warning("Direccion: error consultando comarca en %s (%s).", base_url, exc)
                    continue
        return ""

    @classmethod
    def _enrich_address_fields(
        cls,
        *,
        direccion_raw: str,
        cp_raw: str,
        numero_raw: str,
        municipio_raw: str,
        provincia_raw: str,
        piso_raw: str = "",
        puerta_raw: str = "",
        tipo_via_raw: str = "",
        nombre_via_raw: str = "",
    ) -> dict[str, str]:
        if not numero_raw and direccion_raw:
            num_match = re.search(r"\d+", direccion_raw)
            if num_match:
                numero_raw = num_match.group(0)

        llm = cls._classify_address_with_groq(
            direccion_raw=direccion_raw,
            poblacion=municipio_raw,
            numero=numero_raw,
            piso=piso_raw,
            puerta=puerta_raw,
        )
        query_parts = [direccion_raw, numero_raw, cp_raw, municipio_raw, provincia_raw, "España"]
        query = ", ".join(part for part in query_parts if cls._clean(part))
        carto = cls._query_cartociudad(query=query)
        resolved_municipio = cls._clean(municipio_raw) or cls._clean(carto.get("municipio"))
        resolved_provincia = cls._clean(provincia_raw) or cls._clean(carto.get("provincia")) or "Barcelona"
        resolved_comarca = cls._query_comarca_cartociudad(
            provincia=resolved_provincia,
            municipio=resolved_municipio,
            carto_municipio=cls._clean(carto.get("municipio")),
        )
        resolved = {
            "tipo_via": cls._clean(tipo_via_raw) or cls._clean(llm.get("tipo_via")) or "CALLE",
            "nombre_via": cls._clean(nombre_via_raw) or cls._clean(llm.get("calle")) or cls._clean(direccion_raw),
            "numero": cls._clean(numero_raw) or cls._clean(llm.get("numero")),
            "cp": cls._clean(cp_raw),
            "municipio": resolved_municipio,
            "provincia": resolved_provincia,
            "comarca": resolved_comarca,
        }
        normalized_bundle = cls._norm(
            f"{direccion_raw} {nombre_via_raw} {resolved.get('nombre_via')}"
        )
        if "general mitre" in normalized_bundle:
            resolved["tipo_via"] = "RONDA"
            if not cls._clean(resolved.get("nombre_via")):
                resolved["nombre_via"] = "DEL GENERAL MITRE"
        logger.info(
            "Direccion final: via=%s calle=%s num=%s cp=%s mun=%s prov=%s comarca=%s (llm=%s carto_comarca=%s)",
            resolved.get("tipo_via"),
            resolved.get("nombre_via"),
            resolved.get("numero"),
            resolved.get("cp"),
            resolved.get("municipio"),
            resolved.get("provincia"),
            resolved.get("comarca"),
            bool(llm),
            bool(resolved_comarca),
        )
        return resolved

    @classmethod
    def _infer_tipo_escrito(cls, fase: str, procedim: str) -> str:
        procedim_norm = cls._norm(procedim)
        fase_norm = cls._norm(fase)

        # Regla prioritaria: si el procedimiento menciona "recurso extraordinario"
        # (sin importar mayusculas/acentos), marcar "Recurso extraordinario de revision".
        if "recurso extraordinario" in procedim_norm:
            return "revision"

        # Grupo 1: escrito de alegaciones.
        if (
            fase_norm in {"alegaciones", "denuncia"}
            or "propuesta de resolucion" in fase_norm
        ):
            return "alegaciones"

        # Grupo 2: recurso potestativo de reposicion.
        if any(token in fase_norm for token in ("sancion", "apremio", "embargo")):
            return "reposicion"

        # Fallback historico del site.
        return "alegaciones"

    @classmethod
    def _split_expediente(cls, expediente: str) -> tuple[str, str, str]:
        raw = cls._clean(expediente)
        if not raw:
            return "", "", ""

        match = re.search(r"(\d{2})[/-](\d{7,10})-(\d{1,2})", raw)
        if match:
            return match.group(1), match.group(2), match.group(3)

        digits = re.findall(r"\d+", raw)
        if len(digits) >= 3:
            return digits[0][-2:], digits[1], digits[2]
        return "", "", ""

    @classmethod
    def _infer_document_type_persona(cls, document: str) -> str:
        doc = cls._sanitize_document(document)
        if re.fullmatch(r"\d{8}[A-Z]", doc):
            return "DNI"
        if re.fullmatch(r"[XYZ]\d{7}[A-Z]", doc):
            return "NIE"
        if doc:
            return "Pasaporte"
        return "DNI"

    @classmethod
    def _infer_document_type_empresa(cls, document: str) -> str:
        doc = cls._sanitize_document(document)
        if re.fullmatch(r"[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]", doc):
            return "NIF de empresa"
        if doc:
            return "Documento de identidad extranjero"
        return "NIF de empresa"

    @classmethod
    def _fallback_expone(cls, expediente: str) -> str:
        return f"Se presenta escrito relacionado con el expediente {expediente}."

    @classmethod
    def _fallback_solicita(cls, expediente: str) -> str:
        return f"Se solicita la admision y tramitacion del expediente {expediente}."

    def map_data(self, data: dict) -> dict:
        src = dict(data or {})
        expediente = self._clean(src.get("expediente") or src.get("Expedient"))
        servicio, expediente_num, digito = self._split_expediente(expediente)

        tipodecliente = self._clean(src.get("tipodecliente"))
        is_company = tipodecliente == "2" or bool(self._clean(src.get("nifempresa")))
        tipo_persona = "juridica" if is_company else "fisica"

        nombre = self._clean(src.get("nombre") or src.get("Nombre") or src.get("SujetoRecurso"))
        apellido1 = self._clean(src.get("apellido1") or src.get("Apellido1"))
        apellido2 = self._clean(src.get("apellido2") or src.get("Apellido2"))
        nif_persona = self._ensure_nif_nie_letter(src.get("nif"))
        razon_social = self._clean(src.get("razon_social") or src.get("Nombrefiscal") or src.get("SujetoRecurso"))
        nif_empresa = self._sanitize_document(src.get("nifempresa"))

        fase = self._clean(src.get("fase_procedimiento") or src.get("FaseProcedimiento"))
        procedim = self._clean(src.get("procedim") or src.get("Procedim"))
        tipo_escrito = self._clean(src.get("tipo_escrito")) or self._infer_tipo_escrito(fase, procedim)
        expongo = self._clean(src.get("expongo")) or self._fallback_expone(expediente)
        solicita = self._clean(src.get("solicito")) or self._fallback_solicita(expediente)
        email = self._clean(src.get("email")) or get_default_contact_email()
        telefono = self._clean(src.get("telefono_movil") or src.get("telefono")) or get_default_contact_mobile()

        # IMPORTANTE: la direccion del representante/presentador NO pasa por IA.
        # Debe mantenerse hardcoded/default salvo que venga explicita en payload.
        direccion_tipo_via = self._clean(src.get("direccion_tipo_via"))
        direccion_nombre_via = self._clean(src.get("direccion_nombre_via") or src.get("direccion"))
        direccion_numero = self._clean(src.get("direccion_numero"))
        direccion_cp = self._clean(src.get("direccion_cp"))
        direccion_provincia = self._clean(src.get("direccion_provincia"))
        direccion_municipio = self._clean(src.get("direccion_municipio"))

        representado_calle_raw = self._clean(
            src.get("representado_calle")
            or src.get("representado_nombre_via")
            or src.get("representado_calle_raw")
            or src.get("cliente_domicilio")
        )
        representado_cp_raw = self._clean(
            src.get("representado_cp")
            or src.get("cl_cp")
            or src.get("cliente_cp")
            or src.get("Cpostal")
        )
        representado_numero_raw = self._clean(
            src.get("representado_numero")
            or src.get("representado_numero_raw")
            or src.get("cliente_numero")
        )
        representado_municipio_raw = self._clean(
            src.get("representado_municipio")
            or src.get("representado_poblacion")
            or src.get("cl_poblacion")
            or src.get("cliente_municipio")
        )
        representado_provincia_raw = self._clean(
            src.get("representado_provincia")
            or src.get("cl_provincia")
            or src.get("cliente_provincia")
        )

        logger.info(
            "map_data raw representado: calle_raw=%r numero_raw=%r cp_raw=%r municipio_raw=%r provincia_raw=%r cp_candidates=%r",
            representado_calle_raw,
            representado_numero_raw,
            representado_cp_raw,
            representado_municipio_raw,
            representado_provincia_raw,
            {
                "representado_cp": self._clean(src.get("representado_cp")),
                "cl_cp": self._clean(src.get("cl_cp")),
                "cliente_cp": self._clean(src.get("cliente_cp")),
                "Cpostal": self._clean(src.get("Cpostal")),
            },
        )

        representado_ai = self._enrich_address_fields(
            direccion_raw=representado_calle_raw,
            cp_raw=representado_cp_raw,
            numero_raw=representado_numero_raw,
            municipio_raw=representado_municipio_raw,
            provincia_raw=representado_provincia_raw,
            piso_raw=self._clean(src.get("representado_piso")),
            puerta_raw=self._clean(src.get("representado_puerta")),
            tipo_via_raw=self._clean(src.get("representado_tipo_via")),
            nombre_via_raw=self._clean(src.get("representado_nombre_via")),
        )

        archivos = src.get("archivos") or src.get("archivos_adjuntos") or []
        if isinstance(archivos, str):
            archivos = [archivos]

        logger.info(
            "map_data resolved representado: via=%r nombre_via=%r numero=%r cp=%r provincia=%r comarca=%r municipio=%r",
            representado_ai["tipo_via"],
            representado_ai["nombre_via"],
            representado_ai["numero"],
            representado_ai["cp"],
            representado_ai["provincia"],
            self._clean(src.get("representado_comarca")) or self._clean(representado_ai.get("comarca")),
            representado_ai["municipio"],
        )

        return {
            "idRecurso": src.get("idRecurso"),
            "idExp": src.get("idExp") or src.get("IdExp"),
            "numclient": src.get("numclient"),
            "expediente": expediente,
            "servicio_territorial": servicio,
            "expediente_numero": expediente_num,
            "digito_control": digito,
            "codigo_personal": self._clean(src.get("codigo_personal")) or self._clean(src.get("idRecurso")),
            "tipo_persona": tipo_persona,
            "nombre": nombre,
            "apellido1": apellido1,
            "apellido2": apellido2,
            "nif": nif_persona,
            "razon_social": razon_social,
            "nif_empresa": nif_empresa,
            "documento_solicitante_tipo": self._infer_document_type_persona(nif_persona),
            "documento_empresa_tipo": self._infer_document_type_empresa(nif_empresa),
            "email": email,
            "telefono_movil": telefono,
            "direccion_tipo_via": direccion_tipo_via,
            "direccion_nombre_via": direccion_nombre_via,
            "direccion_numero": direccion_numero,
            "direccion_cp": direccion_cp,
            "direccion_provincia": direccion_provincia,
            "direccion_comarca": self._clean(src.get("direccion_comarca")),
            "direccion_municipio": direccion_municipio,
            "representado_tipo_via": representado_ai["tipo_via"],
            "representado_nombre_via": representado_ai["nombre_via"],
            "representado_numero": representado_ai["numero"],
            "representado_cp": representado_ai["cp"],
            "representado_provincia": representado_ai["provincia"],
            "representado_comarca": self._clean(src.get("representado_comarca")) or self._clean(representado_ai.get("comarca")),
            "representado_municipio": representado_ai["municipio"],
            "tipo_escrito": tipo_escrito,
            "expongo": expongo,
            "solicito": solicita,
            "archivos": list(archivos),
            "acreditacion_path": self._clean(src.get("acreditacion_path")),
            "headless": bool(src.get("headless", True)),
            "payload": dict(src),
        }

    def create_target(self, **kwargs) -> ServeiCatTransTarget:
        archivos = kwargs.get("archivos") or []
        if isinstance(archivos, str):
            archivos = [archivos]

        payload = kwargs.get("payload") if isinstance(kwargs.get("payload"), dict) else {}
        merged_payload = dict(payload)
        for key, value in kwargs.items():
            if key == "payload":
                continue
            merged_payload[key] = value

        direccion_tipo_via = self._clean(kwargs.get("direccion_tipo_via")) or "Ronda"
        direccion_nombre_via = self._clean(kwargs.get("direccion_nombre_via")) or "DEL GENERAL MITRE"
        direccion_numero = self._clean(kwargs.get("direccion_numero")) or "169"
        direccion_cp = self._clean(kwargs.get("direccion_cp")) or "08022"
        direccion_provincia = self._clean(kwargs.get("direccion_provincia")) or "Barcelona"
        direccion_comarca = self._clean(kwargs.get("direccion_comarca")) or "Barcelon\u00e8s"
        direccion_municipio = self._clean(kwargs.get("direccion_municipio")) or "BARCELONA"

        target = ServeiCatTransTarget(
            idRecurso=kwargs.get("idRecurso"),
            idExp=kwargs.get("idExp"),
            numclient=kwargs.get("numclient"),
            expediente=str(kwargs.get("expediente") or ""),
            servicio_territorial=self._clean(kwargs.get("servicio_territorial")),
            expediente_numero=self._clean(kwargs.get("expediente_numero")),
            digito_control=self._clean(kwargs.get("digito_control")),
            codigo_personal=self._clean(kwargs.get("codigo_personal")),
            tipo_persona=self._clean(kwargs.get("tipo_persona")) or "fisica",
            nombre=self._clean(kwargs.get("nombre")),
            apellido1=self._clean(kwargs.get("apellido1")),
            apellido2=self._clean(kwargs.get("apellido2")),
            nif=self._ensure_nif_nie_letter(kwargs.get("nif")),
            razon_social=self._clean(kwargs.get("razon_social")),
            nif_empresa=self._sanitize_document(kwargs.get("nif_empresa")),
            email=self._clean(kwargs.get("email")) or get_default_contact_email(),
            telefono_movil=self._clean(kwargs.get("telefono_movil")) or get_default_contact_mobile(),
            direccion_tipo_via=direccion_tipo_via,
            direccion_nombre_via=direccion_nombre_via,
            direccion_numero=direccion_numero,
            direccion_cp=direccion_cp,
            direccion_provincia=direccion_provincia,
            direccion_comarca=direccion_comarca,
            direccion_municipio=direccion_municipio,
            representado_tipo_via=self._clean(kwargs.get("representado_tipo_via")),
            representado_nombre_via=self._clean(kwargs.get("representado_nombre_via")),
            representado_numero=self._clean(kwargs.get("representado_numero")),
            representado_cp=self._clean(kwargs.get("representado_cp")),
            representado_provincia=self._clean(kwargs.get("representado_provincia")),
            representado_comarca=self._clean(kwargs.get("representado_comarca")),
            representado_municipio=self._clean(kwargs.get("representado_municipio")),
            tipo_escrito=self._clean(kwargs.get("tipo_escrito")) or "alegaciones",
            expongo=self._clean(kwargs.get("expongo")),
            solicito=self._clean(kwargs.get("solicito")),
            archivos_para_subir=[Path(str(p)) for p in archivos if str(p).strip()],
            payload=merged_payload,
            headless=bool(kwargs.get("headless", True)),
        )
        logger.info(
            "create_target representado final: via=%r nombre_via=%r numero=%r cp=%r provincia=%r comarca=%r municipio=%r",
            target.representado_tipo_via,
            target.representado_nombre_via,
            target.representado_numero,
            target.representado_cp,
            target.representado_provincia,
            target.representado_comarca,
            target.representado_municipio,
        )
        return target


def get_controller() -> ServeiCatTransController:
    return ServeiCatTransController()
