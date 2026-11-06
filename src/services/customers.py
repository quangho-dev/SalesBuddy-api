from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4
from zoneinfo import ZoneInfo
import re
import unicodedata

from openpyxl import Workbook, load_workbook
from src.services.settings import get_settings
from src.services.supabase import supabase
from src.services.users import ensure_user

TABLE = "customers"
TEXT_FIELDS = (
    "customer_code",
    "company_name",
    "contact_person",
    "address",
    "phone_number",
    "tax_code",
    "website",
    "facebook",
    "zalo",
    "notes",
)
INT_FIELDS = ("payment_term_days",)
FIELDS = TEXT_FIELDS + INT_FIELDS


class CustomerNotFoundError(LookupError):
    pass


class CustomerImportError(ValueError):
    pass


TEMPLATE_HEADERS = (
    "Mã khách hàng",
    "Tên công ty",
    "Điện thoại",
    "Người liên hệ",
    "Địa chỉ",
    "Mã số thuế",
    "Website",
    "Facebook",
    "Zalo",
    "Hạn công nợ (ngày)",
    "Lịch sử tương tác",
)

_LOCAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
_INTERACTION_LINE = re.compile(
    r"^(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}-\d{1,2}-\d{1,2})"
    r"(?:[ T](\d{1,2}:\d{2}))?"
    r"\s*(.*)$"
)

HEADER_ALIASES = {
    "customer_code": {
        "ma khach hang",
        "ma khach",
        "customer code",
        "customer id",
    },
    "company_name": {
        "ten cong ty",
        "company name",
        "company",
        "cong ty",
    },
    "phone_number": {
        "dien thoai",
        "so dien thoai",
        "phone",
        "phone number",
        "sdt",
        "tel",
        "mobile",
    },
    "contact_person": {
        "nguoi lien he",
        "nguoi lien lac",
        "contact",
        "contact person",
        "lien he",
    },
    "address": {
        "dia chi",
        "address",
        "dia chi cong ty",
    },
    "tax_code": {
        "ma so thue",
        "mst",
        "tax code",
        "tax id",
        "vat",
    },
    "website": {
        "website",
        "web",
        "trang web",
    },
    "facebook": {
        "facebook",
        "fb",
        "fanpage",
    },
    "zalo": {
        "zalo",
    },
    "payment_term_days": {
        "han cong no",
        "han cong no ngay",
        "so ngay no",
        "payment term",
        "credit days",
        "debt term",
    },
    "interaction_history": {
        "lich su tuong tac",
        "tuong tac",
        "interaction",
        "interaction history",
        "history",
    },
}

INSERT_CHUNK_SIZE = 100


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _nonneg_int(value, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        number = int(round(float(str(value).strip().replace(",", "."))))
    except (TypeError, ValueError) as exc:
        raise ValueError("payment_term_days must be a number") from exc
    if number < 0:
        raise ValueError("payment_term_days must be >= 0")
    return number


def _normalize_interactions(items: list | None) -> list[dict]:
    normalized = []
    for item in items or []:
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        if not isinstance(item, dict):
            continue
        content = _text(item.get("content"))
        if not content:
            continue
        created_at = item.get("created_at")
        if created_at is None:
            created_at = _now()
        elif hasattr(created_at, "isoformat"):
            if getattr(created_at, "tzinfo", None) is not None:
                created_at = created_at.astimezone(timezone.utc)
            created_at = created_at.isoformat()
        else:
            created_at = str(created_at)
        interaction_id = item.get("id") or uuid4()
        normalized.append(
            {
                "id": str(interaction_id),
                "content": content,
                "created_at": created_at,
            }
        )
    return _sort_interactions(normalized)


def _interaction_timestamp(item: dict) -> float:
    raw = item.get("created_at")
    if raw is None or raw == "":
        return float("-inf")
    if hasattr(raw, "timestamp"):
        return raw.timestamp()
    text = str(raw).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return float("-inf")


def _sort_interactions(items: list | None) -> list[dict]:
    rows = [item for item in (items or []) if isinstance(item, dict)]
    return sorted(rows, key=_interaction_timestamp, reverse=True)


def _format_customer(row: dict) -> dict:
    row["customer_code"] = _text(row.get("customer_code"))
    row["interaction_history"] = _sort_interactions(row.get("interaction_history"))
    row["payment_term_days"] = _nonneg_int(row.get("payment_term_days"))
    return row


def _to_row(
    payload: dict,
    clerk_id: str,
    *,
    include_history: bool,
    default_payment_term_days: int,
) -> dict:
    row = {field: _text(payload.get(field)) for field in TEXT_FIELDS}
    row["payment_term_days"] = _nonneg_int(
        payload.get("payment_term_days"),
        default_payment_term_days,
    )
    row["clerk_id"] = clerk_id
    if include_history:
        row["interaction_history"] = _normalize_interactions(
            payload.get("interaction_history")
        )
    return row


def _owned_query(customer_id: str, clerk_id: str):
    return (
        supabase.table(TABLE)
        .select("*")
        .eq("id", customer_id)
        .eq("clerk_id", clerk_id)
        .limit(1)
    )


def _fold_header(value: str) -> str:
    text = value.strip().lower().replace("đ", "d")
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", stripped).strip()


def _cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value).strip()
    if isinstance(value, int):
        return str(value)
    return str(value).strip()


def _map_headers(headers: tuple) -> dict[int, str]:
    mapping = {}
    for index, header in enumerate(headers):
        folded = _fold_header(_cell_text(header))
        if not folded:
            continue
        for field, aliases in HEADER_ALIASES.items():
            if folded in aliases:
                mapping[index] = field
                break
    return mapping


def _parse_local_datetime(date_text: str, time_text: str | None) -> datetime | None:
    if "-" in date_text and date_text[0:4].isdigit():
        year_text, month_text, day_text = date_text.split("-", 2)
    else:
        day_text, month_text, year_text = re.split(r"[/-]", date_text)
    hour, minute = (0, 0)
    if time_text:
        hour_text, minute_text = time_text.split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
    try:
        return datetime(
            int(year_text),
            int(month_text),
            int(day_text),
            hour,
            minute,
            tzinfo=_LOCAL_TZ,
        )
    except ValueError:
        return None


def _split_interaction_line(line: str) -> tuple[datetime | None, str]:
    match = _INTERACTION_LINE.match(line.strip())
    if not match:
        return None, line.strip()
    date_text, time_text, rest = match.group(1), match.group(2), match.group(3).strip()
    content = re.sub(r"^[|\-–—:]\s*", "", rest).strip()
    if not content:
        return None, line.strip()
    created_at = _parse_local_datetime(date_text, time_text)
    if created_at is None:
        return None, line.strip()
    return created_at, content


def _parse_interaction_cell(value) -> list[dict]:
    text = _cell_text(value)
    items = []
    for line in re.split(r"\r?\n+", text):
        content_line = line.strip()
        if not content_line:
            continue
        created_at, content = _split_interaction_line(content_line)
        if not content:
            continue
        items.append({"content": content, "created_at": created_at})
    return items


def _row_payload(values: tuple, mapping: dict[int, str]) -> dict:
    payload = {field: "" for field in TEXT_FIELDS}
    payload["payment_term_days"] = None
    payload["interaction_history"] = []
    for index, field in mapping.items():
        if index >= len(values):
            continue
        if field == "interaction_history":
            payload["interaction_history"] = _parse_interaction_cell(values[index])
            continue
        text = _cell_text(values[index])
        if field == "payment_term_days" and text == "":
            continue
        payload[field] = text
    return payload


def _is_empty_payload(payload: dict) -> bool:
    return not any(_text(payload.get(field)) for field in TEXT_FIELDS)


def _fold_code(value) -> str:
    return re.sub(r"\s+", " ", _text(value)).casefold()


def _fold_tax(value) -> str:
    return re.sub(r"[\s.\-]", "", _text(value)).casefold()


def _interaction_key(item: dict) -> tuple[str, int | None]:
    content = _text(item.get("content")).casefold()
    created_at = item.get("created_at")
    if created_at is None or created_at == "":
        return content, None
    if hasattr(created_at, "timestamp"):
        return content, int(created_at.timestamp() // 60)
    stamp = _interaction_timestamp(item)
    if stamp == float("-inf"):
        return content, None
    return content, int(stamp // 60)


def _merge_interactions(existing: list | None, incoming: list | None) -> list[dict]:
    merged = [item for item in (existing or []) if isinstance(item, dict)]
    seen = {_interaction_key(item) for item in merged}
    for item in incoming or []:
        if not isinstance(item, dict):
            continue
        key = _interaction_key(item)
        if not key[0] or key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def _import_updates(payload: dict, mapped_fields: set[str]) -> dict:
    updates = {}
    for field in TEXT_FIELDS:
        if field not in mapped_fields:
            continue
        text = _text(payload.get(field))
        if text:
            updates[field] = text
    if (
        "payment_term_days" in mapped_fields
        and payload.get("payment_term_days") not in (None, "")
    ):
        updates["payment_term_days"] = _nonneg_int(payload.get("payment_term_days"))
    if "interaction_history" in mapped_fields and payload.get("interaction_history"):
        updates["interaction_history"] = payload["interaction_history"]
    return updates


def _load_import_index(
    clerk_id: str,
) -> tuple[dict[str, str], dict[str, str], dict[str, list], dict[str, dict]]:
    by_code: dict[str, str] = {}
    by_tax: dict[str, str] = {}
    histories: dict[str, list] = {}
    keys: dict[str, dict] = {}
    page_size = 1000
    start = 0
    while True:
        result = (
            supabase.table(TABLE)
            .select("id, customer_code, tax_code, interaction_history")
            .eq("clerk_id", clerk_id)
            .order("created_at")
            .range(start, start + page_size - 1)
            .execute()
        )
        rows = result.data or []
        for row in rows:
            customer_id = str(row["id"])
            histories[customer_id] = row.get("interaction_history") or []
            code = _fold_code(row.get("customer_code"))
            tax = _fold_tax(row.get("tax_code"))
            if code and code not in by_code:
                by_code[code] = customer_id
            if tax and tax not in by_tax:
                by_tax[tax] = customer_id
            keys[customer_id] = {
                "customer_code": row.get("customer_code") or "",
                "tax_code": row.get("tax_code") or "",
            }
        if len(rows) < page_size:
            break
        start += page_size
    return by_code, by_tax, histories, keys


def _match_import_customer(
    payload: dict, by_code: dict[str, str], by_tax: dict[str, str]
) -> str | None:
    code = _fold_code(payload.get("customer_code"))
    tax = _fold_tax(payload.get("tax_code"))
    if code and code in by_code:
        return by_code[code]
    if tax and tax in by_tax:
        return by_tax[tax]
    return None


def _remember_import_customer(
    customer: dict,
    by_code: dict[str, str],
    by_tax: dict[str, str],
    keys: dict[str, dict],
) -> None:
    customer_id = str(customer["id"])
    previous = keys.get(customer_id) or {}
    old_code = _fold_code(previous.get("customer_code"))
    old_tax = _fold_tax(previous.get("tax_code"))
    if old_code and by_code.get(old_code) == customer_id:
        del by_code[old_code]
    if old_tax and by_tax.get(old_tax) == customer_id:
        del by_tax[old_tax]
    code = _fold_code(customer.get("customer_code"))
    tax = _fold_tax(customer.get("tax_code"))
    if code:
        by_code[code] = customer_id
    if tax:
        by_tax[tax] = customer_id
    keys[customer_id] = {
        "customer_code": customer.get("customer_code") or "",
        "tax_code": customer.get("tax_code") or "",
    }


def create_customers(clerk_id: str, payloads: list[dict]) -> list[dict]:
    if not payloads:
        return []
    ensure_user(clerk_id)
    default_days = get_settings(clerk_id)["default_payment_term_days"]
    saved = []
    for start in range(0, len(payloads), INSERT_CHUNK_SIZE):
        chunk = [
            _to_row(
                item,
                clerk_id,
                include_history=True,
                default_payment_term_days=default_days,
            )
            for item in payloads[start : start + INSERT_CHUNK_SIZE]
        ]
        result = supabase.table(TABLE).insert(chunk).execute()
        saved.extend(_format_customer(row) for row in (result.data or []))
    return saved


def _json_customer_payload(payload: dict) -> dict:
    ready = dict(payload)
    history = []
    for item in payload.get("interaction_history") or []:
        if not isinstance(item, dict):
            continue
        created_at = item.get("created_at")
        if hasattr(created_at, "isoformat"):
            created_at = created_at.isoformat()
        history.append({"content": item.get("content") or "", "created_at": created_at})
    ready["interaction_history"] = history
    return ready


def parse_customer_workbook(content: bytes) -> dict:
    try:
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise CustomerImportError("File Excel không hợp lệ.") from exc

    try:
        sheet = workbook.active
        rows = sheet.iter_rows(values_only=True)
        try:
            headers = next(rows)
        except StopIteration as exc:
            raise CustomerImportError("File Excel trống.") from exc

        mapping = _map_headers(headers or ())
        if not mapping:
            raise CustomerImportError(
                "Không nhận diện được cột. Hãy dùng file mẫu (Mã khách hàng, Tên công ty, Điện thoại, Người liên hệ, Địa chỉ, Mã số thuế, Website, Facebook, Zalo, Lịch sử tương tác)."
            )

        parsed_rows = []
        skipped = 0
        for values in rows:
            values = values or ()
            if all(value is None or str(value).strip() == "" for value in values):
                skipped += 1
                continue
            payload = _row_payload(values, mapping)
            if _is_empty_payload(payload):
                skipped += 1
                continue
            parsed_rows.append({"customer": _json_customer_payload(payload)})
    finally:
        workbook.close()

    return {
        "rows": parsed_rows,
        "mapped_fields": sorted(set(mapping.values())),
        "skipped": skipped,
    }


def import_customer_rows(
    clerk_id: str, rows: list[dict], mapped_fields: list[str] | set[str]
) -> dict:
    mapped = set(mapped_fields)
    imported = 0
    updated = 0
    latest: dict[str, dict] = {}
    by_code, by_tax, histories, keys = _load_import_index(clerk_id)
    ensure_user(clerk_id)
    default_days = get_settings(clerk_id)["default_payment_term_days"]
    for row in rows:
        payload = row.get("customer") if isinstance(row, dict) else None
        if not isinstance(payload, dict):
            raise CustomerImportError("Dòng import không hợp lệ.")
        if _is_empty_payload(payload):
            continue
        customer_id = _match_import_customer(payload, by_code, by_tax)
        if customer_id:
            changes = _import_updates(payload, mapped)
            if "interaction_history" in changes:
                changes["interaction_history"] = _merge_interactions(
                    histories.get(customer_id),
                    changes["interaction_history"],
                )
            if changes:
                saved = update_customer(customer_id, clerk_id, changes)
                latest[customer_id] = saved
                _remember_import_customer(saved, by_code, by_tax, keys)
                histories[customer_id] = saved.get("interaction_history") or []
            updated += 1
            continue
        result = (
            supabase.table(TABLE)
            .insert(
                _to_row(
                    payload,
                    clerk_id,
                    include_history=True,
                    default_payment_term_days=default_days,
                )
            )
            .execute()
        )
        if not result.data:
            raise RuntimeError("Failed to create customer")
        created = _format_customer(result.data[0])
        created_id = str(created["id"])
        latest[created_id] = created
        _remember_import_customer(created, by_code, by_tax, keys)
        histories[created_id] = created.get("interaction_history") or []
        imported += 1

    return {
        "imported": imported,
        "updated": updated,
        "skipped": 0,
        "duplicates": 0,
        "customers": list(latest.values()),
    }


def import_customers_from_xlsx(clerk_id: str, content: bytes) -> dict:
    parsed = parse_customer_workbook(content)
    result = import_customer_rows(clerk_id, parsed["rows"], parsed["mapped_fields"])
    result["skipped"] = parsed["skipped"]
    return result


def build_customer_template() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Khach hang"
    sheet.append(list(TEMPLATE_HEADERS))
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _format_interaction_export(item: dict) -> str:
    content = _text(item.get("content"))
    if not content:
        return ""
    created_at = item.get("created_at")
    moment = None
    if isinstance(created_at, datetime):
        moment = created_at
    elif created_at:
        try:
            moment = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        except ValueError:
            moment = None
    if moment is None:
        return content
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    local = moment.astimezone(_LOCAL_TZ)
    return f"{local.strftime('%d/%m/%Y %H:%M')} {content}"


def _interaction_export_cell(items: list | None) -> str:
    lines = []
    for item in reversed(_sort_interactions(items)):
        if not isinstance(item, dict):
            continue
        line = _format_interaction_export(item)
        if line:
            lines.append(line)
    return "\n".join(lines)


def _customer_export_row(customer: dict) -> list:
    return [
        _text(customer.get("customer_code")),
        _text(customer.get("company_name")),
        _text(customer.get("phone_number")),
        _text(customer.get("contact_person")),
        _text(customer.get("address")),
        _text(customer.get("tax_code")),
        _text(customer.get("website")),
        _text(customer.get("facebook")),
        _text(customer.get("zalo")),
        _nonneg_int(customer.get("payment_term_days")),
        _interaction_export_cell(customer.get("interaction_history")),
    ]


def export_customers_xlsx(clerk_id: str) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Khach hang"
    sheet.append(list(TEMPLATE_HEADERS))
    for customer in list_customers(clerk_id):
        sheet.append(_customer_export_row(customer))
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def create_customer(clerk_id: str, payload: dict) -> dict:
    ensure_user(clerk_id)
    default_days = get_settings(clerk_id)["default_payment_term_days"]
    result = (
        supabase.table(TABLE)
        .insert(
            _to_row(
                payload,
                clerk_id,
                include_history=True,
                default_payment_term_days=default_days,
            )
        )
        .execute()
    )
    if not result.data:
        raise RuntimeError("Failed to create customer")
    return _format_customer(result.data[0])


def list_customers(clerk_id: str) -> list[dict]:
    result = (
        supabase.table(TABLE)
        .select("*")
        .eq("clerk_id", clerk_id)
        .order("created_at", desc=True)
        .execute()
    )
    return [_format_customer(row) for row in (result.data or [])]


def get_customer(customer_id: str, clerk_id: str) -> dict:
    result = _owned_query(customer_id, clerk_id).execute()
    data = result.data or []
    if not data:
        raise CustomerNotFoundError("Customer not found")
    return _format_customer(data[0])


def update_customer(customer_id: str, clerk_id: str, payload: dict) -> dict:
    get_customer(customer_id, clerk_id)

    updates = {}
    for field in TEXT_FIELDS:
        if field in payload and payload[field] is not None:
            updates[field] = _text(payload[field])
    if "payment_term_days" in payload and payload["payment_term_days"] is not None:
        updates["payment_term_days"] = _nonneg_int(payload["payment_term_days"])
    if "interaction_history" in payload and payload["interaction_history"] is not None:
        updates["interaction_history"] = _normalize_interactions(
            payload["interaction_history"]
        )
    if not updates:
        return get_customer(customer_id, clerk_id)

    updates["updated_at"] = _now()
    result = (
        supabase.table(TABLE)
        .update(updates)
        .eq("id", customer_id)
        .eq("clerk_id", clerk_id)
        .execute()
    )
    if not result.data:
        raise CustomerNotFoundError("Customer not found")
    return _format_customer(result.data[0])


def delete_customer(customer_id: str, clerk_id: str) -> dict:
    existing = get_customer(customer_id, clerk_id)
    # Orders and quotes reference this customer. Remove them first so stock
    # reserved by a delivered order is returned before the order disappears.
    from src.services.orders import delete_order

    order_rows = (
        supabase.table("orders")
        .select("id")
        .eq("customer_id", customer_id)
        .eq("clerk_id", clerk_id)
        .execute()
    )
    for row in order_rows.data or []:
        delete_order(row["id"], clerk_id)
    (
        supabase.table("quotes")
        .delete()
        .eq("customer_id", customer_id)
        .eq("clerk_id", clerk_id)
        .execute()
    )
    supabase.table(TABLE).delete().eq("id", customer_id).eq(
        "clerk_id", clerk_id
    ).execute()
    return existing
