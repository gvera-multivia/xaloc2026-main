from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import uuid
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv

from core.client_documentation import check_requires_gesdoc
from core.contact_defaults import get_default_contact_email
from core.pg_control_plane_store import PgControlPlaneStore
from core.realtime_store import build_realtime_store
from core.redis_client import get_redis_client
from shared.queue import RedisStreamsClient

load_dotenv()
logger = logging.getLogger("payload_validator_service")


class PayloadValidatorService:
    def __init__(self):
        redis = get_redis_client()
        if redis is None:
            raise RuntimeError("Redis requerido para payload-validator-service.")
        self.redis = redis
        self.streams = RedisStreamsClient(redis, logger=logger)
        self.store = PgControlPlaneStore.from_env(logger=logger)
        self.realtime_store = build_realtime_store(logger=logger)

        self.candidates_stream = (os.getenv("CANDIDATES_STREAM_KEY") or "candidates").strip() or "candidates"
        self.validated_stream = (os.getenv("VALIDATED_STREAM_KEY") or "validated").strip() or "validated"
        self.dlq_candidates = (os.getenv("DLQ_CANDIDATES_STREAM_KEY") or "dlq:candidates").strip() or "dlq:candidates"
        self.group = (os.getenv("VALIDATOR_STREAM_GROUP") or "validator_group").strip() or "validator_group"
        self.consumer = (os.getenv("VALIDATOR_CONSUMER_NAME") or f"validator-{uuid.uuid4().hex[:8]}").strip()
        self.gesdoc_recheck_seconds = int((os.getenv("GESDOC_RECHECK_SECONDS") or "300").strip() or "300")
        self.gesdoc_recheck_batch = int((os.getenv("GESDOC_RECHECK_BATCH") or "25").strip() or "25")
        self.gesdoc_retry_zset = (os.getenv("GESDOC_RECHECK_ZSET_KEY") or "validator:gesdoc_recheck:zset").strip()
        self.gesdoc_retry_hash = (os.getenv("GESDOC_RECHECK_HASH_KEY") or "validator:gesdoc_recheck:payload").strip()

    @staticmethod
    def _safe_json(value: Any, default: Any) -> Any:
        if value is None:
            return default
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(str(value))
        except Exception:
            return default

    @staticmethod
    def _normalize_resource_id_str(value: Any) -> str:
        if value is None:
            return ""
        raw = str(value).strip()
        if not raw:
            return ""
        try:
            return str(int(raw))
        except Exception:
            pass
        try:
            as_float = float(raw)
            if as_float.is_integer():
                return str(int(as_float))
        except Exception:
            pass
        return raw

    @staticmethod
    def _to_int_like(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except Exception:
            pass
        try:
            as_float = float(str(value).strip())
            if as_float.is_integer():
                return int(as_float)
        except Exception:
            pass
        return None

    @staticmethod
    def _hydrate_payload_from_canonical(raw_payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(raw_payload or {})
        canonical = payload.get("__canonical_v1")
        if not isinstance(canonical, dict):
            return payload

        resource = canonical.get("resource") or {}
        client = canonical.get("client") or {}
        vehicle = canonical.get("vehicle") or {}
        client_doc = client.get("document") or {}
        client_name = client.get("name") or {}
        client_contact = client.get("contact") or {}
        client_address = client.get("address") or {}
        plate = (vehicle.get("plate") or {}).get("value")

        defaults = {
            "idRecurso": resource.get("id"),
            "idExp": resource.get("exp_id"),
            "numclient": resource.get("numclient"),
            "expediente": resource.get("expedient"),
            "Expedient": resource.get("expedient"),
            "expediente_num": resource.get("expedient"),
            "num_expediente": resource.get("expedient"),
            "denuncia_num": resource.get("expedient"),
            "num_denuncia": resource.get("expedient"),
            "sujeto_recurso": resource.get("subject_name"),
            "SujetoRecurso": resource.get("subject_name"),
            "fase_procedimiento": resource.get("phase"),
            "FaseProcedimiento": resource.get("phase"),
            "empresa": client_name.get("business"),
            "cif": client_doc.get("cif"),
            "cliente_nif": client_doc.get("nif"),
            "cliente_nif_empresa": client_doc.get("cif"),
            "cliente_tipo": client.get("type"),
            "cliente_nombre": client_name.get("first"),
            "cliente_apellido1": client_name.get("last1"),
            "cliente_apellido2": client_name.get("last2"),
            "cliente_razon_social": client_name.get("business"),
            "cliente_provincia": client_address.get("province"),
            "cliente_municipio": client_address.get("city"),
            "cliente_domicilio": client_address.get("street_name"),
            "cliente_numero": client_address.get("number"),
            "cliente_planta": client_address.get("floor"),
            "cliente_puerta": client_address.get("door"),
            "cliente_cp": client_address.get("zip"),
            "cliente_email": client_contact.get("email"),
            "email": client_contact.get("email"),
            "user_email": client_contact.get("email"),
            "cliente_tel1": client_contact.get("phone1"),
            "cliente_tel2": client_contact.get("phone2"),
            "cliente_movil": client_contact.get("mobile"),
            "name": client_name.get("first"),
            "apellido1": client_name.get("last1"),
            "apellido2": client_name.get("last2"),
            "razon_social": client_name.get("business"),
            "matricula": plate,
            "plate_number": plate,
        }
        for key, value in defaults.items():
            if payload.get(key) in (None, "", []):
                payload[key] = value
        return payload

    @staticmethod
    def _canonical_phase(raw_payload: dict[str, Any]) -> str:
        canonical = raw_payload.get("__canonical_v1")
        if not isinstance(canonical, dict):
            return ""
        resource = canonical.get("resource") or {}
        return str(resource.get("phase") or "").strip()

    @staticmethod
    def _ensure_default_emails(payload: dict[str, Any]) -> dict[str, Any]:
        out = dict(payload or {})
        default_email = get_default_contact_email()
        if out.get("email") in (None, "", []):
            out["email"] = default_email
        if out.get("user_email") in (None, "", []):
            out["user_email"] = str(out.get("email") or default_email)
        return out

    def _normalize_payload(self, raw_payload: dict[str, Any]) -> dict[str, Any]:
        payload = self._hydrate_payload_from_canonical(raw_payload)
        return self._ensure_default_emails(payload)

    @staticmethod
    def _normalize_job_type(raw_payload: dict[str, Any]) -> str:
        protocol = str(raw_payload.get("protocol") or "").strip().upper()
        if protocol:
            return protocol
        naturaleza = str(raw_payload.get("naturaleza") or "").strip().upper()
        if naturaleza:
            return naturaleza
        fase = str(
            raw_payload.get("FaseProcedimiento")
            or raw_payload.get("fase_procedimiento")
            or PayloadValidatorService._canonical_phase(raw_payload)
            or ""
        ).strip().lower()
        if "identificacion" in fase:
            return "P1"
        if "denuncia" in fase or "aleg" in fase:
            return "P2"
        return "GENERIC"

    @staticmethod
    def _incident_type_for_gesdoc_reason(reason: str | None) -> str:
        text = str(reason or "").strip().lower()
        if not text:
            return "REQUIRES_GESDOC"
        if "carpeta de documentaci" in text and "no existe" in text:
            return "CLIENT_FOLDER_NOT_FOUND"
        if "no se encontr" in text and "autorizaci" in text:
            return "CLIENT_AUTHORIZATION_MISSING"
        if "compartido de clientes inaccesible" in text or "compartido de clientes vac" in text:
            return "CLIENT_DOCS_SHARE_UNAVAILABLE"
        if "no se pudo inferir identidad del cliente" in text:
            return "CLIENT_IDENTITY_UNRESOLVED"
        return "REQUIRES_GESDOC"

    def _gesdoc_retry_key(self, *, site_id: str, resource_id: int | None, dedup_key: str) -> str:
        site = str(site_id or "").strip().lower() or "unknown"
        if resource_id is not None:
            return f"{site}:{int(resource_id)}"
        return f"{site}:dedup:{dedup_key or uuid.uuid4().hex}"

    async def _schedule_gesdoc_recheck(
        self,
        *,
        site_id: str,
        resource_id: int | None,
        incident_type: str,
        reason: str,
        normalized_payload: dict[str, Any],
        dedup_key: str,
        trace_id: str,
        check_in_seconds: int | None = None,
    ) -> None:
        delay = int(check_in_seconds or self.gesdoc_recheck_seconds)
        now = datetime.now(timezone.utc)
        next_ts = now.timestamp() + max(60, delay)
        retry_key = self._gesdoc_retry_key(site_id=site_id, resource_id=resource_id, dedup_key=dedup_key)
        item = {
            "site_id": site_id,
            "resource_id": resource_id,
            "incident_type": incident_type,
            "reason": reason,
            "normalized_payload": normalized_payload,
            "dedup_key": dedup_key,
            "trace_id": trace_id,
            "scheduled_at": now.isoformat(),
            "next_check_at": datetime.fromtimestamp(next_ts, tz=timezone.utc).isoformat(),
        }
        await self.redis.hset(self.gesdoc_retry_hash, retry_key, json.dumps(item, ensure_ascii=False))
        await self.redis.zadd(self.gesdoc_retry_zset, {retry_key: float(next_ts)})

    async def _remove_gesdoc_recheck(self, retry_key: str) -> None:
        await self.redis.zrem(self.gesdoc_retry_zset, retry_key)
        await self.redis.hdel(self.gesdoc_retry_hash, retry_key)

    async def _process_due_gesdoc_rechecks(self) -> int:
        now_ts = datetime.now(timezone.utc).timestamp()
        try:
            due_keys = await self.redis.zrangebyscore(
                self.gesdoc_retry_zset,
                min="-inf",
                max=now_ts,
                start=0,
                num=max(1, self.gesdoc_recheck_batch),
            )
        except Exception as exc:
            logger.warning("[payload-validator] No se pudieron leer rechecks GESDOC programados: %s", exc)
            return 0
        if not due_keys:
            return 0

        processed = 0
        for retry_key in due_keys:
            raw = await self.redis.hget(self.gesdoc_retry_hash, retry_key)
            if not raw:
                await self.redis.zrem(self.gesdoc_retry_zset, retry_key)
                continue
            try:
                item = json.loads(raw)
            except Exception:
                await self._remove_gesdoc_recheck(str(retry_key))
                continue

            site_id = str(item.get("site_id") or "").strip()
            normalized_payload = item.get("normalized_payload") or {}
            if not isinstance(normalized_payload, dict) or not site_id:
                await self._remove_gesdoc_recheck(str(retry_key))
                continue

            resource_id = self._to_int_like(item.get("resource_id"))
            if resource_id is None:
                resource_id = self._to_int_like(normalized_payload.get("idRecurso"))
            normalized_payload = self._normalize_payload(normalized_payload)

            requires_gesdoc, gesdoc_reason = check_requires_gesdoc(normalized_payload)
            if requires_gesdoc:
                reason_text = (gesdoc_reason or "").strip() or "Requiere autorizacion GESDOC"
                incident_type = self._incident_type_for_gesdoc_reason(reason_text)
                old_incident_type = str(item.get("incident_type") or "")
                if old_incident_type and old_incident_type != incident_type:
                    self.realtime_store.clear_incident(
                        site_id=site_id,
                        resource_id=resource_id,
                        incident_type=old_incident_type,
                    )
                expediente = str(
                    normalized_payload.get("expediente")
                    or normalized_payload.get("expediente_num")
                    or normalized_payload.get("nExp")
                    or ""
                ).strip()
                self.realtime_store.record_incident_once(
                    site_id=site_id,
                    incident_type=incident_type,
                    reason=reason_text,
                    resource_id=resource_id,
                    expediente=expediente or None,
                    payload=normalized_payload,
                    error_code=incident_type,
                    status="NEW",
                )
                await self._schedule_gesdoc_recheck(
                    site_id=site_id,
                    resource_id=resource_id,
                    incident_type=incident_type,
                    reason=reason_text,
                    normalized_payload=normalized_payload,
                    dedup_key=str(item.get("dedup_key") or ""),
                    trace_id=str(item.get("trace_id") or uuid.uuid4()),
                )
                processed += 1
                continue

            job_type = self._normalize_job_type(normalized_payload)
            cert_profile = str(normalized_payload.get("cert_profile") or "default").strip() or "default"
            priority_raw = normalized_payload.get("priority")
            try:
                priority = int(priority_raw) if priority_raw is not None else 100
            except Exception:
                priority = 100
            external_resource_id = self._normalize_resource_id_str(
                normalized_payload.get("external_resource_id") or normalized_payload.get("idRecurso")
            )
            dedup_key = self.store.build_dedup_key(
                organism_id=site_id,
                external_resource_id=external_resource_id,
                job_type=job_type,
            )
            trace_id = str(item.get("trace_id") or normalized_payload.get("trace_id") or uuid.uuid4())
            payload_to_queue = {
                **normalized_payload,
                "trace_id": trace_id,
                "organism_id": site_id,
                "external_resource_id": external_resource_id,
                "job_type": job_type,
                "cert_profile": cert_profile,
                "priority": priority,
                "dedup_key": dedup_key,
                "validated_at": datetime.now(timezone.utc).isoformat(),
            }
            draft = self.store.save_job_draft(
                organism_id=site_id,
                external_resource_id=payload_to_queue["external_resource_id"],
                job_type=job_type,
                cert_profile=cert_profile,
                priority=priority,
                dedup_key=dedup_key,
                normalized_payload=payload_to_queue,
                trace_id=trace_id,
            )
            await self.streams.publish_json(
                stream=self.validated_stream,
                payload={
                    "job_draft_id": draft["draft_id"],
                    "organism_id": site_id,
                    "job_type": job_type,
                    "cert_profile": cert_profile,
                    "priority": priority,
                    "normalized_payload": payload_to_queue,
                    "dedup_key": dedup_key,
                    "trace_id": trace_id,
                },
                maxlen=int((os.getenv("VALIDATED_STREAM_MAXLEN") or "200000").strip() or "200000"),
            )
            self.realtime_store.clear_incident(
                site_id=site_id,
                resource_id=resource_id,
                incident_type=str(item.get("incident_type") or ""),
            )
            await self._remove_gesdoc_recheck(str(retry_key))
            processed += 1

        return processed

    async def run_once(self) -> bool:
        deferred_processed = await self._process_due_gesdoc_rechecks()
        await self.streams.ensure_group(stream=self.candidates_stream, group=self.group)
        msg = await self.streams.read_group(
            stream=self.candidates_stream,
            group=self.group,
            consumer=self.consumer,
            block_ms=int((os.getenv("VALIDATOR_BLOCK_MS") or "5000").strip() or "5000"),
            count=1,
        )
        if msg is None:
            return deferred_processed > 0

        try:
            fields = msg.fields
            organism_id = str(fields.get("organism_id") or "").strip()
            external_resource_id = self._normalize_resource_id_str(fields.get("external_resource_id"))
            raw_payload = self._safe_json(fields.get("raw_payload"), {})
            trace_id = str(fields.get("trace_id") or "").strip() or str(uuid.uuid4())
            raw_payload = self._normalize_payload(raw_payload)

            if not organism_id:
                raise ValueError("candidate sin organism_id")

            job_type = self._normalize_job_type(raw_payload)
            cert_profile = str(raw_payload.get("cert_profile") or "default").strip() or "default"
            priority_raw = raw_payload.get("priority")
            try:
                priority = int(priority_raw) if priority_raw is not None else 100
            except Exception:
                priority = 100

            normalized_resource_id = self._normalize_resource_id_str(raw_payload.get("idRecurso"))
            dedup_key = self.store.build_dedup_key(
                organism_id=organism_id,
                external_resource_id=external_resource_id or normalized_resource_id,
                job_type=job_type,
            )

            normalized_payload = {
                **raw_payload,
                "trace_id": trace_id,
                "organism_id": organism_id,
                "external_resource_id": external_resource_id or normalized_resource_id,
                "job_type": job_type,
                "cert_profile": cert_profile,
                "priority": priority,
                "dedup_key": dedup_key,
                "validated_at": fields.get("claimed_at") or "",
            }

            disable_gesdoc = bool(normalized_payload.get("disable_gesdoc"))
            resource_for_auth = normalized_payload.get("idRecurso")
            if resource_for_auth is None:
                resource_for_auth = normalized_payload.get("external_resource_id")
            try:
                rid_for_auth = int(resource_for_auth) if resource_for_auth is not None else None
            except Exception:
                rid_for_auth = None

            if not disable_gesdoc:
                requires_gesdoc, gesdoc_reason = check_requires_gesdoc(normalized_payload)
                if requires_gesdoc:
                    reason_text = (gesdoc_reason or "").strip() or "Requiere autorizacion GESDOC"
                    expediente = str(
                        normalized_payload.get("expediente")
                        or normalized_payload.get("expediente_num")
                        or normalized_payload.get("nExp")
                        or ""
                    ).strip()
                    resource_id_for_incident = None
                    try:
                        resource_id_for_incident = int(rid_for_auth) if rid_for_auth is not None else None
                    except Exception:
                        resource_id_for_incident = None
                    incident_type = self._incident_type_for_gesdoc_reason(reason_text)
                    self.realtime_store.record_incident_once(
                        site_id=organism_id,
                        incident_type=incident_type,
                        reason=reason_text,
                        resource_id=resource_id_for_incident,
                        expediente=expediente or None,
                        payload=normalized_payload,
                        error_code=incident_type,
                        status="NEW",
                    )
                    await self._schedule_gesdoc_recheck(
                        site_id=organism_id,
                        resource_id=resource_id_for_incident,
                        incident_type=incident_type,
                        reason=reason_text,
                        normalized_payload=normalized_payload,
                        dedup_key=dedup_key,
                        trace_id=trace_id,
                    )
                    await self.streams.ack(stream=self.candidates_stream, group=self.group, message_id=msg.message_id)
                    return True

            if rid_for_auth is not None:
                self.realtime_store.clear_incident(
                    site_id=organism_id,
                    resource_id=rid_for_auth,
                )
            draft = self.store.save_job_draft(
                organism_id=organism_id,
                external_resource_id=normalized_payload["external_resource_id"],
                job_type=job_type,
                cert_profile=cert_profile,
                priority=priority,
                dedup_key=dedup_key,
                normalized_payload=normalized_payload,
                trace_id=trace_id,
            )
            validated_payload = {
                "job_draft_id": draft["draft_id"],
                "organism_id": organism_id,
                "job_type": job_type,
                "cert_profile": cert_profile,
                "priority": priority,
                "normalized_payload": normalized_payload,
                "dedup_key": dedup_key,
                "trace_id": trace_id,
            }
            await self.streams.publish_json(
                stream=self.validated_stream,
                payload=validated_payload,
                maxlen=int((os.getenv("VALIDATED_STREAM_MAXLEN") or "200000").strip() or "200000"),
            )
            await self.streams.ack(stream=self.candidates_stream, group=self.group, message_id=msg.message_id)
            return True
        except Exception as exc:
            logger.exception("Error validando candidate %s: %s", msg.message_id, exc)
            await self.streams.publish_json(
                stream=self.dlq_candidates,
                payload={
                    "source_message_id": msg.message_id,
                    "error": str(exc),
                    "fields": msg.fields,
                },
                maxlen=int((os.getenv("DLQ_STREAM_MAXLEN") or "200000").strip() or "200000"),
            )
            await self.streams.ack(stream=self.candidates_stream, group=self.group, message_id=msg.message_id)
            return True

    async def run_forever(self) -> None:
        shutdown = asyncio.Event()

        def _signal_handler():
            shutdown.set()

        loop = asyncio.get_running_loop()
        if os.name != "nt":
            try:
                loop.add_signal_handler(signal.SIGTERM, _signal_handler)
                loop.add_signal_handler(signal.SIGINT, _signal_handler)
            except NotImplementedError:
                pass

        while not shutdown.is_set():
            processed = await self.run_once()
            if not processed:
                await asyncio.sleep(0.2)


async def _main_async() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [payload-validator] %(levelname)s %(message)s")
    svc = PayloadValidatorService()
    await svc.run_forever()


def main() -> None:
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()

