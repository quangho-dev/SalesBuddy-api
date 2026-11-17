from datetime import datetime, timezone
import re

from src.services.clerkAuth import clerk_profiles
from src.services.supabase import supabase
from src.services.users import remember_user_email

USERS_TABLE = "users"
TABLE = "organizations"
_SPACE = re.compile(r"\s+")


class OrganizationInputError(ValueError):
    pass


class StaffAccessError(PermissionError):
    pass


SALES_MANAGER_ROLE = "sales_supervisor"
SALES_REPRESENTATIVE_ROLE = "sales_representative"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_name(value) -> str:
    return _SPACE.sub(" ", str(value or "").strip())


def _clean_tax(value) -> str:
    return _SPACE.sub("", str(value or "").strip()).upper()


def _name_key(value) -> str:
    return _clean_name(value).casefold()


def _format_organization(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "id": row.get("id"),
        "name": _clean_name(row.get("name")),
        "address": str(row.get("address") or "").strip(),
        "tax_code": _clean_tax(row.get("tax_code")),
    }


def _format_user(user: dict, organization: dict | None) -> dict:
    organization_id = user.get("organization_id")
    return {
        "clerk_id": user.get("clerk_id"),
        "role": user.get("role") or "sales_representative",
        "organization_id": organization_id if organization else None,
        "organization": _format_organization(organization),
    }


def _list_organizations() -> list[dict]:
    page_size = 1000
    start = 0
    rows: list[dict] = []
    while True:
        result = (
            supabase.table(TABLE)
            .select("id, name, address, tax_code")
            .order("id")
            .range(start, start + page_size - 1)
            .execute()
        )
        batch = result.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            return rows
        start += page_size


def _ensure_user(clerk_id: str) -> dict:
    existing = (
        supabase.table(USERS_TABLE)
        .select("clerk_id, role, organization_id")
        .eq("clerk_id", clerk_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        return existing.data[0]
    created = (
        supabase.table(USERS_TABLE)
        .insert({"clerk_id": clerk_id})
        .execute()
    )
    if not created.data:
        raise RuntimeError("Failed to create user")
    return created.data[0]


def _organization_by_id(organization_id: str) -> dict | None:
    result = (
        supabase.table(TABLE)
        .select("id, name, address, tax_code")
        .eq("id", organization_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def _insert_organization(name: str, tax_code: str) -> dict:
    result = (
        supabase.table(TABLE)
        .insert({"name": name, "tax_code": tax_code, "address": ""})
        .execute()
    )
    if not result.data:
        raise RuntimeError("Failed to create organization")
    return result.data[0]


def _update_organization(organization_id: str, changes: dict) -> dict:
    result = (
        supabase.table(TABLE)
        .update({**changes, "updated_at": _now()})
        .eq("id", organization_id)
        .execute()
    )
    if not result.data:
        raise RuntimeError("Failed to update organization")
    return result.data[0]


def _match_organization(name: str, tax_code: str) -> dict | None:
    organizations = _list_organizations()
    if tax_code:
        tax_matches = [
            row for row in organizations if _clean_tax(row.get("tax_code")) == tax_code
        ]
        if len(tax_matches) > 1:
            raise OrganizationInputError("Mã số thuế đang gắn với nhiều tổ chức.")
        if tax_matches:
            chosen = tax_matches[0]
            if name and not _clean_name(chosen.get("name")):
                return _update_organization(chosen["id"], {"name": name})
            return chosen

    if not name:
        return None

    name_matches = [
        row for row in organizations if _name_key(row.get("name")) == _name_key(name)
    ]
    if tax_code:
        same_tax = [
            row for row in name_matches if _clean_tax(row.get("tax_code")) in ("", tax_code)
        ]
        if len(same_tax) == 1:
            chosen = same_tax[0]
            if not _clean_tax(chosen.get("tax_code")):
                return _update_organization(chosen["id"], {"tax_code": tax_code})
            return chosen
        return None

    if len(name_matches) > 1:
        raise OrganizationInputError("Có nhiều tổ chức cùng tên. Hãy nhập mã số thuế.")
    if len(name_matches) == 1:
        return name_matches[0]
    return None


def _customer_counts(owner_ids: list[str]) -> dict[str, int]:
    if not owner_ids:
        return {}
    counts = {owner_id: 0 for owner_id in owner_ids}
    page_size = 1000
    start = 0
    while True:
        result = (
            supabase.table("customers")
            .select("clerk_id")
            .in_("clerk_id", owner_ids)
            .order("id")
            .range(start, start + page_size - 1)
            .execute()
        )
        batch = result.data or []
        for row in batch:
            owner_id = row.get("clerk_id")
            if owner_id in counts:
                counts[owner_id] += 1
        if len(batch) < page_size:
            return counts
        start += page_size


def list_sales_staff(clerk_id: str) -> list[dict]:
    viewer = (
        supabase.table(USERS_TABLE)
        .select("clerk_id, role, organization_id")
        .eq("clerk_id", clerk_id)
        .limit(1)
        .execute()
    )
    rows = viewer.data or []
    user = rows[0] if rows else _ensure_user(clerk_id)
    organization_id = str(user.get("organization_id") or "").strip()
    if user.get("role") != SALES_MANAGER_ROLE or not organization_id:
        raise StaffAccessError("Chỉ quản lý sales mới xem được danh sách nhân viên.")
    result = (
        supabase.table(USERS_TABLE)
        .select("clerk_id, email, role")
        .eq("organization_id", organization_id)
        .eq("role", SALES_REPRESENTATIVE_ROLE)
        .order("email")
        .execute()
    )
    staff = result.data or []
    owner_ids = [row.get("clerk_id") for row in staff if row.get("clerk_id")]
    counts = _customer_counts(owner_ids)
    profiles = clerk_profiles(owner_ids)
    listed = []
    for row in staff:
        owner_id = row.get("clerk_id")
        profile = profiles.get(owner_id) or {}
        listed.append(
            {
                "clerk_id": owner_id,
                "name": str(profile.get("name") or "").strip(),
                "email": remember_user_email(owner_id, row.get("email"), profile.get("email")),
                "role": row.get("role") or SALES_REPRESENTATIVE_ROLE,
                "customer_count": counts.get(owner_id, 0),
            }
        )
    return listed


def get_current_user(clerk_id: str) -> dict:
    user = _ensure_user(clerk_id)
    remember_user_email(clerk_id)
    organization_id = str(user.get("organization_id") or "").strip()
    organization = _organization_by_id(organization_id) if organization_id else None
    return _format_user(user, organization)


def join_organization(clerk_id: str, name: str, tax_code: str) -> dict:
    name = _clean_name(name)
    tax_code = _clean_tax(tax_code)
    if not name and not tax_code:
        raise OrganizationInputError("Hãy nhập tên tổ chức hoặc mã số thuế.")

    _ensure_user(clerk_id)
    try:
        organization = _match_organization(name, tax_code) or _insert_organization(name, tax_code)
    except Exception as error:
        if tax_code and "organizations_tax_code_unique_idx" in str(error):
            organization = _match_organization("", tax_code)
            if not organization:
                raise
        else:
            raise

    updated = (
        supabase.table(USERS_TABLE)
        .update({"organization_id": organization["id"]})
        .eq("clerk_id", clerk_id)
        .execute()
    )
    if not updated.data:
        raise RuntimeError("Failed to assign organization")
    return _format_user(updated.data[0], organization)
