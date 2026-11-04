from datetime import datetime, timezone
from io import BytesIO
import math
import re
import unicodedata

from openpyxl import Workbook, load_workbook
from src.services.supabase import supabase
from src.services.users import ensure_user

TABLE = "products"
TEXT_FIELDS = (
    "product_code",
    "name",
    "product_type",
    "unit",
    "notes",
)
NUMBER_FIELDS = (
    "selling_price",
    "stock",
)


class ProductNotFoundError(LookupError):
    pass


class ProductImportError(ValueError):
    pass


TEMPLATE_HEADERS = (
    "Mã sản phẩm",
    "Tên sản phẩm",
    "Đơn vị tính",
    "Giá bán",
    "Tồn kho",
    "Ghi chú",
    "Loại sản phẩm",
)

HEADER_ALIASES = {
    "product_code": {
        "ma san pham",
        "product code",
        "product_code",
        "sku",
        "code",
        "ma",
        "ma hang",
    },
    "name": {
        "ten san pham",
        "name",
        "ten",
    },
    "product_type": {
        "loai san pham",
        "product type",
        "product_type",
        "type",
        "category",
        "loai",
    },
    "unit": {
        "don vi tinh",
        "on vi tinh",
        "unit",
        "dvt",
        "don vi",
    },
    "selling_price": {
        "gia ban",
        "selling price",
        "selling_price",
        "price",
        "gia",
    },
    "stock": {
        "ton kho",
        "stock",
        "inventory",
        "sl ton",
    },
    "notes": {
        "ghi chu",
        "notes",
        "note",
    },
}

INSERT_CHUNK_SIZE = 100


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _number(value) -> float:
    if value is None or value == "":
        return 0
    return float(value)


def _to_row(payload: dict, clerk_id: str) -> dict:
    row = {field: _text(payload.get(field)) for field in TEXT_FIELDS}
    row.update({field: _number(payload.get(field)) for field in NUMBER_FIELDS})
    row["clerk_id"] = clerk_id
    return row


def _owned_query(product_id: str, clerk_id: str):
    return (
        supabase.table(TABLE)
        .select("*")
        .eq("id", product_id)
        .eq("clerk_id", clerk_id)
        .limit(1)
    )


def _fold_header(value: str) -> str:
    # Đ/đ does not decompose in NFD, so it would be stripped from a-z.
    text = value.strip().lower().replace("đ", "d")
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", stripped).strip()


def _parse_number(value) -> float:
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return 0
        return float(value)
    text = (
        str(value)
        .strip()
        .replace("đ", "")
        .replace("₫", "")
        .replace(" ", "")
        .replace("\u00a0", "")
    )
    if not text:
        return 0
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    elif "," in text:
        if text.count(",") > 1:
            text = text.replace(",", "")
        else:
            text = text.replace(",", ".")
    return float(text)


def _cell_text(value) -> str:
    if value is None:
        return ""
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


def _row_payload(values: tuple, mapping: dict[int, str]) -> dict:
    payload = {field: "" if field in TEXT_FIELDS else 0 for field in (*TEXT_FIELDS, *NUMBER_FIELDS)}
    for index, field in mapping.items():
        if index >= len(values):
            continue
        value = values[index]
        if field in NUMBER_FIELDS:
            payload[field] = _parse_number(value)
        else:
            payload[field] = _cell_text(value)
    return payload


def _is_empty_payload(payload: dict) -> bool:
    has_text = any(_text(payload.get(field)) for field in TEXT_FIELDS)
    has_number = any(_number(payload.get(field)) for field in NUMBER_FIELDS)
    return not has_text and not has_number


def _fold_code(value) -> str:
    return re.sub(r"\s+", " ", _text(value)).casefold()


def _cell_is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _import_updates(values: tuple, mapping: dict[int, str]) -> dict:
    updates = {}
    for index, field in mapping.items():
        if field == "product_code" or index >= len(values):
            continue
        value = values[index]
        if _cell_is_blank(value):
            continue
        if field in NUMBER_FIELDS:
            updates[field] = _parse_number(value)
        else:
            text = _cell_text(value)
            if text:
                updates[field] = text
    return updates


def _load_product_codes(clerk_id: str) -> dict[str, str]:
    by_code: dict[str, str] = {}
    page_size = 1000
    start = 0
    while True:
        result = (
            supabase.table(TABLE)
            .select("id, product_code")
            .eq("clerk_id", clerk_id)
            .order("created_at")
            .range(start, start + page_size - 1)
            .execute()
        )
        rows = result.data or []
        for row in rows:
            code = _fold_code(row.get("product_code"))
            if code and code not in by_code:
                by_code[code] = str(row["id"])
        if len(rows) < page_size:
            break
        start += page_size
    return by_code


def create_products(clerk_id: str, payloads: list[dict]) -> list[dict]:
    if not payloads:
        return []
    ensure_user(clerk_id)
    saved = []
    for start in range(0, len(payloads), INSERT_CHUNK_SIZE):
        chunk = [_to_row(item, clerk_id) for item in payloads[start : start + INSERT_CHUNK_SIZE]]
        result = supabase.table(TABLE).insert(chunk).execute()
        saved.extend(result.data or [])
    return saved


def _plan_product_import(
    parsed_rows: list[tuple[dict, dict]],
    by_code: dict[str, str],
) -> tuple[list[dict], dict[str, dict], int, int]:
    new_by_code: dict[str, dict] = {}
    new_without_code: list[dict] = []
    updates_by_id: dict[str, dict] = {}
    imported = 0
    updated = 0
    for payload, changes in parsed_rows:
        code = _fold_code(payload.get("product_code"))
        product_id = by_code.get(code) if code else None
        if product_id:
            updates_by_id.setdefault(product_id, {}).update(changes)
            updated += 1
            continue
        if code and code in new_by_code:
            new_by_code[code].update(changes)
            updated += 1
            continue
        if code:
            new_by_code[code] = dict(payload)
        else:
            new_without_code.append(dict(payload))
        imported += 1
    return [*new_by_code.values(), *new_without_code], updates_by_id, imported, updated


def _apply_product_updates(product_id: str, clerk_id: str, changes: dict) -> None:
    updates = {}
    for field in TEXT_FIELDS:
        if field in changes and field != "product_code":
            updates[field] = _text(changes[field])
    for field in NUMBER_FIELDS:
        if field in changes:
            updates[field] = _number(changes[field])
    if not updates:
        return
    updates["updated_at"] = _now()
    (
        supabase.table(TABLE)
        .update(updates)
        .eq("id", product_id)
        .eq("clerk_id", clerk_id)
        .execute()
    )


def import_products_from_xlsx(clerk_id: str, content: bytes) -> dict:
    try:
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise ProductImportError("File Excel không hợp lệ.") from exc

    try:
        sheet = workbook.active
        rows = sheet.iter_rows(values_only=True)
        try:
            headers = next(rows)
        except StopIteration as exc:
            raise ProductImportError("File Excel trống.") from exc

        mapping = _map_headers(headers or ())
        if not mapping:
            raise ProductImportError(
                "Không nhận diện được cột. Hãy dùng file mẫu (Mã sản phẩm, Tên sản phẩm, ...)."
            )

        parsed_rows = []
        errors = []
        skipped = 0
        empty_streak = 0
        for row_number, values in enumerate(rows, start=2):
            values = values or ()
            if all(value is None or str(value).strip() == "" for value in values):
                empty_streak += 1
                skipped += 1
                if empty_streak >= 100:
                    break
                continue
            empty_streak = 0
            try:
                payload = _row_payload(values, mapping)
                changes = _import_updates(values, mapping)
            except (TypeError, ValueError):
                errors.append({"row": row_number, "message": "Số không hợp lệ."})
                continue
            if _is_empty_payload(payload):
                skipped += 1
                continue
            parsed_rows.append((payload, changes))
    finally:
        workbook.close()

    by_code = _load_product_codes(clerk_id)
    new_payloads, updates_by_id, imported, updated = _plan_product_import(
        parsed_rows, by_code
    )
    create_products(clerk_id, new_payloads)
    for product_id, changes in updates_by_id.items():
        _apply_product_updates(product_id, clerk_id, changes)

    return {
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "duplicates": 0,
        "errors": errors[:100],
        "products": [],
    }


def build_product_template() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "San pham"
    sheet.append(list(TEMPLATE_HEADERS))
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def create_product(clerk_id: str, payload: dict) -> dict:
    ensure_user(clerk_id)
    result = supabase.table(TABLE).insert(_to_row(payload, clerk_id)).execute()
    if not result.data:
        raise RuntimeError("Failed to create product")
    return result.data[0]


def list_products(clerk_id: str) -> list[dict]:
    result = (
        supabase.table(TABLE)
        .select("*")
        .eq("clerk_id", clerk_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


def get_product(product_id: str, clerk_id: str) -> dict:
    result = _owned_query(product_id, clerk_id).execute()
    data = result.data or []
    if not data:
        raise ProductNotFoundError("Product not found")
    return data[0]


def update_product(product_id: str, clerk_id: str, payload: dict) -> dict:
    get_product(product_id, clerk_id)

    updates = {}
    for field in TEXT_FIELDS:
        if field in payload and payload[field] is not None:
            updates[field] = _text(payload[field])
    for field in NUMBER_FIELDS:
        if field in payload and payload[field] is not None:
            updates[field] = _number(payload[field])
    if not updates:
        return get_product(product_id, clerk_id)

    updates["updated_at"] = _now()
    result = (
        supabase.table(TABLE)
        .update(updates)
        .eq("id", product_id)
        .eq("clerk_id", clerk_id)
        .execute()
    )
    if not result.data:
        raise ProductNotFoundError("Product not found")
    return result.data[0]


def delete_product(product_id: str, clerk_id: str) -> dict:
    existing = get_product(product_id, clerk_id)
    supabase.table(TABLE).delete().eq("id", product_id).eq(
        "clerk_id", clerk_id
    ).execute()
    return existing
