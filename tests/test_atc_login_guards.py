from __future__ import annotations

import pytest

from sites.atc.flows.login import (
    ATC_LOGIN_ENTRY_TIMEOUT_MS,
    _is_auth_url,
    _pick_auth_page,
    _is_post_auth_ready_url,
    _is_reposicio_public_url,
)


def test_atc_login_detects_valid_auth_urls() -> None:
    assert _is_auth_url("https://valid.aoc.cat/idcatmobil")
    assert _is_auth_url("https://example.com/o/oauth2/auth?client_id=1")
    assert _is_auth_url("https://example.com/saml2/post/sso")


def test_atc_login_detects_post_auth_ready_urls() -> None:
    assert _is_post_auth_ready_url("https://seu2.atc.gencat.cat/ca/secured/recurs/identificacio")
    assert _is_post_auth_ready_url("https://seu2.atc.gencat.cat/ca/secured/reas/identificacio")
    assert _is_post_auth_ready_url("https://seu.atc.gencat.cat/es/OficinaVirtual/Paginas/TramitsGenerics.aspx")


def test_atc_login_does_not_confuse_public_pages_with_auth_states() -> None:
    assert not _is_auth_url("https://atc.gencat.cat/ca/gestions/impugnacions/recurs/")
    assert not _is_post_auth_ready_url("https://atc.gencat.cat/ca/gestions/impugnacions/recurs/index.html?moda=1")


def test_atc_login_detects_public_reposicio_landing_urls() -> None:
    assert _is_reposicio_public_url("https://atc.gencat.cat/ca/gestions/impugnacions/recurs/index.html?moda=1&detail=1")
    assert _is_reposicio_public_url("https://atc.gencat.cat/ca/gestions/impugnacions/recurs/")
    assert not _is_reposicio_public_url("https://seu2.atc.gencat.cat/ca/secured/recurs/identificacio")


def test_atc_login_reposicio_entry_timeout_is_shorter_than_full_auth_timeout() -> None:
    assert ATC_LOGIN_ENTRY_TIMEOUT_MS < 120000


class _FakePage:
    def __init__(self, url: str, *, closed: bool = False) -> None:
        self.url = url
        self._closed = closed

    def is_closed(self) -> bool:
        return self._closed


class _FakeContext:
    def __init__(self, pages: list[_FakePage]) -> None:
        self.pages = pages


@pytest.mark.asyncio
async def test_atc_pick_auth_page_prefers_post_auth_page_over_stale_login_tab() -> None:
    stale_auth = _FakePage("https://autenticaciogicar5.extranet.gencat.cat/idp/profile/SAML2/POST/SSO?execution=e1s1")
    ready_form = _FakePage("https://seu2.atc.gencat.cat/ca/secured/recurs/identificacio")
    context = _FakeContext([stale_auth, ready_form])

    picked = await _pick_auth_page(context, stale_auth)

    assert picked is ready_form
