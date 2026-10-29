"""Counting only - no Streamlit, no database. Turns the raw api_usage_log
rows into the daily / monthly / yearly numbers the dashboard shows."""

import pandas as pd

TIMEZONE = "Asia/Kolkata"
PERIOD_FORMATS = {"Daily": "%Y-%m-%d", "Monthly": "%Y-%m", "Yearly": "%Y"}


def prepare(logs: pd.DataFrame, stores: pd.DataFrame) -> pd.DataFrame:
    """Add Indian-time columns and the store name to every log row."""
    columns = ["store_id", "store_name", "api_name", "status", "model",
               "duration_seconds", "error_message", "when"]
    if logs.empty:
        return pd.DataFrame(columns=columns)
    data = logs.copy()
    data["when"] = pd.to_datetime(data["created_at"], utc=True, format="ISO8601").dt.tz_convert(TIMEZONE)
    names = stores.rename(columns={"store_name": "store_name"})[["store_id", "store_name"]] if not stores.empty \
        else pd.DataFrame(columns=["store_id", "store_name"])
    data = data.merge(names, on="store_id", how="left")
    data["store_name"] = data["store_name"].fillna("Unknown store (" + data["store_id"].astype(str) + ")")
    for column in columns:
        if column not in data:
            data[column] = None
    return data[columns].sort_values("when", ascending=False).reset_index(drop=True)


def add_bucket(data: pd.DataFrame, period: str) -> pd.DataFrame:
    result = data.copy()
    result["bucket"] = result["when"].dt.strftime(PERIOD_FORMATS[period])
    return result


def requests_per_period(data: pd.DataFrame, period: str) -> pd.DataFrame:
    """One row per day / month / year: total, success, errors."""
    if data.empty:
        return pd.DataFrame(columns=["Period", "Total", "Success", "Errors"])
    bucketed = add_bucket(data, period)
    grouped = bucketed.groupby("bucket").agg(
        Total=("status", "size"),
        Success=("status", lambda s: int((s == "success").sum())),
        Errors=("status", lambda s: int((s != "success").sum())),
    ).reset_index().rename(columns={"bucket": "Period"})
    return grouped.sort_values("Period").reset_index(drop=True)


def requests_per_store(data: pd.DataFrame) -> pd.DataFrame:
    """One row per medical store, busiest first."""
    if data.empty:
        return pd.DataFrame(columns=["Store", "Total", "Success", "Errors", "Last request"])
    grouped = data.groupby(["store_id", "store_name"]).agg(
        Total=("status", "size"),
        Success=("status", lambda s: int((s == "success").sum())),
        Errors=("status", lambda s: int((s != "success").sum())),
        last=("when", "max"),
    ).reset_index()
    grouped["Last request"] = grouped["last"].dt.strftime("%d %b %Y, %I:%M %p")
    grouped = grouped.rename(columns={"store_name": "Store"})
    return grouped.sort_values("Total", ascending=False)[["Store", "Total", "Success", "Errors", "Last request"]].reset_index(drop=True)


def store_by_period(data: pd.DataFrame, period: str) -> pd.DataFrame:
    """Rows = stores, columns = days / months / years, cells = request count."""
    if data.empty:
        return pd.DataFrame()
    bucketed = add_bucket(data, period)
    table = bucketed.pivot_table(index="store_name", columns="bucket", values="status",
                                 aggfunc="size", fill_value=0)
    table.index.name = "Store"
    return table[sorted(table.columns)]
