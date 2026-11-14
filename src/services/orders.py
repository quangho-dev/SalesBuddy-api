from datetime import date, datetime, timezone
from io import BytesIO
from uuid import UUID
from zoneinfo import ZoneInfo
import re

from openpyxl import Workbook
from openpyxl.styles import Font

from src.services.customers import CustomerNotFoundError, get_customer
from src.services.supabase import supabase
from src.services.users import ensure_user

TABLE = "orders"
ITEMS_TABLE = "order_items"
VAT_RATE = 0.1
CUSTOMER_EMBED = "id, company_name, contact_person, phone_number, address, tax_code, payment_term_days"
SELECT_FIELDS = f"*, customers({CUSTOMER_EMBED}), order_items(*)"
_ORDER_CODE = re.compile(r"^DH-(\d+)$", re.IGNORECASE)
ITEM_FIELDS = (
    "id",
    "product_id",
    "product_code",
    "product_name",
    "unit",
    "quantity",
    "selling_price",
    "vat_invoice",
    "notes",
)


class OrderNotFoundError(LookupError):
    pass


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


PAYMENT_METHODS = {
    "cash": "cash",
    "tien mat": "cash",
    "tiền mặt": "cash",
    "bank_transfer": "bank_transfer",
    "chuyen khoan": "bank_transfer",
    "chuyển khoản": "bank_transfer",
    "transfer": "bank_transfer",
}


def _payment_method(value):
    if value is None or str(value).strip() == "":
        return None
    method = PAYMENT_METHODS.get(str(value).strip().lower())
    if not method:
        raise ValueError("payment_method must be cash or bank_transfer")
    return method


def _paid_amount(value) -> float:
    amount = _number(value)
    if amount < 0:
        raise ValueError("paid_amount must be >= 0")
    return amount


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "co")
    return bool(value)


def _timestamp(value, invalid_message: str = "Thời gian giao hàng không hợp lệ.") -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(invalid_message) from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _order_timestamp(value) -> str:
    if value is None or value == "":
        return _now()
    if isinstance(value, datetime):
        return _timestamp(value, "Ngày tạo đơn hàng không hợp lệ.") or _now()
    if isinstance(value, date):
        local = datetime(value.year, value.month, value.day, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
        return local.astimezone(timezone.utc).isoformat()
    text = str(value).strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return _order_timestamp(date.fromisoformat(text))
    stamped = _timestamp(text, "Ngày tạo đơn hàng không hợp lệ.")
    if not stamped:
        raise ValueError("Ngày tạo đơn hàng không hợp lệ.")
    return stamped


def _owned_customer(customer_id: str, clerk_id: str) -> dict:
    return get_customer(customer_id, clerk_id)


def _product_id(value) -> str | None:
    text = _text(value)
    if not text:
        return None
    try:
        return str(UUID(text))
    except ValueError as error:
        raise ValueError("Mã sản phẩm không hợp lệ.") from error


def _normalize_items(items, clerk_id: str) -> list[dict]:
    if items is None:
        raise ValueError("items is required")
    if not isinstance(items, list):
        raise ValueError("items must be a list")
    if not items:
        raise ValueError("at least one item is required")

    products = _products_for_owner(clerk_id)
    by_id = {str(row["id"]): row for row in products}
    normalized = []
    for index, item in enumerate(items):
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        if not isinstance(item, dict):
            raise ValueError("each item must be an object")
        product_name = _text(item.get("product_name"))
        if not product_name:
            raise ValueError("product_name is required for each item")
        product_id = _product_id(item.get("product_id"))
        if product_id and product_id not in by_id:
            raise ValueError("Sản phẩm không thuộc tài khoản này.")
        if not product_id:
            matched = _match_product(products, {"product_name": product_name, "unit": item.get("unit")})
            product_id = str(matched["id"]) if matched else None
        product = by_id.get(product_id) if product_id else None
        product_code = _text(product.get("product_code")) if product else _text(item.get("product_code"))
        normalized.append(
            {
                "product_id": product_id,
                "product_code": product_code,
                "product_name": product_name,
                "unit": _text(item.get("unit")),
                "quantity": _number(item.get("quantity")),
                "selling_price": _number(item.get("selling_price")),
                "vat_invoice": _bool(item.get("vat_invoice")),
                "notes": _text(item.get("notes")),
                "sort_order": index,
            }
        )
    return normalized


def _to_order_row(payload: dict, clerk_id: str) -> dict:
    customer_id = str(payload.get("customer_id") or "").strip()
    if not customer_id:
        raise ValueError("customer_id is required")
    _owned_customer(customer_id, clerk_id)
    row = {
        "clerk_id": clerk_id,
        "customer_id": customer_id,
        "order_date": _order_timestamp(payload.get("order_date")),
        "notes": _text(payload.get("notes")),
        "is_paid": _bool(payload.get("is_paid")),
        "is_delivered": _bool(payload.get("is_delivered")),
        "delivered_at": _timestamp(payload.get("delivered_at")),
        "payment_method": _payment_method(payload.get("payment_method")),
        "paid_amount": _paid_amount(payload.get("paid_amount")),
    }
    quote_id = str(payload.get("quote_id") or "").strip()
    if quote_id:
        row["quote_id"] = quote_id
    return row


def _format_order(row: dict) -> dict:
    items = row.pop("order_items", None) or []
    items = sorted(items, key=lambda item: item.get("sort_order") or 0)
    row["items"] = [
        {field: item.get(field) for field in ITEM_FIELDS} for item in items
    ]
    row["order_code"] = _text(row.get("order_code"))
    row["order_date"] = _order_timestamp(row.get("order_date"))
    row["is_paid"] = _bool(row.get("is_paid"))
    row["is_delivered"] = _bool(row.get("is_delivered"))
    row["delivered_at"] = _timestamp(row.get("delivered_at"))
    row["payment_method"] = _payment_method(row.get("payment_method"))
    row["paid_amount"] = _paid_amount(row.get("paid_amount"))
    return row


def _owned_query(order_id: str, clerk_id: str):
    return (
        supabase.table(TABLE)
        .select(SELECT_FIELDS)
        .eq("id", order_id)
        .eq("clerk_id", clerk_id)
        .limit(1)
    )


def _items_grand(items: list[dict]) -> float:
    total = 0.0
    for item in items:
        line = float(item.get("quantity") or 0) * float(item.get("selling_price") or 0)
        if item.get("vat_invoice"):
            line += round(line * VAT_RATE)
        total += line
    return total


def _payment_to_record(payload: dict, items: list[dict]) -> dict | None:
    if not _bool(payload.get("is_paid")):
        return None
    method = _payment_method(payload.get("payment_method"))
    if not method:
        raise ValueError("Hãy chọn hình thức thanh toán trước khi đánh dấu đã thanh toán.")
    amount = _paid_amount(payload.get("paid_amount"))
    if amount <= 0:
        amount = _items_grand(items)
    if amount <= 0:
        raise ValueError("Tổng số tiền thanh toán phải lớn hơn 0.")
    return {"payment_method": method, "amount": amount}


def _insert_payment(clerk_id: str, order_id: str, payment: dict) -> None:
    from src.services.payments import create_payment

    create_payment(
        clerk_id,
        {
            "order_id": order_id,
            "amount": payment["amount"],
            "payment_method": payment["payment_method"],
        },
    )


def _delete_order_payments(order_id: str) -> None:
    supabase.table("payments").delete().eq("order_id", order_id).execute()


def _name_key(value) -> str:
    return re.sub(r"\s+", " ", _text(value)).casefold()


def _products_for_owner(clerk_id: str) -> list[dict]:
    result = (
        supabase.table("products")
        .select("id, product_code, name, unit, stock, created_at")
        .eq("clerk_id", clerk_id)
        .order("created_at")
        .execute()
    )
    return result.data or []


def _match_product(products: list[dict], item: dict) -> dict | None:
    product_id = _text(item.get("product_id"))
    if product_id:
        for row in products:
            if str(row.get("id")) == product_id:
                return row
        return None
    name = _name_key(item.get("product_name"))
    if not name:
        return None
    named = [row for row in products if _name_key(row.get("name")) == name]
    if not named:
        return None
    unit = _name_key(item.get("unit"))
    if unit:
        same_unit = [row for row in named if _name_key(row.get("unit")) == unit]
        if same_unit:
            return same_unit[0]
    return named[0]


def _quantities_by_product(products: list[dict], items: list[dict]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for item in items or []:
        product = _match_product(products, item)
        if not product:
            continue
        quantity = _number(item.get("quantity"))
        if quantity == 0:
            continue
        product_id = product["id"]
        totals[product_id] = totals.get(product_id, 0.0) + quantity
    return totals


def _sync_delivery_stock(
    clerk_id: str,
    before_items: list[dict],
    after_items: list[dict],
) -> None:
    """Subtract stock for quantities that are delivered now and were not before.

    before_items are lines already deducted. after_items are lines that should
    stay deducted. A smaller after list puts stock back.
    """
    products = _products_for_owner(clerk_id)
    before = _quantities_by_product(products, before_items)
    after = _quantities_by_product(products, after_items)
    changes = {
        product_id: after.get(product_id, 0.0) - before.get(product_id, 0.0)
        for product_id in set(before) | set(after)
    }
    changes = {product_id: qty for product_id, qty in changes.items() if qty}
    if not changes:
        return

    by_id = {row["id"]: row for row in products}
    applied: list[tuple[str, float]] = []
    try:
        for product_id, quantity in changes.items():
            product = by_id.get(product_id)
            if not product:
                continue
            new_stock = _number(product.get("stock")) - quantity
            result = (
                supabase.table("products")
                .update({"stock": new_stock, "updated_at": _now()})
                .eq("id", product_id)
                .eq("clerk_id", clerk_id)
                .execute()
            )
            if not result.data:
                raise RuntimeError("Failed to update product stock")
            applied.append((product_id, _number(product.get("stock"))))
    except Exception:
        for product_id, previous_stock in applied:
            supabase.table("products").update(
                {"stock": previous_stock, "updated_at": _now()}
            ).eq("id", product_id).eq("clerk_id", clerk_id).execute()
        raise


def _replace_items(order_id: str, items: list[dict]) -> None:
    supabase.table(ITEMS_TABLE).delete().eq("order_id", order_id).execute()
    rows = [{**item, "order_id": order_id} for item in items]
    result = supabase.table(ITEMS_TABLE).insert(rows).execute()
    if not result.data:
        raise RuntimeError("Failed to save order items")


def _next_order_code(clerk_id: str) -> str:
    highest = 0
    start = 0
    page_size = 1000
    while True:
        result = (
            supabase.table(TABLE)
            .select("order_code")
            .eq("clerk_id", clerk_id)
            .order("id")
            .range(start, start + page_size - 1)
            .execute()
        )
        rows = result.data or []
        for row in rows:
            match = _ORDER_CODE.match(_text(row.get("order_code")))
            if match:
                highest = max(highest, int(match.group(1)))
        if len(rows) < page_size:
            break
        start += page_size
    return f"DH-{highest + 1:05d}"


def find_order_for_quote(quote_id: str, clerk_id: str) -> dict | None:
    result = (
        supabase.table(TABLE)
        .select("id, quote_id")
        .eq("quote_id", quote_id)
        .eq("clerk_id", clerk_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def create_order(clerk_id: str, payload: dict) -> dict:
    ensure_user(clerk_id)
    quote_id = str(payload.get("quote_id") or "").strip()
    if quote_id and find_order_for_quote(quote_id, clerk_id):
        raise ValueError("Báo giá này đã có một đơn hàng.")
    items = _normalize_items(payload.get("items"), clerk_id)
    payment = _payment_to_record(payload, items)
    if payment:
        payload = {
            **payload,
            "payment_method": payment["payment_method"],
            "paid_amount": payment["amount"],
        }
    row = _to_order_row(payload, clerk_id)
    row["order_code"] = _next_order_code(clerk_id)
    result = supabase.table(TABLE).insert(row).execute()
    if not result.data:
        raise RuntimeError("Failed to create order")
    order_id = result.data[0]["id"]
    try:
        _replace_items(order_id, items)
        if payment:
            _insert_payment(clerk_id, order_id, payment)
        if _bool(payload.get("is_delivered")):
            _sync_delivery_stock(clerk_id, [], items)
    except Exception:
        supabase.table("payments").delete().eq("order_id", order_id).execute()
        supabase.table(TABLE).delete().eq("id", order_id).eq(
            "clerk_id", clerk_id
        ).execute()
        raise
    return get_order(order_id, clerk_id)


def list_orders(
    clerk_id: str,
    customer_id: str | None = None,
    is_paid: bool | None = None,
) -> list[dict]:
    page_size = 1000
    start = 0
    rows: list[dict] = []
    while True:
        query = (
            supabase.table(TABLE)
            .select(SELECT_FIELDS)
            .eq("clerk_id", clerk_id)
            .order("order_date", desc=True)
            .order("created_at", desc=True)
        )
        if customer_id:
            query = query.eq("customer_id", customer_id)
        if is_paid is not None:
            query = query.eq("is_paid", is_paid)
        result = query.range(start, start + page_size - 1).execute()
        batch = result.data or []
        rows.extend(_format_order(row) for row in batch)
        if len(batch) < page_size:
            return rows
        start += page_size


_ORDER_EXPORT_HEADERS = (
    "Mã đơn",
    "Ngày đơn",
    "Khách hàng",
    "Người liên hệ",
    "Số điện thoại",
    "Địa chỉ",
    "Mã số thuế",
    "Thanh toán",
    "Hình thức thanh toán",
    "Đã trả",
    "Còn lại",
    "Giao hàng",
    "Ngày giao",
    "VAT",
    "Số sản phẩm",
    "Sản phẩm",
    "Tạm tính",
    "Tiền VAT",
    "Tổng tiền",
    "Ghi chú",
)


def _local_moment(value) -> str:
    text = _text(value)
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).strftime("%d/%m/%Y %H:%M")


def _customer_field(order: dict, field: str) -> str:
    customer = order.get("customers") or {}
    if isinstance(customer, list):
        customer = customer[0] if customer else {}
    if not isinstance(customer, dict):
        return ""
    return _text(customer.get(field))


def _export_money(items: list[dict]) -> tuple[float, int, float]:
    subtotal = 0.0
    vat = 0
    for item in items:
        line = _number(item.get("quantity")) * _number(item.get("selling_price"))
        subtotal += line
        if item.get("vat_invoice"):
            vat += int(line * VAT_RATE + 0.5)
    return subtotal, vat, subtotal + vat


def _money_cell(value: float):
    rounded = round(value + 1e-9, 2)
    if rounded == int(rounded):
        return int(rounded)
    return rounded


def _export_item_label(item: dict) -> str:
    name = _text(item.get("product_name"))
    if not name:
        return ""
    code = _text(item.get("product_code"))
    quantity = _number(item.get("quantity"))
    unit = _text(item.get("unit"))
    amount = str(int(quantity)) if quantity == int(quantity) else str(quantity)
    label = f"{code} · {name}" if code else name
    return f"{label} × {amount} {unit}".strip()


def _order_export_row(order: dict) -> list:
    items = order.get("items") or []
    subtotal, vat, grand = _export_money(items)
    paid = _paid_amount(order.get("paid_amount"))
    remaining = 0.0 if order.get("is_paid") else max(grand - paid, 0)
    method = order.get("payment_method")
    if method == "cash":
        method_label = "Tiền mặt"
    elif method == "bank_transfer":
        method_label = "Chuyển khoản"
    else:
        method_label = ""
    products = ", ".join(label for label in (_export_item_label(item) for item in items) if label)
    return [
        _text(order.get("order_code")),
        _local_moment(order.get("order_date")),
        _customer_field(order, "company_name") or _customer_field(order, "contact_person"),
        _customer_field(order, "contact_person"),
        _customer_field(order, "phone_number"),
        _customer_field(order, "address"),
        _customer_field(order, "tax_code"),
        "Đã thanh toán" if order.get("is_paid") else "Chưa thanh toán",
        method_label,
        _money_cell(paid),
        _money_cell(remaining),
        "Đã giao hàng" if order.get("is_delivered") else "Chưa giao hàng",
        _local_moment(order.get("delivered_at")),
        "Có" if any(item.get("vat_invoice") for item in items) else "Không",
        len(items),
        products,
        _money_cell(subtotal),
        vat,
        _money_cell(grand),
        _text(order.get("notes")),
    ]


def export_orders_xlsx(clerk_id: str) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Don hang"
    sheet.append(list(_ORDER_EXPORT_HEADERS))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for order in list_orders(clerk_id):
        sheet.append(_order_export_row(order))
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    widths = (14, 18, 28, 22, 16, 36, 16, 18, 22, 14, 14, 16, 18, 10, 14, 48, 14, 14, 14, 28)
    for index, width in enumerate(widths, start=1):
        column = sheet.cell(row=1, column=index).column_letter
        sheet.column_dimensions[column].width = width
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def get_order(order_id: str, clerk_id: str) -> dict:
    result = _owned_query(order_id, clerk_id).execute()
    data = result.data or []
    if not data:
        raise OrderNotFoundError("Order not found")
    return _format_order(data[0])


def update_order(order_id: str, clerk_id: str, payload: dict) -> dict:
    existing = get_order(order_id, clerk_id)
    was_paid = bool(existing.get("is_paid"))

    updates = {}
    if "customer_id" in payload and payload["customer_id"] is not None:
        customer_id = str(payload["customer_id"]).strip()
        _owned_customer(customer_id, clerk_id)
        updates["customer_id"] = customer_id
    if "order_date" in payload and payload["order_date"] is not None:
        updates["order_date"] = _order_timestamp(payload["order_date"])
    if "notes" in payload and payload["notes"] is not None:
        updates["notes"] = _text(payload["notes"])
    if "is_paid" in payload and payload["is_paid"] is not None:
        updates["is_paid"] = _bool(payload["is_paid"])
    if "is_delivered" in payload and payload["is_delivered"] is not None:
        updates["is_delivered"] = _bool(payload["is_delivered"])
    if "delivered_at" in payload:
        updates["delivered_at"] = _timestamp(payload.get("delivered_at"))
    if "payment_method" in payload:
        updates["payment_method"] = _payment_method(payload.get("payment_method"))
    if "paid_amount" in payload and payload["paid_amount"] is not None:
        updates["paid_amount"] = _paid_amount(payload["paid_amount"])

    items = None
    if "items" in payload and payload["items"] is not None:
        items = _normalize_items(payload["items"], clerk_id)

    payment = None
    clear_payments = was_paid and "is_paid" in updates and not updates["is_paid"]
    if not was_paid:
        payment_items = items if items is not None else existing.get("items") or []
        payment_payload = {
            "is_paid": updates["is_paid"] if "is_paid" in updates else existing.get("is_paid"),
            "payment_method": (
                updates["payment_method"]
                if "payment_method" in updates
                else existing.get("payment_method")
            ),
            "paid_amount": (
                updates["paid_amount"]
                if "paid_amount" in updates
                else existing.get("paid_amount")
            ),
        }
        if "payment_method" in payload or "paid_amount" in payload:
            payment = _payment_to_record(payment_payload, payment_items)
            if payment and "is_paid" in payload:
                updates["payment_method"] = payment["payment_method"]
                updates["paid_amount"] = payment["amount"]

    if not updates and items is None:
        return get_order(order_id, clerk_id)

    updates["updated_at"] = _now()
    result = (
        supabase.table(TABLE)
        .update(updates)
        .eq("id", order_id)
        .eq("clerk_id", clerk_id)
        .execute()
    )
    if not result.data:
        raise OrderNotFoundError("Order not found")
    if items is not None:
        _replace_items(order_id, items)
    if payment:
        try:
            _insert_payment(clerk_id, order_id, payment)
        except Exception:
            supabase.table(TABLE).update(
                {"is_paid": was_paid, "updated_at": _now()}
            ).eq("id", order_id).eq("clerk_id", clerk_id).execute()
            raise
    if clear_payments:
        _delete_order_payments(order_id)

    was_delivered = bool(existing.get("is_delivered"))
    will_delivered = (
        updates["is_delivered"] if "is_delivered" in updates else was_delivered
    )
    previous_items = existing.get("items") or []
    next_items = items if items is not None else previous_items
    try:
        _sync_delivery_stock(
            clerk_id,
            previous_items if was_delivered else [],
            next_items if will_delivered else [],
        )
    except Exception:
        supabase.table(TABLE).update(
            {"is_delivered": was_delivered, "updated_at": _now()}
        ).eq("id", order_id).eq("clerk_id", clerk_id).execute()
        if items is not None and previous_items:
            _replace_items(order_id, _normalize_items(previous_items, clerk_id))
        raise
    return get_order(order_id, clerk_id)


def save_order_drive_file(
    order_id: str,
    clerk_id: str,
    file_id: str,
    file_name: str,
    web_link: str,
) -> dict:
    get_order(order_id, clerk_id)
    result = (
        supabase.table(TABLE)
        .update(
            {
                "drive_file_id": _text(file_id),
                "drive_file_name": _text(file_name),
                "drive_web_link": _text(web_link),
                "updated_at": _now(),
            }
        )
        .eq("id", order_id)
        .eq("clerk_id", clerk_id)
        .execute()
    )
    if not result.data:
        raise OrderNotFoundError("Order not found")
    return get_order(order_id, clerk_id)


def delete_order(order_id: str, clerk_id: str) -> dict:
    existing = get_order(order_id, clerk_id)
    if existing.get("is_delivered"):
        _sync_delivery_stock(clerk_id, existing.get("items") or [], [])
    try:
        supabase.table(TABLE).delete().eq("id", order_id).eq(
            "clerk_id", clerk_id
        ).execute()
    except Exception:
        if existing.get("is_delivered"):
            _sync_delivery_stock(clerk_id, [], existing.get("items") or [])
        raise
    return existing
