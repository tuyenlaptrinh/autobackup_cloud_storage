#!/usr/bin/python
# coding: utf-8
"""Google Drive OAuth2 linking and token management."""

from __future__ import print_function
import os
import json

from .paths import (
    CREDENTIALS_FILE,
    TOKEN_FILE,
    get_config,
    save_config,
    write_json,
    read_json,
    ok,
    fail,
)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
# Google deprecated OOB; use localhost redirect — user copies ?code= from the address bar.
REDIRECT_URI = "http://localhost"


def _extract_client(data):
    """Return (client_id, client_secret, client_type) from credentials.json body."""
    if not isinstance(data, dict):
        return "", "", ""
    for key in ("installed", "web"):
        block = data.get(key)
        if isinstance(block, dict) and block.get("client_id") and block.get("client_secret"):
            return (
                str(block.get("client_id", "")).strip(),
                str(block.get("client_secret", "")).strip(),
                key,
            )
    # flat shape fallback
    if data.get("client_id") and data.get("client_secret"):
        return (
            str(data.get("client_id", "")).strip(),
            str(data.get("client_secret", "")).strip(),
            "flat",
        )
    return "", "", ""


def _save_credentials_file(client_id, client_secret):
    data = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost", "http://localhost:8080/", "urn:ietf:wg:oauth:2.0:oob"],
        }
    }
    write_json(CREDENTIALS_FILE, data)


def _apply_client_to_config(client_id, client_secret):
    cfg = get_config()
    cfg["client_id"] = client_id
    cfg["client_secret"] = client_secret
    save_config(cfg)
    return cfg


def save_oauth_client(client_id, client_secret):
    client_id = (client_id or "").strip()
    client_secret = (client_secret or "").strip()
    if not client_id or not client_secret:
        return fail("Client ID and Client Secret are required.")
    _save_credentials_file(client_id, client_secret)
    _apply_client_to_config(client_id, client_secret)
    return ok("OAuth client saved.", {"client_id": client_id})


def save_credentials_json(raw):
    """Accept credentials.json content (string or dict) uploaded by the user."""
    if raw is None or raw == "":
        return fail("credentials.json content is empty.")
    if isinstance(raw, dict):
        data = raw
    else:
        text = str(raw).strip()
        # strip UTF-8 BOM if present
        if text.startswith("\ufeff"):
            text = text.lstrip("\ufeff")
        try:
            data = json.loads(text)
        except Exception as e:
            return fail("Invalid JSON: {}".format(str(e)))

    client_id, client_secret, ctype = _extract_client(data)
    if not client_id or not client_secret:
        return fail(
            "credentials.json must contain client_id and client_secret "
            "(under installed or web)."
        )

    # Normalize to installed Desktop shape so Flow.from_client_secrets_file works
    if ctype == "web":
        # Keep original web block but also write an installed mirror for the library
        installed = dict(data.get("web") or {})
        installed.setdefault("auth_uri", "https://accounts.google.com/o/oauth2/auth")
        installed.setdefault("token_uri", "https://oauth2.googleapis.com/token")
        uris = installed.get("redirect_uris") or []
        if "http://localhost" not in uris:
            uris = list(uris) + ["http://localhost"]
        installed["redirect_uris"] = uris
        payload = {"installed": installed}
    elif ctype == "flat":
        payload = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": data.get("auth_uri") or "https://accounts.google.com/o/oauth2/auth",
                "token_uri": data.get("token_uri") or "https://oauth2.googleapis.com/token",
                "redirect_uris": data.get("redirect_uris")
                or ["http://localhost", "http://localhost:8080/"],
            }
        }
    else:
        payload = data

    write_json(CREDENTIALS_FILE, payload)
    try:
        os.chmod(CREDENTIALS_FILE, 0o600)
    except Exception:
        pass
    _apply_client_to_config(client_id, client_secret)
    return ok(
        "credentials.json uploaded successfully.",
        {"client_id": client_id, "client_type": ctype or "installed"},
    )


def _ensure_credentials_file():
    """Ensure CREDENTIALS_FILE exists from uploaded file or config fields."""
    if os.path.exists(CREDENTIALS_FILE):
        data = read_json(CREDENTIALS_FILE, {})
        cid, secret, _ = _extract_client(data)
        if cid and secret:
            return True, cid, secret
    cfg = get_config()
    if cfg.get("client_id") and cfg.get("client_secret"):
        _save_credentials_file(cfg["client_id"], cfg["client_secret"])
        return True, cfg["client_id"], cfg["client_secret"]
    return False, "", ""


def get_auth_url():
    ready, _, _ = _ensure_credentials_file()
    if not ready:
        return fail("Please upload credentials.json or save Client ID / Secret first.")
    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError:
        return fail(
            "Google API libraries missing. Re-run install.sh or: "
            "pip install google-auth-oauthlib google-api-python-client"
        )

    cfg = get_config()
    try:
        flow = Flow.from_client_secrets_file(
            CREDENTIALS_FILE,
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI,
        )
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        cfg["oauth_state"] = state
        save_config(cfg)
        return ok("Open this URL to authorize Google Drive.", {"auth_url": auth_url})
    except Exception as e:
        return fail("Failed to build auth URL: {}".format(str(e)))


def exchange_code(code):
    code = (code or "").strip()
    if not code:
        return fail("Authorization code is required.")
    # Accept full redirect URL: http://localhost/?code=...&scope=...
    if "code=" in code:
        try:
            from urllib.parse import urlparse, parse_qs

            qs = parse_qs(urlparse(code).query)
            if "code" in qs:
                code = qs["code"][0]
        except Exception:
            pass
    ready, _, _ = _ensure_credentials_file()
    if not ready:
        return fail("OAuth client is not configured. Upload credentials.json first.")
    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError:
        return fail("Google API libraries are not installed.")

    cfg = get_config()
    try:
        flow = Flow.from_client_secrets_file(
            CREDENTIALS_FILE,
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI,
        )
        flow.fetch_token(code=code)
        creds = flow.credentials
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
        os.chmod(TOKEN_FILE, 0o600)

        email = ""
        try:
            from googleapiclient.discovery import build

            service = build("oauth2", "v2", credentials=creds)
            info = service.userinfo().get().execute()
            email = info.get("email", "")
        except Exception:
            # drive.file scope may not include userinfo; try Drive about
            try:
                from googleapiclient.discovery import build

                service = build("drive", "v3", credentials=creds)
                about = service.about().get(fields="user").execute()
                email = about.get("user", {}).get("emailAddress", "")
            except Exception:
                email = ""

        cfg["linked"] = True
        cfg["account_email"] = email
        save_config(cfg)
        return ok("Google Drive linked successfully.", {"email": email})
    except Exception as e:
        return fail("Failed to exchange code: {}".format(str(e)))


def unlink_drive():
    cfg = get_config()
    cfg["linked"] = False
    cfg["account_email"] = ""
    cfg["drive_folder_id"] = ""
    save_config(cfg)
    for path in (TOKEN_FILE,):
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
    return ok("Google Drive unlinked.")


def get_credentials():
    """Return valid google.oauth2.credentials.Credentials or None."""
    if not os.path.exists(TOKEN_FILE):
        return None
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        return None

    try:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(TOKEN_FILE, "w") as f:
                    f.write(creds.to_json())
            else:
                return None
        return creds
    except Exception:
        return None


def drive_status():
    cfg = get_config()
    linked = bool(cfg.get("linked")) and os.path.exists(TOKEN_FILE)
    creds_ok = False
    if linked:
        creds_ok = get_credentials() is not None
        if not creds_ok:
            linked = False
    return ok(
        "OK",
        {
            "linked": linked,
            "email": cfg.get("account_email", ""),
            "client_configured": bool(cfg.get("client_id") and cfg.get("client_secret"))
            or os.path.exists(CREDENTIALS_FILE),
            "client_id": cfg.get("client_id", ""),
            "credentials_uploaded": os.path.exists(CREDENTIALS_FILE),
            "drive_folder_name": cfg.get("drive_folder_name", "aaPanel Backups"),
            "drive_folder_id": cfg.get("drive_folder_id", ""),
            "token_valid": creds_ok,
        },
    )
