from __future__ import annotations

from sites.adapters.diputacio_bcn import DiputacioBcnAdapter


def test_has_direct_non_orgt_route_for_barcelona() -> None:
    organisme_urls = {
        "AJUNTAMENT DE BARCELONA": {
            "https://seuelectronica.ajuntament.barcelona.cat/APPS/portaltramits/formulari/ptbidcond/T142/init/ca/PTCIU.html"
        }
    }

    assert DiputacioBcnAdapter._has_direct_non_orgt_route("AJUNTAMENT DE BARCELONA", organisme_urls) is True


def test_has_direct_non_orgt_route_for_terrassa() -> None:
    organisme_urls = {
        "AYUNTAMIENTO DE TERRASSA": {
            "https://aoberta.terrassa.cat/tramits/fitxa.jsp?id=3821"
        }
    }

    assert DiputacioBcnAdapter._has_direct_non_orgt_route("AYUNTAMIENTO DE TERRASSA", organisme_urls) is True


def test_has_direct_non_orgt_route_is_false_for_orgt_only() -> None:
    organisme_urls = {
        "AJUNTAMENT DE SABADELL": {DiputacioBcnAdapter.ORGT_IDENTIFICACIO_URL}
    }

    assert DiputacioBcnAdapter._has_direct_non_orgt_route("AJUNTAMENT DE SABADELL", organisme_urls) is False


def test_has_direct_non_orgt_route_is_false_when_unknown() -> None:
    organisme_urls = {}

    assert DiputacioBcnAdapter._has_direct_non_orgt_route("ORGANISME DESCONEGUT", organisme_urls) is False
