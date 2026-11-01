"""FAA calendar-year commercial-service enplanements xlsx: hub class and the last two years of boardings."""

from __future__ import annotations

import io

import openpyxl
from pydantic import BaseModel

from app.data.errors import SourceError

COLUMNS = ("Locid", "Hub", "City", "Airport Name", "ST")


class EnplanementRow(BaseModel):
    locid: str
    hub_class: str  # L | M | S | N
    city: str
    name: str
    state: str
    latest_year: int
    latest: int
    previous: int


def read_enplanements(data: bytes) -> list[EnplanementRow]:
    ws = openpyxl.load_workbook(io.BytesIO(data), read_only=True).worksheets[0]
    rows = ws.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(rows)]
    idx = {h: i for i, h in enumerate(header)}
    if missing := [c for c in COLUMNS if c not in idx]:
        raise SourceError(f"FAA enplanements: missing columns {missing}; header was {header}")
    year_cols = sorted((int(h.split()[1]) + 2000, h) for h in header if h.startswith("CY ") and h.endswith("Enplanements"))
    if len(year_cols) < 2:
        raise SourceError(f"FAA enplanements: expected two 'CY NN Enplanements' columns, header was {header}")
    (_prev_year, prev_col), (latest_year, latest_col) = year_cols[-2], year_cols[-1]
    out: list[EnplanementRow] = []
    for r in rows:
        locid = r[idx["Locid"]]
        if not isinstance(locid, str) or not locid.strip():
            continue
        out.append(EnplanementRow(
            locid=locid.strip(), hub_class=str(r[idx["Hub"]] or "N").strip(), city=str(r[idx["City"]] or "").strip(),
            name=str(r[idx["Airport Name"]] or "").strip(), state=str(r[idx["ST"]] or "").strip(), latest_year=latest_year,
            latest=int(r[idx[latest_col]] or 0), previous=int(r[idx[prev_col]] or 0),
        ))
    return out
