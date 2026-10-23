from datetime import datetime, timezone
from zoneinfo import ZoneInfo

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

from src.services.googleDrive import copy_quote_template
from src.services.quoteSheet import fill_quote_spreadsheet
from src.services.quotes import VAT_RATE, get_quote, save_quote_drive_file

ONES = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]


def _read_triplet(value: int, force_hundreds: bool) -> str:
    hundreds = value // 100
    tens = (value % 100) // 10
    ones = value % 10
    parts = []
    if hundreds or force_hundreds:
        parts.append(f"{ONES[hundreds]} trăm")
    if tens == 0:
        if ones and (hundreds or force_hundreds):
            parts.append("lẻ")
    elif tens == 1:
        parts.append("mười")
    else:
        parts.append(f"{ONES[tens]} mươi")
    if ones:
        if tens > 1 and ones == 1:
            parts.append("mốt")
        elif tens >= 1 and ones == 5:
            parts.append("lăm")
        elif tens > 1 and ones == 4:
            parts.append("tư")
        else:
            parts.append(ONES[ones])
    return " ".join(parts).strip()


def amount_in_vietnamese_words(amount: float) -> str:
    number = int(round(float(amount or 0)))
    if number < 0:
        return "Âm " + amount_in_vietnamese_words(-number).lower()
    if number == 0:
        return "Không đồng./."

    scales = ["", "nghìn", "triệu", "tỷ", "nghìn tỷ"]
    groups = []
    remaining = number
    while remaining:
        groups.append(remaining % 1000)
        remaining //= 1000

    parts = []
    last_index = len(groups) - 1
    for index in range(last_index, -1, -1):
        group = groups[index]
        if group == 0:
            continue
        force_hundreds = index != last_index and group < 100
        words = _read_triplet(group, force_hundreds)
        if scales[index]:
            words = f"{words} {scales[index]}"
        parts.append(words)
    return " ".join(parts).capitalize() + " đồng./."


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_vietnam(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(VN_TZ)


def _format_quote_date(value: str | None) -> str:
    raw = _text(value)
    parsed = None
    if raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
    if parsed is None:
        parsed = datetime.now(timezone.utc)
    local = _as_vietnam(parsed)
    return f"Tp.Hồ Chí Minh {local.day} tháng {local.month} năm {local.year}"


def build_quote_file_info(clerk_id: str, payload: dict) -> dict:
    quote = None
    quote_id = _text(payload.get("quote_id"))
    if quote_id:
        quote = get_quote(quote_id, clerk_id)

    customer_payload = payload.get("customer") or {}
    if hasattr(customer_payload, "model_dump"):
        customer_payload = customer_payload.model_dump()
    quote_customer = (quote or {}).get("customers") or {}

    items = payload.get("items")
    if items is None and quote:
        items = quote.get("items") or []
    if not items:
        raise ValueError("items is required")

    normalized_items = []
    for index, item in enumerate(items, start=1):
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        quantity = float(item.get("quantity") or 0)
        selling_price = float(item.get("selling_price") or 0)
        line_total = quantity * selling_price
        vat_invoice = bool(item.get("vat_invoice"))
        row = {
            "stt": index,
            "product_name": _text(item.get("product_name")),
            "unit": _text(item.get("unit")),
            "quantity": quantity,
            "selling_price": selling_price,
            "vat_invoice": vat_invoice,
            "notes": _text(item.get("notes")),
            "line_total": line_total,
            "line_vat": round(line_total * VAT_RATE) if vat_invoice else 0,
        }
        normalized_items.append(row)

    totals = {
        "subtotal": sum(item["line_total"] for item in normalized_items),
        "vat_total": sum(item["line_vat"] for item in normalized_items),
    }
    totals["grand_total"] = totals["subtotal"] + totals["vat_total"]
    company_name = _text(customer_payload.get("company_name")) or _text(
        quote_customer.get("company_name")
    )
    if not company_name:
        raise ValueError("customer company_name is required")

    year = datetime.now().year
    return {
        "quote_id": (quote or {}).get("id"),
        "quote_number": _text(payload.get("quote_number")) or f"BG/KM-{year}",
        "quote_date_text": _format_quote_date(
            _text(payload.get("quote_date")) or (quote or {}).get("created_at")
        ),
        "customer": {
            "company_name": company_name,
            "contact_person": _text(customer_payload.get("contact_person"))
            or _text(quote_customer.get("contact_person")),
            "address": _text(customer_payload.get("address"))
            or _text(quote_customer.get("address")),
            "phone_number": _text(customer_payload.get("phone_number"))
            or _text(quote_customer.get("phone_number")),
            "tax_code": _text(customer_payload.get("tax_code"))
            or _text(quote_customer.get("tax_code")),
            "email": _text(customer_payload.get("email")),
        },
        "notes": _text(payload.get("notes"))
        if payload.get("notes") is not None
        else _text((quote or {}).get("notes")),
        "items": normalized_items,
        "subtotal": totals["subtotal"],
        "vat_total": totals["vat_total"],
        "grand_total": totals["grand_total"],
        "amount_in_words": amount_in_vietnamese_words(totals["grand_total"]),
    }


def _file_title(info: dict) -> str:
    company = info["customer"]["company_name"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return f"Bao gia - {company} - {stamp}"


async def generate_quote_file(clerk_id: str, payload: dict) -> dict:
    info = build_quote_file_info(clerk_id, payload)
    copied = copy_quote_template(_file_title(info))
    sheet_name = fill_quote_spreadsheet(copied["id"], info)
    quote_id = info.get("quote_id")
    saved_quote = None
    if quote_id:
        saved_quote = save_quote_drive_file(
            quote_id,
            clerk_id,
            copied["id"],
            copied["name"],
            copied["web_link"],
        )
    count = len(info["items"])
    return {
        "file_id": copied["id"],
        "file_name": copied["name"],
        "web_link": copied["web_link"],
        "sheet_name": sheet_name,
        "summary": f"Đã điền {count} sản phẩm vào sheet {sheet_name}.",
        "template_name": copied["template_name"],
        "quote": saved_quote or info,
    }


__all__ = [
    "amount_in_vietnamese_words",
    "build_quote_file_info",
    "generate_quote_file",
]
