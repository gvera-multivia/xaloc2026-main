from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.autofirma_js import get_redsara_afirma_hook_script
from sites.valencia.flows import confirmacion


class _FakeFirePage:
    def __init__(self) -> None:
        self.url = "https://sede.valencia.es/presentarInstancia/"
        self.context = SimpleNamespace(request=object())
        self.submit_payload: dict[str, str] | None = None
        self.submit_script: str | None = None

    async def evaluate(self, script: str, arg=None):
        if "miniappletSuccessService" not in script:
            raise AssertionError(f"Unexpected evaluate call: {script[:120]}")
        self.submit_script = script
        self.submit_payload = arg
        return {
            "ok": True,
            "url": "https://sede.valencia.es/fire-signature/public/miniappletSuccessService",
        }

    async def wait_for_timeout(self, timeout_ms: int) -> None:
        _ = timeout_ms

    async def wait_for_load_state(self, state: str, timeout: int) -> None:
        _ = (state, timeout)


@pytest.mark.asyncio
async def test_execute_fire_signing_inprocess_submits_success_service_with_single_payload_arg(monkeypatch) -> None:
    async def _noop(*args, **kwargs) -> None:
        _ = (args, kwargs)

    async def _fake_execute_fire_signing(*args, **kwargs):
        _ = (args, kwargs)
        return SimpleNamespace(
            ok=True,
            error="",
            trace="ok",
            signature_b64="SIGNED_B64",
        )

    monkeypatch.setattr(confirmacion, "_capture_fire_runtime_state", _noop)
    monkeypatch.setattr(confirmacion, "_drain_fire_runtime_events", _noop)
    monkeypatch.setattr(confirmacion, "execute_fire_signing", _fake_execute_fire_signing)
    monkeypatch.setattr(confirmacion, "_extract_signing_cert_b64", lambda: "PFX+CERT/BASE64")
    monkeypatch.setattr(confirmacion, "_extract_cert_b64_from_signature", lambda signature_b64: "SIG+CERT/BASE64")

    telemetry = {"_last_afirma_uri": "afirma://sign?op=sign"}
    page = _FakeFirePage()

    await confirmacion._execute_fire_signing_inprocess(page, telemetry=telemetry)

    assert telemetry["_last_fire_signature_b64"] == "SIGNED_B64"
    assert page.submit_payload == {
        "signatureB64": "SIGNED_B64",
        "certB64": "SIG+CERT/BASE64",
    }
    assert "document.getElementById('formSign')" in (page.submit_script or "")
    assert "mode: 'existing_form'" in (page.submit_script or "")
    assert "isBatchOperation" in (page.submit_script or "")


def test_redsara_hook_covers_autoscript_document_location_and_iframe_attribute_paths() -> None:
    script = get_redsara_afirma_hook_script(block_external_launch=True)

    assert "window.__afirma_source" in script
    assert "wrapLocationProperty(Document.prototype, 'document.location')" in script
    assert "wrapLocationProperty(document, 'document.location.instance')" in script
    assert "Element.prototype.setAttributeNode" in script
    assert "setAttributeNode:" in script
    assert "HTMLIFrameElement.prototype" in script
