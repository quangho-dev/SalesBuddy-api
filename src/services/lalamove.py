from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


class LalamoveError(RuntimeError):
    pass


_ERROR_TEXT = {
    "ERR_INSUFFICIENT_CREDIT": "Ví Lalamove không đủ số dư.",
    "ERR_OUT_OF_SERVICE_AREA": "Điểm lấy hoặc điểm giao nằm ngoài vùng phục vụ.",
    "ERR_INVALID_PHONE_NUMBER": "Số điện thoại không hợp lệ với Lalamove.",
    "ERR_INVALID_SCHEDULE_TIME": "Giờ hẹn giao hàng không hợp lệ.",
    "ERR_INVALID_SERVICE_TYPE": "Loại xe không có ở khu vực này.",
    "ERR_REVERSE_GEOCODE_FAILURE": "Không xác định được vị trí. Hãy nhập vĩ độ và kinh độ.",
    "ERR_CANCELLATION_FORBIDDEN": "Lalamove không cho hủy chuyến này.",
    "ERR_INVALID_QUOTATION": "Báo giá không còn hiệu lực. Hãy báo giá lại.",
    "ERR_QUOTATION_EXPIRED": "Báo giá đã hết hạn. Hãy báo giá lại.",
}


def configured() -> bool:
    return bool(_key() and _secret())


def market() -> str:
    return (os.getenv("LALAMOVE_MARKET") or "VN").strip() or "VN"


def _key() -> str:
    return (os.getenv("LALAMOVE_API_KEY") or "").strip()


def _secret() -> str:
    return (os.getenv("LALAMOVE_API_SECRET") or "").strip()


def _base_url() -> str:
    return (os.getenv("LALAMOVE_BASE_URL") or "https://rest.sandbox.lalamove.com").rstrip("/")


def _require_config() -> None:
    if not configured():
        raise LalamoveError(
            "Chưa cấu hình Lalamove. Hãy thêm LALAMOVE_API_KEY và LALAMOVE_API_SECRET."
        )


def _signature(method: str, path: str, body: str, timestamp: str) -> str:
    raw = f"{timestamp}\r\n{method}\r\n{path}\r\n\r\n{body}"
    return hmac.new(_secret().encode(), raw.encode(), hashlib.sha256).hexdigest()


def _error_message(payload, status: int) -> str:
    if isinstance(payload, dict):
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0] if isinstance(errors[0], dict) else {}
            code = str(first.get("id") or payload.get("message") or "")
            detail = str(first.get("detail") or first.get("message") or "")
            return _ERROR_TEXT.get(code) or detail or code or f"Lalamove trả lỗi {status}."
        code = str(payload.get("message") or "")
        return _ERROR_TEXT.get(code) or code or f"Lalamove trả lỗi {status}."
    return f"Lalamove trả lỗi {status}."


def _request(method: str, path: str, payload: dict | None = None) -> dict:
    _require_config()
    body = ""
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    timestamp = str(int(datetime.now(timezone.utc).timestamp() * 1000))
    signature = _signature(method, path, body, timestamp)
    request = Request(
        f"{_base_url()}{path}",
        data=body.encode() if body else None,
        method=method,
        headers={
            "Authorization": f"hmac {_key()}:{timestamp}:{signature}",
            "Content-Type": "application/json",
            "Market": market(),
            "Request-ID": str(uuid4()),
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read().decode()
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read().decode()
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {}
        raise LalamoveError(_error_message(parsed, exc.code)) from exc
    except LalamoveError:
        raise
    except Exception as exc:
        raise LalamoveError("Không kết nối được Lalamove.") from exc


def create_quotation(
    service_type: str,
    stops: list[dict],
    schedule_at: str | None = None,
) -> dict:
    data = {
        "serviceType": service_type,
        "language": "vi_VN" if market().upper().startswith("VN") else "en_US",
        "stops": stops,
    }
    if schedule_at:
        data["scheduleAt"] = schedule_at
    result = _request("POST", "/v3/quotations", {"data": data})
    return result.get("data") or {}


def place_order(quotation_id: str, sender: dict, recipients: list[dict]) -> dict:
    result = _request(
        "POST",
        "/v3/orders",
        {
            "data": {
                "quotationId": quotation_id,
                "sender": sender,
                "recipients": recipients,
            }
        },
    )
    return result.get("data") or {}


def get_order(provider_order_id: str) -> dict:
    result = _request("GET", f"/v3/orders/{provider_order_id}")
    return result.get("data") or {}


def cancel_order(provider_order_id: str) -> None:
    _request("DELETE", f"/v3/orders/{provider_order_id}")
