import json
import os
import secrets
import time
from urllib.parse import urlencode

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from src.config.index import appConfig
from src.services.googleDrive import SCOPES, _google_paths

REDIRECT_URI = os.getenv("GOOGLE_SHEETS_REDIRECT_URI", "http://localhost:8000/")
_PENDING_TTL_SECONDS = 10 * 60
_pending: dict[str, dict] = {}


def _allow_localhost_oauth() -> None:
    # Desktop OAuth client redirects to http://localhost, which oauthlib blocks unless this is set.
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


def _purge_pending() -> None:
    now = time.time()
    expired = [
        state
        for state, item in _pending.items()
        if now - item["created"] > _PENDING_TTL_SECONDS
    ]
    for state in expired:
        _pending.pop(state, None)


def _save_credentials(creds: Credentials, token_path: str) -> None:
    temporary = f"{token_path}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(creds.to_json())
    os.replace(temporary, token_path)


def _load_credentials(token_path: str) -> Credentials | None:
    if not os.path.exists(token_path):
        return None
    with open(token_path, encoding="utf-8") as handle:
        return Credentials.from_authorized_user_info(json.load(handle), SCOPES)


def sheets_connection_status() -> dict:
    credentials_path, token_path = _google_paths()
    if not os.path.exists(credentials_path):
        return {"connected": False, "reason": "missing_client"}
    creds = _load_credentials(token_path)
    if creds is None:
        return {"connected": False, "reason": "missing_token"}
    if creds.valid:
        return {"connected": True, "reason": None}
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_credentials(creds, token_path)
            return {"connected": True, "reason": None}
        except RefreshError:
            return {"connected": False, "reason": "expired"}
        except Exception:
            return {"connected": False, "reason": "expired"}
    return {"connected": False, "reason": "expired"}


def start_sheets_login(clerk_id: str) -> str:
    credentials_path, _ = _google_paths()
    if not os.path.exists(credentials_path):
        raise FileNotFoundError("Google OAuth client file was not found.")
    _allow_localhost_oauth()
    _purge_pending()
    flow = Flow.from_client_secrets_file(
        credentials_path,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    state = secrets.token_urlsafe(32)
    url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=state,
    )
    _pending[state] = {
        "clerk_id": clerk_id,
        "code_verifier": flow.code_verifier,
        "created": time.time(),
    }
    return url


def finish_sheets_login(
    code: str | None,
    state: str | None,
    error: str | None,
) -> str:
    domain = (appConfig["domain"] or "http://localhost:3000").rstrip("/")
    if error:
        return f"{domain}/chat?{urlencode({'google': 'denied'})}"

    _purge_pending()
    pending = _pending.pop(state, None) if state else None
    if not pending or not code:
        return f"{domain}/chat?{urlencode({'google': 'error'})}"

    credentials_path, token_path = _google_paths()
    _allow_localhost_oauth()
    flow = Flow.from_client_secrets_file(
        credentials_path,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
        code_verifier=pending["code_verifier"],
        autogenerate_code_verifier=False,
    )
    flow.fetch_token(code=code)
    if not flow.credentials:
        return f"{domain}/chat?{urlencode({'google': 'error'})}"
    _save_credentials(flow.credentials, token_path)
    return f"{domain}/chat?{urlencode({'google': 'connected'})}"
