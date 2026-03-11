from __future__ import annotations

from core.contact_defaults import get_default_contact_email
from services.payload_validator.app import PayloadValidatorService


def test_normalize_payload_is_canonical_only_and_sets_default_email() -> None:
    svc = PayloadValidatorService.__new__(PayloadValidatorService)
    out = svc._normalize_payload({"idRecurso": 123})
    assert out["email"] == get_default_contact_email()
    assert out["user_email"] == get_default_contact_email()


def test_normalize_payload_prefers_canonical_email() -> None:
    svc = PayloadValidatorService.__new__(PayloadValidatorService)
    out = svc._normalize_payload(
        {
            "__canonical_v1": {
                "client": {"contact": {"email": "canon@example.com"}},
            }
        }
    )
    assert out["email"] == "canon@example.com"
    assert out["user_email"] == "canon@example.com"
