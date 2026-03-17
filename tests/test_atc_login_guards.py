from __future__ import annotations

from sites.atc.flows.login import _is_auth_url, _is_post_auth_ready_url


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
