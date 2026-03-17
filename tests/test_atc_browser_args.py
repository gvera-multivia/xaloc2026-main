from __future__ import annotations

import json
import logging
from pathlib import Path

from core import base_automation as base_automation_mod
from sites.atc.config import AtcConfig
from sites.atc.controller import AtcController


def _build_automation(tmp_path: Path) -> base_automation_mod.BaseAutomation:
    logger = logging.getLogger("xaloc_automation.atc")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    return base_automation_mod.BaseAutomation(AtcConfig())


def test_atc_browser_args_use_short_valid_aoc_pattern_for_cli_autoselect(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLAYWRIGHT_PROFILE_DIR", str(tmp_path / "profile"))
    monkeypatch.setenv("XALOC_CERT_AUTOSELECT_VIA_POLICY", "0")
    monkeypatch.delenv("XALOC_CERT_AUTOSELECT_PATTERN", raising=False)
    monkeypatch.delenv("XALOC_CERT_AUTOSELECT_RULES_JSON", raising=False)

    automation = _build_automation(tmp_path)

    args = automation._build_browser_args()

    cert_args = [arg for arg in args if arg.startswith("--auto-select-certificate-for-urls=")]
    assert len(cert_args) == 1
    assert '"pattern":"https://valid.aoc.cat/*"' in cert_args[0]
    assert "[*.]aoc.cat" not in cert_args[0]


def test_windows_policy_mode_skips_cli_autoselect_by_default(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLAYWRIGHT_PROFILE_DIR", str(tmp_path / "profile"))
    monkeypatch.setenv("XALOC_CERT_AUTOSELECT_VIA_POLICY", "1")
    monkeypatch.setenv("XALOC_CERT_AUTOSELECT_CLI_FALLBACK", "1")
    monkeypatch.delenv("XALOC_CERT_AUTOSELECT_PATTERN", raising=False)
    monkeypatch.delenv("XALOC_CERT_AUTOSELECT_RULES_JSON", raising=False)
    monkeypatch.setattr(base_automation_mod.os, "name", "nt")

    automation = _build_automation(tmp_path)

    args = automation._build_browser_args()

    assert not any(arg.startswith("--auto-select-certificate-for-urls=") for arg in args)


def test_windows_policy_mode_allows_explicit_cli_force(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLAYWRIGHT_PROFILE_DIR", str(tmp_path / "profile"))
    monkeypatch.setenv("XALOC_CERT_AUTOSELECT_VIA_POLICY", "1")
    monkeypatch.setenv("XALOC_CERT_AUTOSELECT_CLI_FALLBACK", "1")
    monkeypatch.setenv("XALOC_CERT_AUTOSELECT_FORCE_CLI_ON_WINDOWS", "1")
    monkeypatch.delenv("XALOC_CERT_AUTOSELECT_PATTERN", raising=False)
    monkeypatch.delenv("XALOC_CERT_AUTOSELECT_RULES_JSON", raising=False)
    monkeypatch.setattr(base_automation_mod.os, "name", "nt")

    automation = _build_automation(tmp_path)

    args = automation._build_browser_args()

    assert any(arg.startswith("--auto-select-certificate-for-urls=") for arg in args)


def test_windows_profile_sanitization_clears_crash_markers(monkeypatch, tmp_path: Path) -> None:
    profile_dir = tmp_path / "profile"
    sessions_dir = profile_dir / "Default" / "Sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / "Session_1").write_text("session", encoding="utf-8")
    (sessions_dir / "Tabs_1").write_text("tabs", encoding="utf-8")
    prefs_path = profile_dir / "Default" / "Preferences"
    prefs_path.write_text(
        json.dumps({"profile": {"exit_type": "Crashed"}, "session": {"restore_on_startup": 1}}),
        encoding="utf-8",
    )

    automation = _build_automation(tmp_path)
    monkeypatch.setattr(base_automation_mod.os, "name", "nt")

    automation._sanitize_windows_profile_before_launch(str(profile_dir))

    assert not any(sessions_dir.iterdir())
    prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
    assert prefs["profile"]["exit_type"] == "Normal"
    assert prefs["profile"]["exited_cleanly"] is True
    assert prefs["session"]["restore_on_startup"] == 5


def test_prepare_protocol_preferences_revokes_autofirma_pairs_when_auto_open_disabled(monkeypatch, tmp_path: Path) -> None:
    profile_dir = tmp_path / "profile"
    prefs_path = profile_dir / "Default" / "Preferences"
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    prefs_path.write_text(
        json.dumps(
            {
                "protocol_handler": {
                    "excluded_schemes": {"afirma": False, "xalocafirma": False},
                    "allowed_origin_protocol_pairs": [
                        {"protocol": "afirma", "origin": "https://sede.valencia.es"},
                        {"protocol": "xalocafirma", "origin": "https://sede.valencia.es"},
                        {"protocol": "mailto", "origin": "https://example.org"},
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PLAYWRIGHT_PROFILE_DIR", str(profile_dir))
    monkeypatch.setenv("XALOC_AUTOFIRMA_PROTOCOLS", "afirma,xalocafirma")
    monkeypatch.setenv("XALOC_AUTOFIRMA_ALLOWED_ORIGINS", "https://sede.valencia.es")

    automation = _build_automation(tmp_path)
    automation.config.autofirma_auto_open = False
    automation.config.autofirma_origin = "https://sede.valencia.es"

    automation._prepare_protocol_preferences(str(profile_dir))

    prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
    protocol_handler = prefs["protocol_handler"]
    assert protocol_handler["excluded_schemes"]["afirma"] is True
    assert protocol_handler["excluded_schemes"]["xalocafirma"] is True
    assert protocol_handler["allowed_origin_protocol_pairs"] == [
        {"protocol": "mailto", "origin": "https://example.org"}
    ]


def test_sanitize_managed_protocol_policies_removes_disabled_origins(monkeypatch, tmp_path: Path) -> None:
    managed_dir = tmp_path / "etc" / "chromium" / "policies" / "managed"
    managed_dir.mkdir(parents=True, exist_ok=True)
    policy_path = managed_dir / "xaloc-afirma-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "AutoLaunchProtocolsFromOrigins": [
                    {
                        "protocol": "afirma",
                        "allowed_origins": [
                            "https://sede.valencia.es",
                            "https://palma.sedipualba.es",
                        ],
                    },
                    {
                        "protocol": "xalocafirma",
                        "allowed_origins": [
                            "https://sede.valencia.es",
                        ],
                    },
                    {
                        "protocol": "mailto",
                        "allowed_origins": [
                            "https://example.org",
                        ],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    automation = _build_automation(tmp_path)
    automation.config.autofirma_auto_open = False
    automation.config.autofirma_origin = "https://sede.valencia.es"
    monkeypatch.setenv("XALOC_AUTOFIRMA_PROTOCOLS", "afirma,xalocafirma")
    monkeypatch.setenv("XALOC_AUTOFIRMA_ALLOWED_ORIGINS", "https://sede.valencia.es")

    original_path_class = base_automation_mod.Path

    def _mapped_path(value: str | Path) -> Path:
        value = str(value)
        if value == "/etc/chromium/policies/managed/xaloc-afirma-policy.json":
            return policy_path
        return original_path_class(value)

    monkeypatch.setattr(base_automation_mod, "Path", _mapped_path)

    automation._sanitize_managed_protocol_policies()

    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    assert policy["AutoLaunchProtocolsFromOrigins"] == [
        {
            "protocol": "afirma",
            "allowed_origins": ["https://palma.sedipualba.es"],
        },
        {
            "protocol": "mailto",
            "allowed_origins": ["https://example.org"],
        },
    ]


def test_atc_controller_defaults_contact_fields_when_missing() -> None:
    controller = AtcController()

    mapped = controller.map_data(
        {
            "expediente": "DIL20253811601",
            "procedim": "EMBARGO Persona Fisica BOP_21",
            "nif": "44416590W",
            "Nombre": "JORDI",
            "Apellido1": "GRISO",
            "Apellido2": "VILA",
            "email": "",
            "telefono": "",
        }
    )

    assert mapped["email"] == "info@xvia-serviciosjuridicos.com"
    assert mapped["telefono"] == "722761154"
