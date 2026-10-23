from googleapiclient.errors import HttpError

from src.services.googleDrive import sheets_service


def _batch(sheets, spreadsheet_id: str, requests: list[dict]) -> None:
    if not requests:
        return
    try:
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests},
        ).execute()
    except HttpError:
        if len(requests) == 1:
            raise
        for request in requests:
            try:
                sheets.spreadsheets().batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body={"requests": [request]},
                ).execute()
            except HttpError:
                continue


def _norm(value) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _row_text(row: list) -> str:
    return " ".join(_norm(cell) for cell in row)


def _find_row(rows: list[list], *needles: str, start: int = 0) -> int:
    wanted = [_norm(needle) for needle in needles]
    for index in range(start, len(rows)):
        text = _row_text(rows[index])
        if all(needle in text for needle in wanted):
            return index
    return -1


def _quote_sheet(spreadsheet: dict) -> dict:
    sheets = spreadsheet.get("sheets") or []
    exact = None
    first_quote = None
    for sheet in sheets:
        title = ((sheet.get("properties") or {}).get("title") or "").strip()
        lowered = title.lower()
        if lowered == "báo giá":
            exact = sheet
            break
        if first_quote is None and lowered.startswith("báo giá"):
            first_quote = sheet
    sheet = exact or first_quote
    if sheet:
        return sheet
    if not sheets:
        raise RuntimeError("Quote template has no sheets")
    return sheets[0]


def _a1(sheet_name: str, range_a1: str) -> str:
    escaped = sheet_name.replace("'", "''")
    return f"'{escaped}'!{range_a1}"


def _read_rows(sheets, spreadsheet_id: str, sheet_name: str) -> list[list]:
    result = (
        sheets.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=_a1(sheet_name, "A1:H200"),
            valueRenderOption="UNFORMATTED_VALUE",
        )
        .execute()
    )
    return result.get("values") or []


def _keep_filled_sheet(
    sheets, spreadsheet_id: str, keep_sheet_id: int, keep_title: str
) -> str:
    spreadsheet = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    requests = []
    for sheet in spreadsheet.get("sheets") or []:
        properties = sheet.get("properties") or {}
        sheet_id = properties.get("sheetId")
        if sheet_id != keep_sheet_id:
            requests.append({"deleteSheet": {"sheetId": sheet_id}})
    requests.append(
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": keep_sheet_id,
                    "title": keep_title,
                    "index": 0,
                },
                "fields": "title,index",
            }
        }
    )
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests},
    ).execute()
    return keep_title


def fill_quote_spreadsheet(
    spreadsheet_id: str, info: dict, keep_title: str = "Báo giá"
) -> str:
    items = info.get("items") or []
    if not items:
        raise ValueError("items is required")

    sheets = sheets_service()
    spreadsheet = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet = _quote_sheet(spreadsheet)
    properties = sheet.get("properties") or {}
    sheet_name = properties.get("title") or "Báo giá"
    sheet_id = properties.get("sheetId")
    rows = _read_rows(sheets, spreadsheet_id, sheet_name)

    header_idx = _find_row(rows, "stt", "tên hàng")
    if header_idx < 0:
        header_idx = _find_row(rows, "stt")
    footer_idx = _find_row(rows, "tổng cộng", start=max(header_idx + 1, 0))
    if header_idx < 0 or footer_idx < 0 or footer_idx <= header_idx:
        raise RuntimeError("Quote template is missing the product table")

    needed = len(items)
    existing = footer_idx - header_idx - 1
    requests = []
    item_start = header_idx + 1
    if needed > existing:
        start = footer_idx
        requests.append(
            {
                "insertDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": start,
                        "endIndex": start + (needed - existing),
                    },
                    "inheritFromBefore": True,
                }
            }
        )
        footer_idx += needed - existing
    elif needed < existing:
        start = item_start + needed
        requests.append(
            {
                "deleteDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": start,
                        "endIndex": footer_idx,
                    }
                }
            }
        )
        footer_idx = start
    _batch(sheets, spreadsheet_id, requests)
    _batch(
        sheets,
        spreadsheet_id,
        [
            {
                "unmergeCells": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": item_start,
                        "endRowIndex": max(footer_idx, item_start + needed),
                        "startColumnIndex": 0,
                        "endColumnIndex": 8,
                    }
                }
            },
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": item_start,
                        "endIndex": max(footer_idx, item_start + needed),
                    },
                    "properties": {"hiddenByUser": False, "pixelSize": 24},
                    "fields": "hiddenByUser,pixelSize",
                }
            },
        ],
    )
    rows = _read_rows(sheets, spreadsheet_id, sheet_name)
    header_idx = _find_row(rows, "stt", "tên hàng")
    if header_idx < 0:
        header_idx = _find_row(rows, "stt")
    footer_idx = _find_row(rows, "tổng cộng", start=max(header_idx + 1, 0))
    if header_idx < 0 or footer_idx < 0:
        raise RuntimeError("Quote template is missing the product table after resize")

    customer = info.get("customer") or {}
    item_values = [
        [
            item.get("stt"),
            item.get("product_name") or "",
            item.get("unit") or "",
            item.get("quantity") or 0,
            item.get("selling_price") or 0,
            item.get("line_total") or 0,
            "",
            item.get("notes") or "",
        ]
        for item in items
    ]
    first_item_row = header_idx + 2
    last_item_row = header_idx + 1 + needed
    vat_idx = _find_row(rows, "vat10", start=footer_idx)
    if vat_idx < 0:
        vat_idx = _find_row(rows, "vat", start=footer_idx)
    ship_idx = _find_row(rows, "vận chuyển", start=footer_idx)
    grand_idx = _find_row(rows, "tổng giá trị", start=footer_idx)
    words_idx = _find_row(rows, "bằng chữ", start=footer_idx)

    updates = [
        {
            "range": _a1(sheet_name, "B8"),
            "values": [[
                f"(Số :     {info.get('document_number') or info.get('quote_number') or ''})"
            ]],
        },
        {
            "range": _a1(sheet_name, "D8"),
            "values": [[
                info.get("date_text") or info.get("quote_date_text") or ""
            ]],
        },
        {
            "range": _a1(sheet_name, "A10"),
            "values": [[f"Kính gửi: {customer.get('company_name') or ''}"]],
        },
        {
            "range": _a1(sheet_name, "A11"),
            "values": [[f"Địa chỉ: {customer.get('address') or ''}"]],
        },
        {
            "range": _a1(sheet_name, "A12"),
            "values": [[f"Mã số thuế: {customer.get('tax_code') or ''}"]],
        },
        {
            "range": _a1(sheet_name, "A13"),
            "values": [[f"Số điện thoại: {customer.get('phone_number') or ''}"]],
        },
        {
            "range": _a1(sheet_name, f"A{first_item_row}:H{last_item_row}"),
            "values": item_values,
        },
        {
            "range": _a1(sheet_name, f"F{footer_idx + 1}"),
            "values": [[info.get("subtotal") or 0]],
        },
    ]
    if vat_idx >= 0:
        updates.append(
            {
                "range": _a1(sheet_name, f"F{vat_idx + 1}"),
                "values": [[info.get("vat_total") or 0]],
            }
        )
    if ship_idx >= 0:
        updates.append(
            {"range": _a1(sheet_name, f"F{ship_idx + 1}"), "values": [[0]]}
        )
    if grand_idx >= 0:
        updates.append(
            {
                "range": _a1(sheet_name, f"F{grand_idx + 1}"),
                "values": [[info.get("grand_total") or 0]],
            }
        )
    if words_idx >= 0:
        updates.append(
            {
                "range": _a1(sheet_name, f"A{words_idx + 1}"),
                "values": [[f"Bằng chữ: {info.get('amount_in_words') or ''}"]],
            }
        )

    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"valueInputOption": "USER_ENTERED", "data": updates},
    ).execute()
    return _keep_filled_sheet(sheets, spreadsheet_id, sheet_id, keep_title)
