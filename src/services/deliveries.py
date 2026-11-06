from datetime import datetime, timezone

from src.services.customers import get_customer
from src.services.lalamove import LalamoveError, cancel_order, create_quotation, get_order as get_lalamove_order, place_order
from src.services.orders import OrderNotFoundError, get_order, update_order
from src.services.supabase import supabase
from src.services.users import ensure_user

SETTINGS_TABLE = "delivery_settings"
TABLE = "deliveries"
STOPS_TABLE = "delivery_stops"
EVENTS_TABLE = "delivery_events"
RECEIPTS_TABLE = "delivery_webhook_receipts"
OPEN_STATUSES = ("draft", "quoted", "assigning_driver", "ongoing", "picked_up")
PROVIDER_STATUS = {
    "ASSIGNING_DRIVER": "assigning_driver",
    "ON_GOING": "ongoing",
    "PICKED_UP": "picked_up",
    "COMPLETED": "completed",
    "CANCELED": "canceled",
    "CANCELLED": "canceled",
    "REJECTED": "rejected",
    "EXPIRED": "expired",
}


class DeliveryNotFoundError(LookupError):
    pass


class DeliveryError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _number(value):
    if value is None or value == "":
        return None
    return float(value)


def _phone(value: str, market: str) -> str:
    phone = _text(value).replace(" ", "").replace("-", "")
    if phone.startswith("+"):
        return phone
    if phone.startswith("00"):
        return f"+{phone[2:]}"
    if market.upper().startswith("VN") and phone.startswith("0"):
        return f"+84{phone[1:]}"
    if market.upper().startswith("VN") and phone.startswith("84"):
        return f"+{phone}"
    return phone


def _parse_time(value):
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _status_from_provider(value: str) -> str:
    return PROVIDER_STATUS.get(_text(value).upper(), "")


def _default_settings(clerk_id: str) -> dict:
    return {
        "clerk_id": clerk_id,
        "pickup_name": "",
        "pickup_phone": "",
        "pickup_address": "",
        "pickup_lat": None,
        "pickup_lng": None,
        "market": "VN",
        "default_service_type": "MOTORCYCLE",
    }


def get_settings(clerk_id: str) -> dict:
    ensure_user(clerk_id)
    result = (
        supabase.table(SETTINGS_TABLE)
        .select("*")
        .eq("clerk_id", clerk_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    if not rows:
        return _default_settings(clerk_id)
    return rows[0]


def update_settings(clerk_id: str, payload: dict) -> dict:
    current = get_settings(clerk_id)
    saved = {
        "clerk_id": clerk_id,
        "pickup_name": _text(payload.get("pickup_name", current["pickup_name"])),
        "pickup_phone": _text(payload.get("pickup_phone", current["pickup_phone"])),
        "pickup_address": _text(payload.get("pickup_address", current["pickup_address"])),
        "pickup_lat": _number(
            payload["pickup_lat"] if "pickup_lat" in payload else current["pickup_lat"]
        ),
        "pickup_lng": _number(
            payload["pickup_lng"] if "pickup_lng" in payload else current["pickup_lng"]
        ),
        "market": _text(payload.get("market", current["market"])) or "VN",
        "default_service_type": _text(
            payload.get("default_service_type", current["default_service_type"])
        )
        or "MOTORCYCLE",
        "updated_at": _now(),
    }
    result = supabase.table(SETTINGS_TABLE).upsert(saved).execute()
    if not result.data:
        raise RuntimeError("Failed to save delivery settings")
    return result.data[0]


def _load_stops(delivery_id: str) -> list[dict]:
    result = (
        supabase.table(STOPS_TABLE)
        .select("*")
        .eq("delivery_id", delivery_id)
        .order("stop_index")
        .execute()
    )
    return result.data or []


def _load_events(delivery_id: str) -> list[dict]:
    result = (
        supabase.table(EVENTS_TABLE)
        .select("id, previous_status, status, provider_status, reason, created_at")
        .eq("delivery_id", delivery_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


def _public(row: dict) -> dict:
    delivery_id = str(row["id"])
    row["stops"] = _load_stops(delivery_id)
    row["events"] = _load_events(delivery_id)
    return row


def _get_row(delivery_id: str, clerk_id: str) -> dict:
    result = (
        supabase.table(TABLE)
        .select("*")
        .eq("id", delivery_id)
        .eq("clerk_id", clerk_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    if not rows:
        raise DeliveryNotFoundError("Không tìm thấy chuyến giao.")
    return rows[0]


def get_delivery(delivery_id: str, clerk_id: str) -> dict:
    return _public(_get_row(delivery_id, clerk_id))


def list_deliveries(
    clerk_id: str,
    order_id: str | None = None,
    status: str | None = None,
    customer_id: str | None = None,
) -> list[dict]:
    ensure_user(clerk_id)
    query = (
        supabase.table(TABLE)
        .select("*")
        .eq("clerk_id", clerk_id)
        .order("created_at", desc=True)
    )
    if order_id:
        query = query.eq("order_id", order_id)
    if status:
        query = query.eq("status", status)
    if customer_id:
        query = query.eq("customer_id", customer_id)
    rows = query.execute().data or []
    return [_public(row) for row in rows]


def _open_for_order(clerk_id: str, order_id: str) -> dict | None:
    result = (
        supabase.table(TABLE)
        .select("*")
        .eq("clerk_id", clerk_id)
        .eq("order_id", order_id)
        .in_("status", list(OPEN_STATUSES))
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def _record_event(row: dict, status: str, provider_status: str = "", reason: str = "") -> None:
    previous = _text(row.get("status"))
    if previous == status and not reason:
        return
    supabase.table(EVENTS_TABLE).insert(
        {
            "clerk_id": row["clerk_id"],
            "delivery_id": row["id"],
            "previous_status": previous,
            "status": status,
            "provider_status": provider_status,
            "reason": _text(reason)[:1000],
        }
    ).execute()


def _replace_stops(delivery_id: str, clerk_id: str, stops: list[dict]) -> None:
    supabase.table(STOPS_TABLE).delete().eq("delivery_id", delivery_id).execute()
    if stops:
        supabase.table(STOPS_TABLE).insert(stops).execute()


def _stop_row(delivery_id: str, clerk_id: str, index: int, role: str, stop: dict, provider_stop_id: str) -> dict:
    return {
        "delivery_id": delivery_id,
        "clerk_id": clerk_id,
        "stop_index": index,
        "role": role,
        "contact_name": _text(stop.get("name")),
        "contact_phone": _text(stop.get("phone")),
        "address": _text(stop.get("address")),
        "lat": _number((stop.get("coordinates") or {}).get("lat", stop.get("lat"))),
        "lng": _number((stop.get("coordinates") or {}).get("lng", stop.get("lng"))),
        "remarks": _text(stop.get("remarks")),
        "provider_stop_id": _text(provider_stop_id),
    }


def _mark_order_delivered(order_id: str | None, clerk_id: str) -> None:
    if not order_id:
        return
    order = get_order(str(order_id), clerk_id)
    if order.get("is_delivered"):
        return
    update_order(
        str(order_id),
        clerk_id,
        {"is_delivered": True, "delivered_at": _now()},
    )


def _apply_provider_order(row: dict, data: dict) -> dict:
    provider_status = _text(data.get("status"))
    status = _status_from_provider(provider_status) or (
        "assigning_driver" if data.get("orderId") else row["status"]
    )
    driver = data.get("driver") if isinstance(data.get("driver"), dict) else {}
    price = data.get("priceBreakdown") if isinstance(data.get("priceBreakdown"), dict) else {}
    updates = {
        "status": status,
        "provider_order_id": _text(data.get("orderId") or row.get("provider_order_id")),
        "share_link": _text(data.get("shareLink") or row.get("share_link")),
        "driver_name": _text(driver.get("name") or row.get("driver_name")),
        "driver_phone": _text(driver.get("phone") or row.get("driver_phone")),
        "driver_plate": _text(
            driver.get("plateNumber") or driver.get("plate") or row.get("driver_plate")
        ),
        "updated_at": _now(),
    }
    total = price.get("total")
    if total not in (None, ""):
        updates["quoted_fee"] = _number(total) or 0
        updates["currency"] = _text(price.get("currency") or row.get("currency") or "VND")
    if status == "picked_up" and not row.get("picked_up_at"):
        updates["picked_up_at"] = _now()
    if status == "completed" and not row.get("completed_at"):
        updates["completed_at"] = _now()
    if status == "canceled" and not row.get("canceled_at"):
        updates["canceled_at"] = _now()
    if status != row.get("status"):
        _record_event(row, status, provider_status)
    result = (
        supabase.table(TABLE)
        .update(updates)
        .eq("id", row["id"])
        .eq("clerk_id", row["clerk_id"])
        .execute()
    )
    saved = (result.data or [row])[0]
    if status == "completed":
        _mark_order_delivered(saved.get("order_id"), saved["clerk_id"])
    return _public(saved)


def quote_delivery(clerk_id: str, payload: dict) -> dict:
    order_id = _text(payload.get("order_id"))
    if not order_id:
        raise DeliveryError("Cần chọn đơn hàng trước khi báo giá.")
    try:
        order = get_order(order_id, clerk_id)
    except OrderNotFoundError as exc:
        raise DeliveryError("Không tìm thấy đơn hàng.") from exc
    customer = get_customer(order["customer_id"], clerk_id)
    settings = get_settings(clerk_id)
    market = settings["market"]
    pickup_address = settings["pickup_address"]
    dropoff_address = _text(customer.get("address"))
    pickup_lat = settings.get("pickup_lat")
    pickup_lng = settings.get("pickup_lng")
    dropoff_lat = _number(payload.get("dropoff_lat"))
    dropoff_lng = _number(payload.get("dropoff_lng"))
    if not pickup_address or pickup_lat is None or pickup_lng is None:
        raise DeliveryError("Hãy nhập điểm lấy hàng, vĩ độ và kinh độ.")
    if not dropoff_address:
        raise DeliveryError("Khách hàng chưa có địa chỉ giao.")
    if dropoff_lat is None or dropoff_lng is None:
        raise DeliveryError("Hãy nhập vĩ độ và kinh độ điểm giao.")
    service_type = _text(payload.get("service_type")) or settings["default_service_type"]
    existing = _open_for_order(clerk_id, order_id)
    if existing and existing["status"] not in ("draft", "quoted"):
        raise DeliveryError("Đơn này đang có chuyến giao chưa kết thúc.")
    pickup_phone = _phone(settings["pickup_phone"], market)
    dropoff_phone = _phone(_text(customer.get("phone_number")), market)
    if not pickup_phone or not dropoff_phone:
        raise DeliveryError("Cần số điện thoại điểm lấy và số điện thoại khách hàng.")
    stops = [
        {
            "coordinates": {"lat": str(pickup_lat), "lng": str(pickup_lng)},
            "address": pickup_address,
        },
        {
            "coordinates": {"lat": str(dropoff_lat), "lng": str(dropoff_lng)},
            "address": dropoff_address,
        },
    ]
    try:
        quoted = create_quotation(service_type, stops, _text(payload.get("schedule_at")) or None)
    except LalamoveError as exc:
        raise DeliveryError(str(exc)) from exc
    price = quoted.get("priceBreakdown") if isinstance(quoted.get("priceBreakdown"), dict) else {}
    fields = {
        "clerk_id": clerk_id,
        "order_id": order_id,
        "customer_id": order["customer_id"],
        "provider": "lalamove",
        "status": "quoted",
        "service_type": _text(quoted.get("serviceType") or service_type),
        "quotation_id": _text(quoted.get("quotationId")),
        "quotation_expires_at": quoted.get("expiresAt"),
        "currency": _text(price.get("currency") or "VND"),
        "quoted_fee": _number(price.get("total")) or 0,
        "quoted_at": _now(),
        "failure_reason": "",
        "updated_at": _now(),
    }
    if existing:
        result = (
            supabase.table(TABLE)
            .update(fields)
            .eq("id", existing["id"])
            .eq("clerk_id", clerk_id)
            .execute()
        )
        row = (result.data or [existing])[0]
        _record_event(existing, "quoted", reason="Báo giá mới")
    else:
        fields["created_at"] = _now()
        result = supabase.table(TABLE).insert(fields).execute()
        if not result.data:
            raise RuntimeError("Failed to save delivery")
        row = result.data[0]
        _record_event({**row, "status": ""}, "quoted")
    provider_stops = quoted.get("stops") if isinstance(quoted.get("stops"), list) else []
    names = [
        {
            "name": settings["pickup_name"],
            "phone": pickup_phone,
            "address": pickup_address,
            "lat": pickup_lat,
            "lng": pickup_lng,
        },
        {
            "name": _text(customer.get("contact_person") or customer.get("company_name")),
            "phone": dropoff_phone,
            "address": dropoff_address,
            "lat": dropoff_lat,
            "lng": dropoff_lng,
        },
    ]
    stop_rows = []
    for index, local in enumerate(names):
        remote = provider_stops[index] if index < len(provider_stops) else {}
        stop_rows.append(
            _stop_row(
                row["id"],
                clerk_id,
                index,
                "pickup" if index == 0 else "dropoff",
                {**local, **(remote if isinstance(remote, dict) else {})},
                (remote or {}).get("stopId") if isinstance(remote, dict) else "",
            )
        )
    _replace_stops(row["id"], clerk_id, stop_rows)
    return get_delivery(str(row["id"]), clerk_id)


def place_delivery(clerk_id: str, delivery_id: str) -> dict:
    row = _get_row(delivery_id, clerk_id)
    if row["status"] != "quoted":
        raise DeliveryError("Chỉ đặt được chuyến vừa báo giá.")
    expires = _parse_time(row.get("quotation_expires_at"))
    if expires and expires <= datetime.now(timezone.utc):
        _record_event(row, "expired", reason="Báo giá hết hạn")
        supabase.table(TABLE).update(
            {"status": "expired", "updated_at": _now()}
        ).eq("id", row["id"]).execute()
        raise DeliveryError("Báo giá đã hết hạn. Hãy báo giá lại.")
    stops = _load_stops(str(row["id"]))
    pickup = next((stop for stop in stops if stop["role"] == "pickup"), None)
    dropoffs = [stop for stop in stops if stop["role"] == "dropoff"]
    if not pickup or not dropoffs or not pickup.get("provider_stop_id"):
        raise DeliveryError("Thiếu điểm dừng của báo giá. Hãy báo giá lại.")
    try:
        placed = place_order(
            row["quotation_id"],
            {
                "stopId": pickup["provider_stop_id"],
                "name": pickup["contact_name"],
                "phone": pickup["contact_phone"],
            },
            [
                {
                    "stopId": stop["provider_stop_id"],
                    "name": stop["contact_name"],
                    "phone": stop["contact_phone"],
                    "remarks": stop.get("remarks") or "",
                }
                for stop in dropoffs
            ],
        )
    except LalamoveError as exc:
        _record_event(row, "failed", reason=str(exc))
        supabase.table(TABLE).update(
            {"status": "failed", "failure_reason": str(exc)[:1000], "updated_at": _now()}
        ).eq("id", row["id"]).execute()
        raise DeliveryError(str(exc)) from exc
    placed_row = {**row, "placed_at": _now()}
    supabase.table(TABLE).update({"placed_at": _now()}).eq("id", row["id"]).execute()
    return _apply_provider_order(placed_row, placed)


def cancel_delivery(clerk_id: str, delivery_id: str, reason: str = "") -> dict:
    row = _get_row(delivery_id, clerk_id)
    if row["status"] in ("completed", "canceled", "rejected", "expired", "failed"):
        raise DeliveryError("Chuyến này đã kết thúc.")
    if row["status"] == "picked_up":
        raise DeliveryError("Tài xế đã lấy hàng, không hủy trên Lalamove được.")
    if row.get("provider_order_id"):
        try:
            cancel_order(row["provider_order_id"])
        except LalamoveError as exc:
            raise DeliveryError(str(exc)) from exc
    _record_event(row, "canceled", reason=reason or "Người dùng hủy")
    result = (
        supabase.table(TABLE)
        .update(
            {
                "status": "canceled",
                "failure_reason": _text(reason)[:1000],
                "canceled_at": _now(),
                "updated_at": _now(),
            }
        )
        .eq("id", row["id"])
        .execute()
    )
    return _public((result.data or [row])[0])


def refresh_delivery(clerk_id: str, delivery_id: str) -> dict:
    row = _get_row(delivery_id, clerk_id)
    if not row.get("provider_order_id"):
        return _public(row)
    try:
        remote = get_lalamove_order(row["provider_order_id"])
    except LalamoveError as exc:
        raise DeliveryError(str(exc)) from exc
    return _apply_provider_order(row, remote)


def _find_by_provider_order(provider_order_id: str) -> dict | None:
    result = (
        supabase.table(TABLE)
        .select("*")
        .eq("provider", "lalamove")
        .eq("provider_order_id", provider_order_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def receive_lalamove_webhook(payload: dict) -> dict:
    event_id = _text(
        payload.get("eventId")
        or payload.get("event_id")
        or payload.get("id")
    )
    if not event_id:
        event_id = f"unsigned-{_now()}"
    existing = (
        supabase.table(RECEIPTS_TABLE)
        .select("id")
        .eq("provider", "lalamove")
        .eq("event_id", event_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        return {"duplicate": True}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    order = data.get("order") if isinstance(data.get("order"), dict) else data
    provider_order_id = _text(order.get("orderId") or order.get("id"))
    row = _find_by_provider_order(provider_order_id) if provider_order_id else None
    supabase.table(RECEIPTS_TABLE).insert(
        {
            "provider": "lalamove",
            "event_id": event_id,
            "delivery_id": row["id"] if row else None,
            "payload": payload,
        }
    ).execute()
    if not row:
        return {"matched": False}
    driver = data.get("driver") if isinstance(data.get("driver"), dict) else {}
    merged = {**order, "driver": driver or order.get("driver")}
    _apply_provider_order(row, merged)
    return {"matched": True}
