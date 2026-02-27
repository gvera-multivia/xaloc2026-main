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
from core.pg_control_plane_store import PgControlPlaneStore
from core.pg_pending_authorization_store import PgPendingAuthorizationStore
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
        self.pending_auth_store = PgPendingAuthorizationStore.from_env(logger=logger)
        self.realtime_store = build_realtime_store(logger=logger)

        self.candidates_stream = (os.getenv("CANDIDATES_STREAM_KEY") or "candidates").strip() or "candidates"
        self.validated_stream = (os.getenv("VALIDATED_STREAM_KEY") or "validated").strip() or "validated"
        self.dlq_candidates = (os.getenv("DLQ_CANDIDATES_STREAM_KEY") or "dlq:candidates").strip() or "dlq:candidates"
        self.group = (os.getenv("VALIDATOR_STREAM_GROUP") or "validator_group").strip() or "validator_group"
        self.consumer = (os.getenv("VALIDATOR_CONSUMER_NAME") or f"validator-{uuid.uuid4().hex[:8]}").strip()

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
    def _normalize_job_type(raw_payload: dict[str, Any]) -> str:
        protocol = str(raw_payload.get("protocol") or "").strip().upper()
        if protocol:
            return protocol
        naturaleza = str(raw_payload.get("naturaleza") or "").strip().upper()
        if naturaleza:
            return naturaleza
        fase = str(raw_payload.get("FaseProcedimiento") or raw_payload.get("fase_procedimiento") or "").strip().lower()
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

    async def run_once(self) -> bool:
        await self.streams.ensure_group(stream=self.candidates_stream, group=self.group)
        msg = await self.streams.read_group(
            stream=self.candidates_stream,
            group=self.group,
            consumer=self.consumer,
            block_ms=int((os.getenv("VALIDATOR_BLOCK_MS") or "5000").strip() or "5000"),
            count=1,
        )
        if msg is None:
            return False

        try:
            fields = msg.fields
            organism_id = str(fields.get("organism_id") or "").strip()
            external_resource_id = self._normalize_resource_id_str(fields.get("external_resource_id"))
            raw_payload = self._safe_json(fields.get("raw_payload"), {})
            trace_id = str(fields.get("trace_id") or "").strip() or str(uuid.uuid4())

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
            # Si ya existe autorización previa para este site/recurso,
            # no volver a recrear pending-auth para el mismo ítem.
            resource_for_auth = normalized_payload.get("idRecurso")
            if resource_for_auth is None:
                resource_for_auth = normalized_payload.get("external_resource_id")
            try:
                rid_for_auth = int(resource_for_auth) if resource_for_auth is not None else None
            except Exception:
                rid_for_auth = None

            if rid_for_auth is not None and self.pending_auth_store.has_authorized_record(
                site_id=organism_id,
                resource_id=rid_for_auth,
            ):
                logger.info(
                    "[payload-validator] skip gesdoc pending recreation: site=%s resource_id=%s already moved_to_queue",
                    organism_id,
                    rid_for_auth,
                )
                disable_gesdoc = True

            if not disable_gesdoc:
                requires_gesdoc, gesdoc_reason = check_requires_gesdoc(normalized_payload)
                if requires_gesdoc:
                    reason_text = (gesdoc_reason or "").strip() or "Requiere autorizacion GESDOC"
                    self.pending_auth_store.insert_pending_authorization(
                        site_id=organism_id,
                        payload=normalized_payload,
                        authorization_type="gesdoc",
                        reason=reason_text,
                    )
                    expediente = str(
                        normalized_payload.get("expediente")
                        or normalized_payload.get("expediente_num")
                        or normalized_payload.get("nExp")
                        or ""
                    ).strip()
                    resource_id_for_incident = None
                    try:
                        resource_id_for_incident = (
                            int(rid_for_auth) if rid_for_auth is not None else None
                        )
                    except Exception:
                        resource_id_for_incident = None
                    incident_type = self._incident_type_for_gesdoc_reason(reason_text)
                    created = self.realtime_store.record_incident_once(
                        site_id=organism_id,
                        incident_type=incident_type,
                        reason=reason_text,
                        resource_id=resource_id_for_incident,
                        expediente=expediente or None,
                        payload=normalized_payload,
                        error_code=incident_type,
                        status="NEW",
                    )
                    if created:
                        # Best-effort realtime event so Electron can notify immediately.
                        try:
                            await self.redis.publish(
                                "channel:ui_updates",
                                json.dumps(
                                    {
                                        "type": "incident.new",
                                        "timestamp": datetime.now(timezone.utc).isoformat(),
                                        "data": {
                                            "site_id": organism_id,
                                            "incident_type": incident_type,
                                            "error_code": incident_type,
                                            "reason": reason_text,
                                            "resource_id": resource_id_for_incident,
                                            "expediente": expediente or None,
                                        },
                                    },
                                    ensure_ascii=False,
                                ),
                            )
                        except Exception as exc:
                            logger.debug(
                                "[payload-validator] No se pudo publicar evento realtime de incidencia: %s",
                                exc,
                            )
                    await self.streams.ack(stream=self.candidates_stream, group=self.group, message_id=msg.message_id)
                    return True

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
