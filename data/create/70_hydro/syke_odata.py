from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import urlopen

import pandas as pd

from .config import SYKE_ODATA_BASE


@dataclass(frozen=True)
class FetchSpec:
    entity: str
    places: list[int]
    start: datetime
    end: datetime
    extra_filter: str = ""


def _odata_qs(params: dict[str, str]) -> str:
    # SYKE endpoint is sensitive to OData query formatting; use %20 not '+' for spaces.
    return urlencode(params, quote_via=quote, safe="$',=()")


def _fetch_json(url: str, *, timeout_s: int = 60) -> dict[str, Any]:
    with urlopen(url, timeout=timeout_s) as response:
        payload = response.read()
    return json.loads(payload)


def _place_filter(places: list[int]) -> str:
    # OData validation enforces a node-count limit, so keep place lists short (<=10 ok).
    return " or ".join([f"Paikka_Id eq {pid}" for pid in places])


def _format_dt(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def fetch_rows(spec: FetchSpec, *, chunk_days: int = 120, top: int = 5000) -> pd.DataFrame:
    """
    Fetch SYKE OData rows for a small place set by chunked time windows.

    Returns a dataframe with columns: Aika (UTC datetime), Paikka_Id (int), Arvo (float).
    """
    if not spec.places:
        return pd.DataFrame(columns=["Aika", "Paikka_Id", "Arvo"])

    start = spec.start.astimezone(timezone.utc)
    end = spec.end.astimezone(timezone.utc)
    if start > end:
        raise ValueError("start must be <= end")

    frames: list[pd.DataFrame] = []
    cursor = start

    # SYKE endpoint appears to cap responses (often ~500 rows) regardless of $top in some cases.
    # Keep chunks small and paginate defensively with $skip.
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=chunk_days))
        start_s = _format_dt(cursor)
        end_s = _format_dt(chunk_end)

        filt = (
            f"Aika ge datetime'{start_s}' and Aika le datetime'{end_s}' "
            f"and ({_place_filter(spec.places)})"
        )
        if spec.extra_filter:
            filt = f"{filt} and {spec.extra_filter}"

        skip = 0
        while True:
            qs = _odata_qs(
                {
                    "$top": str(top),
                    "$skip": str(skip),
                    "$select": "Paikka_Id,Aika,Arvo",
                    "$filter": filt,
                    "$orderby": "Aika asc",
                }
            )
            url = f"{SYKE_ODATA_BASE}/{spec.entity}?{qs}"
            data = _fetch_json(url)
            rows = data.get("value", [])

            if rows:
                frames.append(pd.DataFrame(rows))

            if len(rows) < top:
                break
            skip += top

        cursor = chunk_end + timedelta(seconds=1)

    if not frames:
        return pd.DataFrame(columns=["Aika", "Paikka_Id", "Arvo"])

    df = pd.concat(frames, ignore_index=True)
    df["Aika"] = pd.to_datetime(df["Aika"], utc=True, errors="coerce")
    df["Paikka_Id"] = pd.to_numeric(df["Paikka_Id"], errors="coerce").astype("Int64")
    df["Arvo"] = pd.to_numeric(df["Arvo"], errors="coerce")
    df = df.dropna(subset=["Aika", "Paikka_Id", "Arvo"])
    df["Paikka_Id"] = df["Paikka_Id"].astype(int)

    df = df.drop_duplicates(subset=["Paikka_Id", "Aika"], keep="last")
    df = df.sort_values(["Aika", "Paikka_Id"]).reset_index(drop=True)
    return df[["Aika", "Paikka_Id", "Arvo"]]
