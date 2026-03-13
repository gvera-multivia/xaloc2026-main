from __future__ import annotations

from typing import Any

from core.domain import ResourceDomain


CORE_COMPARE_KEYS = (
    "idRecurso",
    "idExp",
    "Expedient",
    "Organisme",
    "TExp",
    "Estado",
    "numclient",
    "SujetoRecurso",
    "FaseProcedimiento",
    "UsuarioAsignado",
)


def _by_id(resources: list[ResourceDomain]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for item in resources:
        try:
            rid = int(item.id)
        except Exception:
            continue
        out[rid] = dict(item.metadata or {})
    return out


def compare_resources_for_parity(
    *,
    legacy_resources: list[ResourceDomain],
    consultor_resources: list[ResourceDomain],
    compare_keys: tuple[str, ...] = CORE_COMPARE_KEYS,
) -> dict[str, Any]:
    legacy = _by_id(legacy_resources)
    consultor = _by_id(consultor_resources)

    legacy_ids = set(legacy.keys())
    consultor_ids = set(consultor.keys())

    only_legacy = sorted(legacy_ids - consultor_ids)
    only_consultor = sorted(consultor_ids - legacy_ids)

    mismatches: list[dict[str, Any]] = []
    for rid in sorted(legacy_ids & consultor_ids):
        left = legacy[rid]
        right = consultor[rid]
        diff_fields: list[dict[str, Any]] = []
        for key in compare_keys:
            if left.get(key) != right.get(key):
                diff_fields.append(
                    {
                        "field": key,
                        "legacy": left.get(key),
                        "consultor": right.get(key),
                    }
                )
        if diff_fields:
            mismatches.append({"idRecurso": rid, "diffs": diff_fields})

    return {
        "legacy_count": len(legacy),
        "consultor_count": len(consultor),
        "only_legacy": only_legacy,
        "only_consultor": only_consultor,
        "mismatches": mismatches,
        "ok": not only_legacy and not only_consultor and not mismatches,
    }

