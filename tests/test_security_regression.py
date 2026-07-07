import io
import os
import tarfile
import zipfile
from types import SimpleNamespace

import pytest

import web.hooks as hooks_mod
import web.oauth as oauth_mod
import web.ollama_local as ollama_mod


class DummyRequest:
    def __init__(self, *, headers=None, query_params=None, cookies=None):
        self.headers = headers or {}
        self.query_params = query_params or {}
        self.cookies = cookies or {}


def test_hook_requests_are_not_public_by_default(monkeypatch):
    monkeypatch.delenv("OMBRE_HOOK_TOKEN", raising=False)
    monkeypatch.delenv("OMBRE_HOOK_ALLOW_PUBLIC", raising=False)
    hooks_mod.sh.config = {"hooks": {}}

    assert hooks_mod._is_hook_request_authorized(DummyRequest()) is False


def test_hook_requests_accept_configured_token(monkeypatch):
    monkeypatch.setenv("OMBRE_HOOK_TOKEN", "secret-token")
    monkeypatch.delenv("OMBRE_HOOK_ALLOW_PUBLIC", raising=False)
    hooks_mod.sh.config = {"hooks": {}}

    assert hooks_mod._is_hook_request_authorized(
        DummyRequest(query_params={"token": "secret-token"})
    ) is True
    assert hooks_mod._is_hook_request_authorized(
        DummyRequest(headers={"x-ombre-hook-token": "secret-token"})
    ) is True
    assert hooks_mod._is_hook_request_authorized(
        DummyRequest(headers={"authorization": "Bearer secret-token"})
    ) is True
    assert hooks_mod._is_hook_request_authorized(
        DummyRequest(query_params={"token": "wrong-token"})
    ) is False


def test_hook_requests_can_be_explicitly_public(monkeypatch):
    monkeypatch.delenv("OMBRE_HOOK_TOKEN", raising=False)
    monkeypatch.setenv("OMBRE_HOOK_ALLOW_PUBLIC", "1")
    hooks_mod.sh.config = {"hooks": {}}

    assert hooks_mod._is_hook_request_authorized(DummyRequest()) is True


def test_oauth_authorize_rejects_unknown_client_redirect():
    oauth_mod._oauth_clients.clear()

    ok, error = oauth_mod._validate_authorize_redirect(
        "unknown-client",
        "https://attacker.example/callback",
    )

    assert ok is False
    assert "client_id" in error


def test_oauth_authorize_requires_exact_registered_redirect():
    oauth_mod._oauth_clients.clear()
    oauth_mod._oauth_clients["client-1"] = {
        "redirect_uris": ["https://legit.example/callback"],
        "client_name": "Legit",
    }

    ok, _ = oauth_mod._validate_authorize_redirect(
        "client-1",
        "https://legit.example/callback",
    )
    bad_ok, bad_error = oauth_mod._validate_authorize_redirect(
        "client-1",
        "https://attacker.example/callback",
    )

    assert ok is True
    assert bad_ok is False
    assert "redirect_uri" in bad_error


def test_safe_zip_extract_rejects_path_traversal(tmp_path):
    dest = tmp_path / "extract"
    dest.mkdir()
    outside = tmp_path / "escape.txt"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../escape.txt", "owned")
    buf.seek(0)

    with zipfile.ZipFile(buf) as zf:
        with pytest.raises(ValueError):
            ollama_mod._safe_extract_zip(zf, str(dest))

    assert not outside.exists()


def test_safe_tar_extract_rejects_path_traversal(tmp_path):
    dest = tmp_path / "extract"
    dest.mkdir()
    outside = tmp_path / "escape.txt"
    buf = io.BytesIO()
    payload = b"owned"
    info = tarfile.TarInfo("../escape.txt")
    info.size = len(payload)
    with tarfile.open(fileobj=buf, mode="w") as tf:
        tf.addfile(info, io.BytesIO(payload))
    buf.seek(0)

    with tarfile.open(fileobj=buf, mode="r") as tf:
        with pytest.raises(ValueError):
            ollama_mod._safe_extract_tar(tf, str(dest))

    assert not outside.exists()


def test_ollama_download_rejects_non_http_url():
    with pytest.raises(ValueError):
        ollama_mod._validate_download_url("file:///tmp/ollama.tar.zst")
