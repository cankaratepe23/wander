import time
from dataclasses import dataclass

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.auth import AccessVerifier
from app.config import Settings
from app.main import create_app

TEAM = "example.cloudflareaccess.com"
AUD = "test-aud-tag"


@dataclass
class _Key:
    key: object


class FakeJWKS:
    """Stands in for PyJWKClient, which would fetch keys from the Access team domain."""

    def __init__(self, public_key):
        self.public_key = public_key

    def get_signing_key_from_jwt(self, _token):
        return _Key(self.public_key)


@pytest.fixture
def keypair():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private, private.public_key()


def make_token(private_key, **claims) -> str:
    now = int(time.time())
    base = {"aud": AUD, "iss": f"https://{TEAM}", "iat": now, "exp": now + 300}
    return jwt.encode(base | claims, private_key, algorithm="RS256")


@pytest.fixture
def access_client(tmp_path, keypair):
    settings = Settings(
        data_dir=tmp_path,
        access_team_domain=TEAM,
        access_aud=AUD,
        allowed_emails="alex@example.com, sam@example.com",
    )
    app = create_app(settings)
    app.state.access_verifier = AccessVerifier(TEAM, AUD, jwks_client=FakeJWKS(keypair[1]))
    with TestClient(app) as c:
        yield c


def test_valid_token_is_accepted(access_client, keypair):
    token = make_token(keypair[0], email="Alex@Example.com")
    r = access_client.get("/api/me", headers={"Cf-Access-Jwt-Assertion": token})
    assert r.status_code == 200
    assert r.json()["email"] == "alex@example.com"


def test_cookie_is_accepted_too(access_client, keypair):
    access_client.cookies.set("CF_Authorization", make_token(keypair[0], email="sam@example.com"))
    assert access_client.get("/api/me").status_code == 200


def test_missing_token_is_refused(access_client):
    assert access_client.get("/api/me").status_code == 401


def test_wrong_audience_is_refused(access_client, keypair):
    token = make_token(keypair[0], email="alex@example.com", aud="another-app")
    assert (
        access_client.get("/api/me", headers={"Cf-Access-Jwt-Assertion": token}).status_code == 401
    )


def test_expired_token_is_refused(access_client, keypair):
    token = make_token(keypair[0], email="alex@example.com", exp=int(time.time()) - 10)
    assert (
        access_client.get("/api/me", headers={"Cf-Access-Jwt-Assertion": token}).status_code == 401
    )


def test_token_signed_by_another_key_is_refused(access_client):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = make_token(other, email="alex@example.com")
    assert (
        access_client.get("/api/me", headers={"Cf-Access-Jwt-Assertion": token}).status_code == 401
    )


def test_email_outside_allow_list_is_refused(access_client, keypair):
    token = make_token(keypair[0], email="stranger@example.com")
    assert (
        access_client.get("/api/me", headers={"Cf-Access-Jwt-Assertion": token}).status_code == 403
    )


def test_service_token_cannot_act_as_a_person(access_client, keypair):
    token = make_token(keypair[0], common_name="abc123.access")
    assert (
        access_client.get("/api/me", headers={"Cf-Access-Jwt-Assertion": token}).status_code == 403
    )


def test_no_auth_configured_refuses_everything(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as c:
        assert c.get("/api/me").status_code == 503
        assert c.get("/api/health").status_code == 200


def test_dev_mode_cannot_be_combined_with_access(tmp_path):
    with pytest.raises(ValueError):
        Settings(data_dir=tmp_path, dev_mode=True, access_team_domain=TEAM, access_aud=AUD)


def test_settings_strip_windows_line_endings(tmp_path, monkeypatch):
    monkeypatch.setenv("WANDER_ACCESS_TEAM_DOMAIN", f"{TEAM}\r")
    monkeypatch.setenv("WANDER_ACCESS_AUD", f"{AUD}\r")
    monkeypatch.setenv("WANDER_ALLOWED_EMAILS", "alex@example.com,sam@example.com\r")
    s = Settings(data_dir=tmp_path)
    assert s.access_team_domain == TEAM
    assert s.access_aud == AUD
    assert s.allowed_email_set == {"alex@example.com", "sam@example.com"}


def test_rejected_token_is_logged_without_the_token(access_client, keypair, caplog):
    token = make_token(keypair[0], email="alex@example.com", aud="another-app")
    access_client.get("/api/me", headers={"Cf-Access-Jwt-Assertion": token})
    assert "rejected Access token: InvalidAudienceError" in caplog.text
    assert token not in caplog.text
