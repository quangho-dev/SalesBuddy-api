import json
from uuid import uuid4

import redis
from src.config.index import appConfig
from src.services.targetCustomers import FIELDS, get_owned_target_customer_list

SESSION_TTL_SECONDS = 60 * 60
KEY_PREFIX = "target_customer_search:"

_redis = redis.from_url(appConfig["redis_url"], decode_responses=True)


class SearchSessionNotFoundError(LookupError):
    pass


class SearchSessionCustomerNotFoundError(LookupError):
    pass


def _key(search_id: str) -> str:
    return f"{KEY_PREFIX}{search_id}"


def _to_session_customer(customer: dict) -> dict:
    return {
        "id": str(uuid4()),
        **{field: customer.get(field) or "" for field in FIELDS},
    }


def _load_owned_session(search_id: str, clerk_id: str) -> dict:
    raw = _redis.get(_key(search_id))
    if not raw:
        raise SearchSessionNotFoundError("Search session not found")

    session = json.loads(raw)
    if session.get("clerk_id") != clerk_id:
        raise SearchSessionNotFoundError("Search session not found")
    return session


def _save_session(session: dict) -> None:
    _redis.set(
        _key(session["search_id"]),
        json.dumps(session),
        ex=SESSION_TTL_SECONDS,
    )


def create_search_session(
    clerk_id: str,
    list_id: str,
    query: str,
    customers: list[dict],
) -> dict:
    customer_list = get_owned_target_customer_list(list_id, clerk_id)
    if not customer_list:
        raise LookupError("Target customer list not found")

    session = {
        "search_id": str(uuid4()),
        "clerk_id": clerk_id,
        "query": query,
        "list": customer_list,
        "customers": [_to_session_customer(c) for c in customers],
    }
    _save_session(session)
    return session


def get_search_session(search_id: str, clerk_id: str) -> dict:
    return _load_owned_session(search_id, clerk_id)


def remove_customer_from_session(
    search_id: str, clerk_id: str, customer_id: str
) -> dict:
    session = _load_owned_session(search_id, clerk_id)
    remaining = [
        customer
        for customer in session["customers"]
        if customer.get("id") != customer_id
    ]
    if len(remaining) == len(session["customers"]):
        raise SearchSessionCustomerNotFoundError("Target customer not found")

    session["customers"] = remaining
    _save_session(session)
    return session


def delete_search_session(search_id: str) -> None:
    _redis.delete(_key(search_id))
