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

import admin_users
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
def _usage_page() -> None:
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


# ---------------------------------------------------------------- medical stores
@st.cache_data(ttl=60, show_spinner="Stores aa rahe hain...")
def _load_store_list() -> list:
    return admin_users.list_stores(_client())


@st.cache_data(ttl=300, show_spinner=False)
def _load_email(uid: str) -> str:
    return admin_users.get_email(_client(), uid)


def _store_details(store: dict) -> None:
    sid = store.get("store_id")
    uid = store.get("UID")
    try:
        email = _load_email(uid)
    except admin_users.AdminUserError as error:
        st.error(str(error))
        return

    st.caption("Email id")
    st.code(email, language=None)
    st.caption(f"Owner: {store.get('owner_name') or '-'}   ·   Store ID: {sid}")

    pw_key = f"pw_open_{sid}"
    if st.button("🔑 Change password", key=f"pw_btn_{sid}"):
        st.session_state[pw_key] = not st.session_state.get(pw_key, False)
        st.rerun()

    if st.session_state.get(pw_key):
        with st.form(f"pw_form_{sid}", clear_on_submit=True):
            new_password = st.text_input("Naya password", type="password", key=f"pw_new_{sid}")
            confirm_password = st.text_input("Password dobara likho (confirm)", type="password", key=f"pw_conf_{sid}")
            st.caption(f"{admin_users.PASSWORD_MIN_LENGTH}-{admin_users.PASSWORD_MAX_LENGTH} akshar. "
                       "Set hote hi purana password login ke liye band ho jayega.")
            submitted = st.form_submit_button("✅ Password set karo", type="primary")
        if submitted:
            try:
                admin_users.set_password(_client(), uid, new_password, confirm_password)
            except admin_users.AdminUserError as error:
                st.error(str(error))
            else:
                st.session_state[pw_key] = False
                st.session_state["pw_done"] = (
                    f"✅ {store.get('store_name')} ka password badal gaya. Ab user ko naya password bata do."
                )
                st.rerun()


def _stores_page() -> None:
    st.title("🏪 Medical stores")
    done = st.session_state.pop("pw_done", None)
    if done:
        st.success(done)
    try:
        stores = _load_store_list()
    except admin_users.AdminUserError as error:
        st.error(str(error))
        return
    if not stores:
        st.info("Abhi koi medical store nahi hai.")
        return

    st.caption(f"Total {len(stores)} medical stores - kisi par click karo.")
    open_id = st.session_state.get("open_store")
    for store in stores:
        sid = store.get("store_id")
        is_open = open_id == sid
        with st.container(border=True):
            arrow = "▾" if is_open else "▸"
            label = f"{arrow}  🏪 {store.get('store_name') or 'Unnamed store'}  ·  {store.get('owner_name') or ''}"
            if st.button(label, key=f"store_btn_{sid}", use_container_width=True):
                st.session_state["open_store"] = None if is_open else sid
                st.rerun()
            if is_open:
                _store_details(store)


# ---------------------------------------------------------------- main
def main() -> None:
    if not _logged_in():
        return
    page = st.radio("Page", ["📊 API usage", "🏪 Medical stores"], horizontal=True,
                    key="admin_page", label_visibility="collapsed")
    if page == "🏪 Medical stores":
        _stores_page()
    else:
        _usage_page()


main()
