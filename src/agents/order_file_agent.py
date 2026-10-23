from datetime import datetime, timezone

from src.agents.quote_file_agent import (
    _format_quote_date,
    _text,
    amount_in_vietnamese_words,
)
from src.services.googleDrive import ORDER_TEMPLATE_NAME, copy_quote_template
from src.services.orders import get_order, save_order_drive_file
from src.services.quoteSheet import fill_quote_spreadsheet
from src.services.quotes import VAT_RATE


def build_order_file_info(clerk_id: str, payload: dict) -> dict:
    order = None
    order_id = _text(payload.get("order_id"))
    if order_id:
        order = get_order(order_id, clerk_id)

    customer_payload = payload.get("customer") or {}
    if hasattr(customer_payload, "model_dump"):
        customer_payload = customer_payload.model_dump()
    order_customer = (order or {}).get("customers") or {}

    items = payload.get("items")
    if items is None and order:
        items = order.get("items") or []
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
        normalized_items.append(
            {
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
        )

    totals = {
        "subtotal": sum(item["line_total"] for item in normalized_items),
        "vat_total": sum(item["line_vat"] for item in normalized_items),
    }
    totals["grand_total"] = totals["subtotal"] + totals["vat_total"]
    company_name = _text(customer_payload.get("company_name")) or _text(
        order_customer.get("company_name")
    )
    if not company_name:
        raise ValueError("customer company_name is required")

    year = datetime.now().year
    date_source = (
        _text(payload.get("order_date"))
        or _text((order or {}).get("order_date"))
        or _text((order or {}).get("created_at"))
    )
    iso_date = date_source[:10] if date_source else ""
    if len(iso_date) == 10 and iso_date[4] == "-" and iso_date[7] == "-":
        year_s, month_s, day_s = iso_date.split("-")
        date_text = f"Tp.Hồ Chí Minh {int(day_s)} tháng {int(month_s)} năm {int(year_s)}"
    else:
        date_text = _format_quote_date(date_source)
    return {
        "order_id": (order or {}).get("id"),
        "document_number": _text(payload.get("order_number")) or f"DH/KM-{year}",
        "date_text": date_text,
        "customer": {
            "company_name": company_name,
            "contact_person": _text(customer_payload.get("contact_person"))
            or _text(order_customer.get("contact_person")),
            "address": _text(customer_payload.get("address"))
            or _text(order_customer.get("address")),
            "phone_number": _text(customer_payload.get("phone_number"))
            or _text(order_customer.get("phone_number")),
            "tax_code": _text(customer_payload.get("tax_code"))
            or _text(order_customer.get("tax_code")),
            "email": _text(customer_payload.get("email")),
        },
        "notes": _text(payload.get("notes"))
        if payload.get("notes") is not None
        else _text((order or {}).get("notes")),
        "items": normalized_items,
        "subtotal": totals["subtotal"],
        "vat_total": totals["vat_total"],
        "grand_total": totals["grand_total"],
        "amount_in_words": amount_in_vietnamese_words(totals["grand_total"]),
    }


def _file_title(info: dict) -> str:
    company = info["customer"]["company_name"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return f"Don hang - {company} - {stamp}"


async def generate_order_file(clerk_id: str, payload: dict) -> dict:
    info = build_order_file_info(clerk_id, payload)
    copied = copy_quote_template(_file_title(info), ORDER_TEMPLATE_NAME)
    sheet_name = fill_quote_spreadsheet(copied["id"], info, keep_title="Đơn hàng")
    order_id = info.get("order_id")
    saved_order = None
    if order_id:
        saved_order = save_order_drive_file(
            order_id,
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
        "order": saved_order or info,
    }


__all__ = [
    "build_order_file_info",
    "generate_order_file",
]
