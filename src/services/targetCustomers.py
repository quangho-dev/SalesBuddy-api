from src.services.supabase import supabase
from src.services.users import ensure_user

TABLE = "target_customers"
LIST_TABLE = "target_customer_list"
FIELDS = (
    "name",
    "summary_about_the_target_customer",
    "website",
    "address",
    "phone_number",
    "facebook",
    "reason_to_choose",
)


def _to_row(customer: dict, list_id: str) -> dict:
    return {
        **{field: customer.get(field) or "" for field in FIELDS},
        "target_customer_list_id": list_id,
    }


def create_target_customer_list(
    clerk_id: str, name: str, description: str
) -> dict:
    ensure_user(clerk_id)
    result = (
        supabase.table(LIST_TABLE)
        .insert(
            {
                "name": name.strip() or "Danh sách khách hàng mục tiêu",
                "description": description.strip() or name.strip(),
                "clerk_id": clerk_id,
            }
        )
        .execute()
    )
    if not result.data:
        raise RuntimeError("Failed to create target customer list")
    return result.data[0]


def get_owned_target_customer_list(list_id: str, clerk_id: str) -> dict | None:
    result = (
        supabase.table(LIST_TABLE)
        .select("*")
        .eq("id", list_id)
        .eq("clerk_id", clerk_id)
        .limit(1)
        .execute()
    )
    data = result.data or []
    return data[0] if data else None


def save_target_customers(customers: list[dict], list_id: str) -> list[dict]:
    if not customers:
        return []

    result = (
        supabase.table(TABLE)
        .insert([_to_row(c, list_id) for c in customers])
        .execute()
    )
    return result.data or []


def save_search_results(
    clerk_id: str,
    customers: list[dict],
    list_id: str,
) -> dict:
    customer_list = get_owned_target_customer_list(list_id, clerk_id)
    if not customer_list:
        raise LookupError("Target customer list not found")

    if not customers:
        return {"list": customer_list, "customers": []}

    saved = save_target_customers(customers, customer_list["id"])
    return {"list": customer_list, "customers": saved}


def list_target_customer_lists(clerk_id: str) -> list[dict]:
    result = (
        supabase.table(LIST_TABLE)
        .select("*")
        .eq("clerk_id", clerk_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


def list_known_target_customers(clerk_id: str, limit: int = 200) -> list[dict]:
    lists = (
        supabase.table(LIST_TABLE)
        .select("id")
        .eq("clerk_id", clerk_id)
        .execute()
    )
    list_ids = [row["id"] for row in (lists.data or [])]
    if not list_ids:
        return []

    result = (
        supabase.table(TABLE)
        .select("name, website, facebook")
        .in_("target_customer_list_id", list_ids)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []
