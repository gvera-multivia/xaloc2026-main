from __future__ import annotations

from services.brain_claim.processable_validator import validate_candidate


class _RuntimeStore:
    def is_resource_processing_paused(self, *, site_id: str, resource_id: int) -> bool:
        return False


class _AdminStore:
    def is_resource_blocked(self, *, site_id: str, resource_id: int) -> bool:
        return False


def test_validate_candidate_madrid_with_canonical_only_fields() -> None:
    candidate = {
        "__canonical_v1": {
            "resource": {
                "id": 5001,
                "expedient": "935/12345678.9",
                "phase": "Alegaciones",
            },
            "client": {
                "document": {"nif": "12345678Z", "cif": ""},
                "address": {"street_name": "CALLE MAYOR"},
            },
        }
    }
    out = validate_candidate(
        site_id="madrid",
        candidate=candidate,
        runtime_store=_RuntimeStore(),
        admin_store=_AdminStore(),
    )
    assert out.processable is True


def test_validate_candidate_base_p1_with_canonical_only_fields() -> None:
    candidate = {
        "__canonical_v1": {
            "resource": {
                "id": 5002,
                "expedient": "12345-2024/1234-GIM",
                "phase": "Identificacion del conductor",
                "subject_name": "JUAN PEREZ",
            },
            "client": {
                "document": {"nif": "12345678Z"},
                "address": {"street_name": "CALLE MAYOR"},
            },
        }
    }
    out = validate_candidate(
        site_id="base_online",
        candidate=candidate,
        runtime_store=_RuntimeStore(),
        admin_store=_AdminStore(),
    )
    assert out.processable is True
