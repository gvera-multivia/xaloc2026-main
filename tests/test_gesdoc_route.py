from __future__ import annotations

import os
import sys

sys.path.append(os.getcwd())

from core.gesdoc_auth import (
    extract_gesdoc_action_links,
    extract_gesdoc_logged_user,
    extract_gesdoc_sent_requests,
    search_client_in_gesdoc,
)


class _FakeResponse:
    def __init__(self, html: str) -> None:
        self.status = 200
        self.url = "http://gesdoc.xvia/gesdoc/index.php"
        self._html = html

    async def text(self) -> str:
        return self._html

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeSession:
    def __init__(self, html: str) -> None:
        self._html = html

    def post(self, *_args, **_kwargs) -> _FakeResponse:
        return _FakeResponse(self._html)


def test_gesdoc_extract_helpers_detect_login_and_sent_request() -> None:
    html = """
    <html><body>
    <span class="d-none d-md-inline">Hola LOURDES GARCIA <a href="cerrarsesion.php"> - Salir - </a></span>
    <div class='alert alert-light alert-dismissible'><strong>Solicitud Enviada el 29-01-26</strong></div>
    <div class='alert alert-light alert-dismissible'><strong>Solicitud Enviada el 30-03-26</strong></div>
    </body></html>
    """

    assert extract_gesdoc_logged_user(html) == "LOURDES GARCIA"
    assert extract_gesdoc_sent_requests(html) == ["29-01-26", "30-03-26"]


def test_gesdoc_extract_action_links_detects_three_buttons() -> None:
    html = """
    <html><body>
    <a href='carta.php?cliente=43880&plantilla=10101'><button type='button'>Solicitar</button></a>
    <a href='generarautorizaciones.php?cliente=43880&plantilla=1'><button type='button'>Generar PDF Autoriz. Emp. sin enviar</button></a>
    <a href='generarautorizaciones.php?cliente=43880&plantilla=2'><button type='button'>Generar PDF Autoriz. Part. sin enviar</button></a>
    </body></html>
    """

    assert extract_gesdoc_action_links(html, 43880) == {
        "send": "http://gesdoc.xvia/gesdoc/carta.php?cliente=43880&plantilla=10101",
        "generate_company": "http://gesdoc.xvia/gesdoc/generarautorizaciones.php?cliente=43880&plantilla=1",
        "generate_particular": "http://gesdoc.xvia/gesdoc/generarautorizaciones.php?cliente=43880&plantilla=2",
    }


async def _run_search(html: str) -> dict:
    return await search_client_in_gesdoc(_FakeSession(html), 43880)


def test_search_client_in_gesdoc_returns_structured_result() -> None:
    import asyncio

    html = """
    <html><body>
    <span class="d-none d-md-inline">Hola LOURDES GARCIA <a href="cerrarsesion.php"> - Salir - </a></span>
    <p>Num. Cliente: <b>43880</b></p>
    <div class='alert alert-light alert-dismissible'><strong>Solicitud Enviada el 29-01-26</strong></div>
    <a href='carta.php?cliente=43880&plantilla=10101'><button type='button'>Solicitar</button></a>
    <a href='generarautorizaciones.php?cliente=43880&plantilla=1'><button type='button'>Generar PDF Autoriz. Emp. sin enviar</button></a>
    <a href='generarautorizaciones.php?cliente=43880&plantilla=2'><button type='button'>Generar PDF Autoriz. Part. sin enviar</button></a>
    </body></html>
    """

    result = asyncio.run(_run_search(html))

    assert result["status_code"] == 200
    assert result["final_url"] == "http://gesdoc.xvia/gesdoc/index.php"
    assert result["logged_user"] == "LOURDES GARCIA"
    assert result["has_client_number"] is True
    assert result["has_sent_request"] is True
    assert result["sent_request_entries"] == ["29-01-26"]
    assert result["action_links"]["send"].endswith("carta.php?cliente=43880&plantilla=10101")
    assert result["action_links"]["generate_company"].endswith("generarautorizaciones.php?cliente=43880&plantilla=1")
    assert result["action_links"]["generate_particular"].endswith("generarautorizaciones.php?cliente=43880&plantilla=2")
