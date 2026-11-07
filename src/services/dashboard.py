from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import re

from src.services.orders import VAT_RATE
from src.services.supabase import supabase

VN = ZoneInfo("Asia/Ho_Chi_Minh")
PERIODS = ("day", "week", "month", "year")
BUCKETS = {"day": "hour", "week": "day", "month": "day", "year": "month"}
PAGE_SIZE = 1000

ORDER_SELECT = (
    "id, customer_id, order_date, is_paid, paid_amount, "
    "customers(id, customer_code, company_name, contact_person), "
    "order_items(product_id, product_code, product_name, unit, quantity, selling_price, vat_invoice)"
)


def period_windows(now: datetime | None = None) -> dict[str, tuple[datetime, datetime]]:
    moment = (now or datetime.now(VN)).astimezone(VN)
    day_start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - timedelta(days=day_start.weekday())
    month_start = day_start.replace(day=1)
    year_start = day_start.replace(month=1, day=1)
    return {
        "day": (day_start, day_start + timedelta(days=1)),
        "week": (week_start, week_start + timedelta(days=7)),
        "month": (month_start, _add_months(month_start, 1)),
        "year": (year_start, year_start.replace(year=year_start.year + 1)),
    }


def build_dashboard(
    orders: list[dict],
    customers: list[dict],
    unpaid_orders: list[dict],
    period: str,
    limit: int = 5,
    now: datetime | None = None,
) -> dict:
    if period not in PERIODS:
        raise ValueError("period must be day, week, month, or year")
    windows = period_windows(now)
    selected_start, selected_end = windows[period]
    bucket = BUCKETS[period]
    series = {
        key: {"key": key, "revenue": 0, "order_count": 0}
        for key in _bucket_keys(selected_start, selected_end, bucket)
    }
    revenue = {name: 0 for name in PERIODS}
    order_count = {name: 0 for name in PERIODS}
    customers_by_id: dict[str, dict] = {}
    products_by_key: dict[tuple, dict] = {}

    for order in orders:
        moment = _parse_timestamp(order.get("order_date"))
        if moment is None:
            continue
        total = _order_revenue(order)
        matched = [
            name
            for name, (start, end) in windows.items()
            if start <= moment < end
        ]
        for name in matched:
            revenue[name] += total
            order_count[name] += 1
        if not (selected_start <= moment < selected_end):
            continue
        point = series.get(_bucket_key(moment, bucket))
        if point is not None:
            point["revenue"] += total
            point["order_count"] += 1
        _add_customer(customers_by_id, order, total)
        _add_products(products_by_key, order)

    new_customer_count = {name: 0 for name in PERIODS}
    for customer in customers:
        created = _parse_timestamp(customer.get("created_at"))
        if created is None:
            continue
        for name, (start, end) in windows.items():
            if start <= created < end:
                new_customer_count[name] += 1

    receivable = 0
    receivable_order_count = 0
    for order in unpaid_orders:
        if order.get("is_paid"):
            continue
        remaining = _order_revenue(order) - _money_number(order.get("paid_amount"))
        if remaining <= 0:
            continue
        receivable += remaining
        receivable_order_count += 1

    top_customers = sorted(
        customers_by_id.values(),
        key=lambda row: (
            -row["revenue"],
            -row["order_count"],
            row["company_name"].casefold(),
            row["customer_id"],
        ),
    )[:limit]
    top_products = sorted(
        products_by_key.values(),
        key=lambda row: (
            -row["quantity"],
            -row["revenue"],
            row["product_name"].casefold(),
            row["product_code"].casefold(),
        ),
    )[:limit]

    return {
        "timezone": "Asia/Ho_Chi_Minh",
        "period": period,
        "from": _iso(selected_start),
        "to": _iso(selected_end),
        "ranges": {
            name: {"from": _iso(start), "to": _iso(end)}
            for name, (start, end) in windows.items()
        },
        "revenue": revenue,
        "order_count": order_count,
        "new_customer_count": new_customer_count,
        "receivable": receivable,
        "receivable_order_count": receivable_order_count,
        "revenue_series": {
            "bucket": bucket,
            "points": list(series.values()),
        },
        "top_customers": [_public_customer(row) for row in top_customers],
        "top_products": [_public_product(row) for row in top_products],
    }


def get_dashboard(clerk_id: str, period: str = "month", limit: int = 5) -> dict:
    if period not in PERIODS:
        raise ValueError("period must be day, week, month, or year")
    windows = period_windows()
    coverage_start = min(start for start, _end in windows.values())
    coverage_end = max(end for _start, end in windows.values())
    orders = _fetch_orders(clerk_id, coverage_start, coverage_end)
    customers = _fetch_customers(clerk_id, coverage_start, coverage_end)
    unpaid = _fetch_unpaid_orders(clerk_id)
    return build_dashboard(orders, customers, unpaid, period, limit)


def _add_months(moment: datetime, months: int) -> datetime:
    month_index = moment.month - 1 + months
    year = moment.year + month_index // 12
    month = month_index % 12 + 1
    return moment.replace(year=year, month=month)


def _iso(moment: datetime) -> str:
    return moment.astimezone(VN).isoformat()


def _parse_timestamp(value) -> datetime | None:
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
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(VN)


def _money_number(value) -> int:
    if value is None or value == "":
        return 0
    return int(round(float(value)))


def _line_revenue(item: dict) -> int:
    line = float(item.get("quantity") or 0) * float(item.get("selling_price") or 0)
    if item.get("vat_invoice"):
        line += round(line * VAT_RATE)
    return int(round(line))


def _order_items(order: dict) -> list[dict]:
    items = order.get("order_items")
    if items is None:
        items = order.get("items")
    return items or []


def _order_revenue(order: dict) -> int:
    return sum(_line_revenue(item) for item in _order_items(order))


def _bucket_key(moment: datetime, bucket: str) -> str:
    local = moment.astimezone(VN)
    if bucket == "hour":
        return local.strftime("%Y-%m-%dT%H")
    if bucket == "month":
        return local.strftime("%Y-%m")
    return local.strftime("%Y-%m-%d")


def _bucket_keys(start: datetime, end: datetime, bucket: str) -> list[str]:
    keys = []
    cursor = start
    while cursor < end:
        keys.append(_bucket_key(cursor, bucket))
        if bucket == "hour":
            cursor += timedelta(hours=1)
        elif bucket == "day":
            cursor += timedelta(days=1)
        else:
            cursor = _add_months(cursor, 1)
    return keys


def _customer_row(order: dict) -> dict:
    customer = order.get("customers")
    if isinstance(customer, list):
        customer = customer[0] if customer else None
    return customer or {}


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _add_customer(groups: dict[str, dict], order: dict, total: int) -> None:
    customer_id = _text(order.get("customer_id"))
    if not customer_id:
        return
    customer = _customer_row(order)
    current = groups.get(customer_id)
    if current is None:
        groups[customer_id] = {
            "customer_id": customer_id,
            "customer_code": _text(customer.get("customer_code")),
            "company_name": _text(customer.get("company_name")),
            "contact_person": _text(customer.get("contact_person")),
            "revenue": total,
            "order_count": 1,
        }
        return
    current["revenue"] += total
    current["order_count"] += 1
    if not current["company_name"]:
        current["company_name"] = _text(customer.get("company_name"))
    if not current["contact_person"]:
        current["contact_person"] = _text(customer.get("contact_person"))
    if not current["customer_code"]:
        current["customer_code"] = _text(customer.get("customer_code"))


def _fold(value) -> str:
    return re.sub(r"\s+", " ", _text(value)).casefold()


def _product_key(item: dict) -> tuple:
    product_id = _text(item.get("product_id"))
    if product_id:
        return ("id", product_id)
    return ("custom", _fold(item.get("product_name")), _fold(item.get("unit")))


def _add_products(groups: dict[tuple, dict], order: dict) -> None:
    order_id = _text(order.get("id"))
    for item in _order_items(order):
        key = _product_key(item)
        quantity = float(item.get("quantity") or 0)
        revenue = _line_revenue(item)
        current = groups.get(key)
        if current is None:
            current = {
                "product_id": key[1] if key[0] == "id" else None,
                "product_code": _text(item.get("product_code")),
                "product_name": _text(item.get("product_name")),
                "unit": _text(item.get("unit")),
                "quantity": 0.0,
                "revenue": 0,
                "order_ids": set(),
                "_label_quantity": -1.0,
            }
            groups[key] = current
        current["quantity"] += quantity
        current["revenue"] += revenue
        if order_id:
            current["order_ids"].add(order_id)
        if quantity > current["_label_quantity"]:
            current["_label_quantity"] = quantity
            current["product_code"] = _text(item.get("product_code"))
            current["product_name"] = _text(item.get("product_name"))
            current["unit"] = _text(item.get("unit"))


def _quantity(value: float) -> int | float:
    rounded = round(value)
    if abs(value - rounded) < 1e-9:
        return int(rounded)
    return value


def _public_customer(row: dict) -> dict:
    return {
        "customer_id": row["customer_id"],
        "customer_code": row["customer_code"],
        "company_name": row["company_name"],
        "contact_person": row["contact_person"],
        "revenue": row["revenue"],
        "order_count": row["order_count"],
    }


def _public_product(row: dict) -> dict:
    return {
        "product_id": row["product_id"],
        "product_code": row["product_code"],
        "product_name": row["product_name"],
        "unit": row["unit"],
        "quantity": _quantity(row["quantity"]),
        "revenue": row["revenue"],
        "order_count": len(row["order_ids"]),
    }


def _fetch_all(query_factory) -> list[dict]:
    rows: list[dict] = []
    start = 0
    while True:
        result = query_factory().range(start, start + PAGE_SIZE - 1).execute()
        batch = result.data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            return rows
        start += PAGE_SIZE


def _fetch_orders(clerk_id: str, start: datetime, end: datetime) -> list[dict]:
    start_iso = start.astimezone(timezone.utc).isoformat()
    end_iso = end.astimezone(timezone.utc).isoformat()

    def query():
        return (
            supabase.table("orders")
            .select(ORDER_SELECT)
            .eq("clerk_id", clerk_id)
            .gte("order_date", start_iso)
            .lt("order_date", end_iso)
            .order("id")
        )

    return _fetch_all(query)


def _fetch_unpaid_orders(clerk_id: str) -> list[dict]:
    def query():
        return (
            supabase.table("orders")
            .select(ORDER_SELECT)
            .eq("clerk_id", clerk_id)
            .eq("is_paid", False)
            .order("id")
        )

    return _fetch_all(query)


def _fetch_customers(clerk_id: str, start: datetime, end: datetime) -> list[dict]:
    start_iso = start.astimezone(timezone.utc).isoformat()
    end_iso = end.astimezone(timezone.utc).isoformat()

    def query():
        return (
            supabase.table("customers")
            .select("id, created_at")
            .eq("clerk_id", clerk_id)
            .gte("created_at", start_iso)
            .lt("created_at", end_iso)
            .order("id")
        )

    return _fetch_all(query)
