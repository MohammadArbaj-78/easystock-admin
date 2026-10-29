"""EasyStock Admin Dashboard - sirf owner ke liye.

Kaun sa medical store kitni API request bhej raha hai - daily, monthly aur
yearly. Data Supabase ki `api_usage_log` table se aata hai (main app likhta
hai, ye app sirf padhta hai).
"""

import hmac
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import stats

st.set_page_config(page_title="EasyStock Admin", page_icon="📊", layout="wide")
IST = ZoneInfo(stats.TIMEZONE)


# ---------------------------------------------------------------- login
def _logged_in() -> bool:
    if st.session_state.get("admin_ok"):
        return True
    st.title("📊 EasyStock Admin")
    password = st.text_input("Admin password", type="password")
    if st.button("Login", type="primary"):
        if hmac.compare_digest(password, str(st.secrets["ADMIN_PASSWORD"])):
            st.session_state["admin_ok"] = True
            st.rerun()
        else:
            st.error("Password galat hai.")
    return False


# ---------------------------------------------------------------- data
@st.cache_resource
def _client():
    from supabase import create_client
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_SERVICE_ROLE_KEY"])


@st.cache_data(ttl=60, show_spinner="Data aa raha hai...")
def _load_logs(start_iso: str, end_iso: str) -> pd.DataFrame:
    rows, offset = [], 0
    while True:                                   # Supabase gives at most 1000 rows per call
        data = (
            _client().table("api_usage_log").select("*")
            .gte("created_at", start_iso).lt("created_at", end_iso)
            .order("created_at").range(offset, offset + 999).execute()
        ).data or []
        rows += data
        if len(data) < 1000:
            break
        offset += 1000
    return pd.DataFrame(rows)


@st.cache_data(ttl=300)
def _load_stores() -> pd.DataFrame:
    data = _client().table("stores").select("store_id, store_name, owner_name").execute().data or []
    return pd.DataFrame(data)


# ---------------------------------------------------------------- page
def main() -> None:
    if not _logged_in():
        return

    st.title("📊 EasyStock Admin - API usage")

    with st.sidebar:
        st.header("Filters")
        period = st.radio("Kaise dekhna hai", ["Daily", "Monthly", "Yearly"])
        today = datetime.now(IST).date()
        default_start = {"Daily": today - timedelta(days=29),
                         "Monthly": today - timedelta(days=364),
                         "Yearly": date(today.year - 2, 1, 1)}[period]
        picked = st.date_input("Date range", value=(default_start, today), max_value=today,
                               key=f"range_{period}")
        if st.button("🔄 Refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        if st.button("Logout", use_container_width=True):
            st.session_state.clear()
            st.rerun()

    if not isinstance(picked, tuple) or len(picked) != 2:
        st.info("Date range ki start aur end dono date chuno.")
        return
    start_date, end_date = picked
    start_iso = datetime.combine(start_date, time.min, tzinfo=IST).isoformat()
    end_iso = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=IST).isoformat()

    try:
        stores = _load_stores()
        data = stats.prepare(_load_logs(start_iso, end_iso), stores)
    except Exception as error:
        st.error(f"Data nahi aa saka. Secrets aur `api_usage_log` table check karo.\n\n{error}")
        return

    with st.sidebar:
        store_choice = st.selectbox("Medical store", ["Sab stores"] + sorted(data["store_name"].unique().tolist()))
        apis = sorted(data["api_name"].dropna().unique().tolist())
        api_choice = st.multiselect("API", apis, default=apis)
    if store_choice != "Sab stores":
        data = data[data["store_name"] == store_choice]
    data = data[data["api_name"].isin(api_choice)] if apis else data

    if data.empty:
        st.info("Is range me koi API request nahi mili.")
        return

    total = len(data)
    errors = int((data["status"] != "success").sum())
    a, b, c, d = st.columns(4)
    a.metric("Total requests", total)
    b.metric("Success", total - errors)
    c.metric("Errors", errors)
    d.metric("Active stores", data["store_id"].nunique())

    per_period = stats.requests_per_period(data, period)
    st.subheader(f"{period} requests")
    st.bar_chart(per_period.set_index("Period")[["Success", "Errors"]])
    st.dataframe(per_period, use_container_width=True, hide_index=True)

    st.subheader("Store-wise")
    st.dataframe(stats.requests_per_store(data), use_container_width=True, hide_index=True)

    st.subheader(f"Store x {period.lower()} (kitni requests)")
    st.dataframe(stats.store_by_period(data, period), use_container_width=True)

    st.subheader("Haal ki requests")
    recent = data.head(50).copy()
    recent["when"] = recent["when"].dt.strftime("%d %b %Y, %I:%M %p")
    st.dataframe(
        recent.rename(columns={"when": "Time", "store_name": "Store", "api_name": "API", "status": "Status",
                               "duration_seconds": "Seconds", "error_message": "Error"})
        [["Time", "Store", "API", "Status", "Seconds", "Error"]],
        use_container_width=True, hide_index=True,
    )

    export = data.copy()
    export["when"] = export["when"].dt.strftime("%Y-%m-%d %H:%M:%S")
    st.download_button("⬇️ CSV download", export.to_csv(index=False).encode("utf-8"),
                       file_name="api_usage.csv", mime="text/csv")


main()
