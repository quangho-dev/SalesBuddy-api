import json
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from src.scripts.utils import load_mcp_config

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
QUOTE_TEMPLATE_NAME = os.getenv("QUOTE_TEMPLATE_NAME", "bao-gia.xls")
ORDER_TEMPLATE_NAME = os.getenv("ORDER_TEMPLATE_NAME", "don-hang.xls")
QUOTE_OUTPUT_FOLDER_ID = os.getenv(
    "QUOTE_OUTPUT_FOLDER_ID", "13v2sghRxWyYvuvGz9v9NPFd10oiq2yv3"
)
SHEET_MIME = "application/vnd.google-apps.spreadsheet"
EXCEL_MIME = "application/vnd.ms-excel"
_TEMPLATES_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "templates")
)


class QuoteTemplateNotFoundError(LookupError):
    pass


def quote_template_path(name: str = QUOTE_TEMPLATE_NAME) -> str:
    env_path = (os.getenv("QUOTE_TEMPLATE_PATH") or "").strip()
    if env_path:
        return os.path.abspath(env_path)
    return os.path.join(_TEMPLATES_DIR, name)


def _google_paths() -> tuple[str, str]:
    config = load_mcp_config("google-sheets").get("google-sheets") or {}
    env = config.get("env") or {}
    credentials_path = env.get("CREDENTIALS_PATH") or os.getenv(
        "CREDENTIALS_PATH", "credentials.json"
    )
    token_path = env.get("TOKEN_PATH") or os.getenv("TOKEN_PATH", "token.json")
    return credentials_path, token_path


def _credentials() -> Credentials:
    _, token_path = _google_paths()
    if not os.path.exists(token_path):
        raise RuntimeError(f"Google token not found at {token_path}")
    with open(token_path, encoding="utf-8") as handle:
        creds = Credentials.from_authorized_user_info(json.load(handle), SCOPES)
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "w", encoding="utf-8") as handle:
            handle.write(creds.to_json())
        return creds
    raise RuntimeError("Google Drive token is invalid. Re-authenticate MCP Google Sheets.")


def drive_service():
    return build("drive", "v3", credentials=_credentials(), cache_discovery=False)


def sheets_service():
    return build("sheets", "v4", credentials=_credentials(), cache_discovery=False)


def find_quote_template(name: str = QUOTE_TEMPLATE_NAME) -> dict:
    path = quote_template_path(name)
    if not os.path.isfile(path):
        raise QuoteTemplateNotFoundError(f"Template not found at {path}")
    return {
        "id": path,
        "name": os.path.basename(path),
        "path": path,
        "mimeType": EXCEL_MIME,
    }


def copy_quote_template(title: str, template_name: str = QUOTE_TEMPLATE_NAME) -> dict:
    template = find_quote_template(template_name)
    drive = drive_service()
    media = MediaFileUpload(template["path"], mimetype=EXCEL_MIME, resumable=True)
    body = {"name": title, "mimeType": SHEET_MIME}
    if QUOTE_OUTPUT_FOLDER_ID:
        body["parents"] = [QUOTE_OUTPUT_FOLDER_ID]
    copied = (
        drive.files()
        .create(
            body=body,
            media_body=media,
            fields="id,name,webViewLink,mimeType",
            supportsAllDrives=True,
        )
        .execute()
    )
    if not copied.get("id"):
        raise RuntimeError("Failed to copy spreadsheet template")
    return {
        "id": copied["id"],
        "name": copied.get("name") or title,
        "web_link": copied.get("webViewLink")
        or f"https://docs.google.com/spreadsheets/d/{copied['id']}/edit",
        "mime_type": copied.get("mimeType"),
        "template_id": template["id"],
        "template_name": template["name"],
    }
