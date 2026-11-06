"""
Google OAuth authentication module.

Supports two flows:
  1. ID Token verification (mobile/web client sends Google ID Token)
  2. Authorization code exchange (server-side OAuth flow)

For overseas market, ID Token flow is preferred:
  - Client uses Google Sign-In SDK → gets ID Token
  - Client sends ID Token to /v1/auth/google
  - Backend verifies token → extracts sub (Google user ID) + email + name
  - Backend finds or creates user via user_identities table

Required env vars:
  - GOOGLE_CLIENT_ID     Google OAuth Client ID (for token verification)
  - GOOGLE_CLIENT_SECRET  (for auth code flow, optional for ID token flow)
  - GOOGLE_REDIRECT_URI   (for auth code flow, optional)

Reference: https://developers.google.com/identity/sign-in/web/backend-auth
"""
from __future__ import annotations

import json
from typing import Optional

import requests
from flask import current_app


GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


class GoogleUserInfo:
    """Decoded Google user info from ID Token or userinfo API."""

    def __init__(self, sub: str, email: str = "", name: str = "",
                 picture: str = "", locale: str = ""):
        self.sub = sub            # Google unique user ID
        self.email = email
        self.name = name
        self.picture = picture
        self.locale = locale

    def to_dict(self):
        return {
            "sub": self.sub,
            "email": self.email,
            "name": self.name,
            "picture": self.picture,
            "locale": self.locale,
        }

    def to_metadata(self):
        return json.dumps({
            "picture": self.picture,
            "locale": self.locale,
        })


def verify_id_token(id_token: str) -> GoogleUserInfo:
    """Verify a Google ID Token and extract user info.

    Uses Google's tokeninfo endpoint for verification.
    For production, prefer google-auth library's id_token.verify_oauth2_token()
    which does proper signature verification locally.

    Raises:
        ValueError if token is invalid or audience mismatch.
    """
    client_id = current_app.config.get("GOOGLE_CLIENT_ID", "")

    # Try google-auth library first (proper signature verification)
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests

        decoded = id_token.verify_oauth2_token(
            id_token, google_requests.Request(), client_id
        )
        return GoogleUserInfo(
            sub=decoded.get("sub", ""),
            email=decoded.get("email", ""),
            name=decoded.get("name", ""),
            picture=decoded.get("picture", ""),
            locale=decoded.get("locale", ""),
        )
    except ImportError:
        pass  # Fall through to tokeninfo endpoint

    # Fallback: tokeninfo endpoint (less secure, but no extra dependency)
    params = {"id_token": id_token}
    if client_id:
        params["audience"] = client_id

    resp = requests.get(GOOGLE_TOKENINFO_URL, params=params, timeout=10)
    if resp.status_code != 200:
        raise ValueError(f"Google token verification failed: {resp.status_code}")

    data = resp.json()

    # Verify audience if client_id is configured
    if client_id and data.get("aud") != client_id:
        raise ValueError(
            f"Google token audience mismatch: expected {client_id}, got {data.get('aud')}"
        )

    if "sub" not in data:
        raise ValueError("Google token: no 'sub' field in response")

    return GoogleUserInfo(
        sub=data["sub"],
        email=data.get("email", ""),
        name=data.get("name", ""),
        picture=data.get("picture", ""),
        locale=data.get("locale", ""),
    )


def exchange_auth_code(code: str) -> GoogleUserInfo:
    """Exchange an authorization code for user info (server-side OAuth flow).

    This is the traditional OAuth2 flow:
    1. Client redirects to Google consent screen
    2. Google redirects back with ?code=xxx
    3. Server exchanges code for access_token + id_token
    4. Server fetches user info

    Raises:
        ValueError if code exchange fails.
    """
    client_id = current_app.config.get("GOOGLE_CLIENT_ID", "")
    client_secret = current_app.config.get("GOOGLE_CLIENT_SECRET", "")
    redirect_uri = current_app.config.get("GOOGLE_REDIRECT_URI", "")

    if not all([client_id, client_secret, redirect_uri]):
        raise ValueError("Google OAuth not configured: need GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI")

    # Exchange code for tokens
    resp = requests.post(GOOGLE_TOKEN_URL, data={
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }, timeout=10)

    if resp.status_code != 200:
        raise ValueError(f"Google auth code exchange failed: {resp.status_code} {resp.text}")

    tokens = resp.json()
    access_token = tokens.get("access_token", "")

    # Fetch user info
    resp = requests.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )

    if resp.status_code != 200:
        raise ValueError(f"Google userinfo fetch failed: {resp.status_code}")

    data = resp.json()
    return GoogleUserInfo(
        sub=data.get("sub", ""),
        email=data.get("email", ""),
        name=data.get("name", ""),
        picture=data.get("picture", ""),
        locale=data.get("locale", ""),
    )
