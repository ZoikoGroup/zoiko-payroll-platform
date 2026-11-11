"""Allowlisted outbound HTTP requests required by the Google OAuth flow."""

import httpx

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v2/userinfo"


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(20.0),
        follow_redirects=False,
        trust_env=False,
    )


def exchange_code(endpoint: str, data: dict) -> httpx.Response:
    if endpoint != TOKEN_ENDPOINT:
        raise ValueError("Google OAuth token endpoint is not allowlisted")
    with _client() as client:
        return client.post(TOKEN_ENDPOINT, data=data)


def fetch_userinfo(endpoint: str, access_token: str) -> httpx.Response:
    if endpoint != USERINFO_ENDPOINT:
        raise ValueError("Google OAuth userinfo endpoint is not allowlisted")
    with _client() as client:
        return client.get(
            USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
        )
