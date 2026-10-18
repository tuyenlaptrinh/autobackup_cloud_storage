#!/usr/bin/python
# coding: utf-8
"""Microsoft Graph OAuth for OneDrive Business / SharePoint (work/school only)."""

from __future__ import print_function
import os
import json
import time

from .paths import (
    MSGRAPH_TOKEN_FILE,
    DEFAULT_MSGRAPH,
    get_config,
    save_config,
    write_json,
    read_json,
    ok,
    fail,
)

# Work/school accounts only — excludes personal Microsoft accounts
AUTHORITY = "https://login.microsoftonline.com/organizations"
REDIRECT_URI = "http://localhost"
GRAPH_SCOPES = [
    "Files.ReadWrite",
    "Sites.ReadWrite.All",
    "User.Read",
    "offline_access",
]


def _msgraph_cfg(cfg=None):
    cfg = cfg or get_config()
    mg = dict(DEFAULT_MSGRAPH)
    raw = cfg.get("msgraph") if isinstance(cfg.get("msgraph"), dict) else {}
    mg.update(raw or {})
    return mg


def _save_msgraph(mg, cfg=None):
    cfg = cfg or get_config()
    cfg["msgraph"] = mg
    save_config(cfg)
    return cfg


def save_msgraph_client(client_id, client_secret, tenant=None):
    client_id = (client_id or "").strip()
    client_secret = (client_secret or "").strip()
    mg = _msgraph_cfg()
    if not client_id:
        return fail("Application (client) ID is required.")
    if not client_secret and not mg.get("client_secret"):
        return fail("Client secret is required.")
    mg["client_id"] = client_id
    if client_secret:
        mg["client_secret"] = client_secret
    # Always force organizations so personal MSA cannot sign in
    mg["tenant"] = "organizations"
    if tenant and str(tenant).strip() and str(tenant).strip().lower() not in (
        "common",
        "consumers",
    ):
        # Allow specific tenant GUID/domain, but never consumers/common
        t = str(tenant).strip()
        if t.lower() != "organizations":
            mg["tenant"] = t
    _save_msgraph(mg)
    return ok(
        "Microsoft Entra app credentials saved (work/school accounts only).",
        {"client_id": client_id, "tenant": mg["tenant"]},
    )


def save_msgraph_site(site_url):
    site_url = (site_url or "").strip()
    if not site_url:
        return fail("SharePoint site URL is required.")
    mg = _msgraph_cfg()
    mg["site_url"] = site_url
    mg["site_id"] = ""
    mg["drive_id"] = ""
    _save_msgraph(mg)
    return ok("SharePoint site URL saved.", {"site_url": site_url})


def save_msgraph_folder_name(folder_name):
    folder_name = (folder_name or "").strip() or "aaPanel Backups"
    mg = _msgraph_cfg()
    mg["folder_name"] = folder_name
    mg["folder_id"] = ""
    _save_msgraph(mg)
    return ok("Backup folder name updated.", {"folder_name": folder_name})


def _authority(mg=None):
    mg = mg or _msgraph_cfg()
    tenant = (mg.get("tenant") or "organizations").strip() or "organizations"
    if tenant.lower() in ("common", "consumers"):
        tenant = "organizations"
    return "https://login.microsoftonline.com/{}".format(tenant)


def _msal_app(mg=None):
    try:
        from msal import ConfidentialClientApplication
    except ImportError:
        raise RuntimeError(
            "msal is not installed. Re-run install.sh or: pip install msal requests"
        )
    mg = mg or _msgraph_cfg()
    if not mg.get("client_id") or not mg.get("client_secret"):
        raise RuntimeError("Save Application (client) ID and Client secret first.")
    return ConfidentialClientApplication(
        mg["client_id"],
        client_credential=mg["client_secret"],
        authority=_authority(mg),
    )


def get_auth_url():
    try:
        app = _msal_app()
    except Exception as e:
        return fail(str(e))
    try:
        flow = app.initiate_auth_code_flow(
            scopes=GRAPH_SCOPES,
            redirect_uri=REDIRECT_URI,
        )
        if "auth_uri" not in flow:
            return fail("Failed to start Microsoft auth flow: {}".format(flow.get("error_description") or flow))
        mg = _msgraph_cfg()
        # Persist flow state for exchange (contains code_verifier / state)
        mg["oauth_flow"] = flow
        _save_msgraph(mg)
        return ok(
            "Open this URL and sign in with a Microsoft 365 work/school account "
            "(personal OneDrive is not supported).",
            {"auth_url": flow["auth_uri"]},
        )
    except Exception as e:
        return fail("Failed to build Microsoft auth URL: {}".format(str(e)))


def _extract_code_params(raw):
    """Accept raw code or full redirect URL; return dict for MSAL."""
    raw = (raw or "").strip()
    if not raw:
        return {}
    if "://" in raw or "code=" in raw:
        try:
            from urllib.parse import urlparse, parse_qs

            # Support pasted full URL or query-only string
            if "://" not in raw and raw.startswith("?"):
                raw = "http://localhost/" + raw
            elif "://" not in raw and "code=" in raw:
                raw = "http://localhost/?" + raw.lstrip("?")
            parsed = urlparse(raw)
            qs = parse_qs(parsed.query)
            out = {}
            for k, vals in qs.items():
                if vals:
                    out[k] = vals[0]
            return out
        except Exception:
            pass
    return {"code": raw}


def exchange_code(code_or_url):
    auth_response = _extract_code_params(code_or_url)
    if not auth_response.get("code"):
        return fail("Authorization code is required.")
    mg = _msgraph_cfg()
    flow = mg.get("oauth_flow")
    if not isinstance(flow, dict) or "auth_uri" not in flow:
        return fail("Auth flow expired. Click Get auth URL again.")
    try:
        app = _msal_app(mg)
    except Exception as e:
        return fail(str(e))
    try:
        result = app.acquire_token_by_auth_code_flow(flow, auth_response)
        if "access_token" not in result:
            desc = result.get("error_description") or result.get("error") or str(result)
            return fail("Microsoft token exchange failed: {}".format(desc))

        # Reject personal MSA if somehow returned
        id_claims = result.get("id_token_claims") or {}
        tid = str(id_claims.get("tid") or "")
        # Personal Microsoft accounts use tenant 9188040d-6c67-4c5b-b112-36a304b66dad
        if tid.lower() == "9188040d-6c67-4c5b-b112-36a304b66dad":
            return fail(
                "Personal Microsoft accounts are not supported. "
                "Sign in with a Microsoft 365 work or school account (OneDrive Business)."
            )

        token_blob = {
            "access_token": result.get("access_token"),
            "refresh_token": result.get("refresh_token"),
            "expires_at": int(time.time()) + int(result.get("expires_in") or 3600) - 60,
            "token_type": result.get("token_type") or "Bearer",
            "scope": result.get("scope") or "",
            "id_token_claims": id_claims,
        }
        write_json(MSGRAPH_TOKEN_FILE, token_blob)
        try:
            os.chmod(MSGRAPH_TOKEN_FILE, 0o600)
        except Exception:
            pass

        email = (
            id_claims.get("preferred_username")
            or id_claims.get("email")
            or id_claims.get("upn")
            or ""
        )
        if not email:
            try:
                email = _graph_me(token_blob["access_token"]).get("mail") or _graph_me(
                    token_blob["access_token"]
                ).get("userPrincipalName") or ""
            except Exception:
                email = ""

        mg["linked"] = True
        mg["account_email"] = email
        mg.pop("oauth_flow", None)
        _save_msgraph(mg)
        return ok(
            "Microsoft 365 account linked (work/school).",
            {"email": email},
        )
    except Exception as e:
        return fail("Failed to exchange Microsoft code: {}".format(str(e)))


def unlink_msgraph():
    mg = _msgraph_cfg()
    mg["linked"] = False
    mg["account_email"] = ""
    mg["folder_id"] = ""
    mg["site_id"] = ""
    mg["drive_id"] = ""
    mg.pop("oauth_flow", None)
    _save_msgraph(mg)
    if os.path.exists(MSGRAPH_TOKEN_FILE):
        try:
            os.remove(MSGRAPH_TOKEN_FILE)
        except Exception:
            pass
    return ok("Microsoft 365 account unlinked.")


def _graph_me(access_token):
    import requests

    r = requests.get(
        "https://graph.microsoft.com/v1.0/me",
        headers={"Authorization": "Bearer {}".format(access_token)},
        timeout=30,
    )
    if r.status_code >= 400:
        raise RuntimeError("Graph /me failed: {}".format(r.text[:300]))
    return r.json()


def get_access_token():
    """Return a valid access token string or None."""
    if not os.path.exists(MSGRAPH_TOKEN_FILE):
        return None
    blob = read_json(MSGRAPH_TOKEN_FILE, {})
    if not blob.get("access_token"):
        return None
    expires_at = int(blob.get("expires_at") or 0)
    if expires_at > int(time.time()) + 30:
        return blob["access_token"]

    refresh = blob.get("refresh_token")
    if not refresh:
        return None
    try:
        app = _msal_app()
        result = app.acquire_token_by_refresh_token(refresh, scopes=GRAPH_SCOPES)
        if "access_token" not in result:
            return None
        blob["access_token"] = result["access_token"]
        if result.get("refresh_token"):
            blob["refresh_token"] = result["refresh_token"]
        blob["expires_at"] = int(time.time()) + int(result.get("expires_in") or 3600) - 60
        write_json(MSGRAPH_TOKEN_FILE, blob)
        return blob["access_token"]
    except Exception:
        return None


def msgraph_status():
    mg = _msgraph_cfg()
    token_ok = get_access_token() is not None
    linked = bool(mg.get("linked")) and token_ok
    if mg.get("linked") and not token_ok:
        linked = False
    return {
        "linked": linked,
        "email": mg.get("account_email") or "",
        "client_configured": bool(mg.get("client_id") and mg.get("client_secret")),
        "client_id": mg.get("client_id") or "",
        "tenant": mg.get("tenant") or "organizations",
        "folder_name": mg.get("folder_name") or "aaPanel Backups",
        "site_url": mg.get("site_url") or "",
        "site_id": mg.get("site_id") or "",
        "token_valid": token_ok,
        "work_school_only": True,
    }
