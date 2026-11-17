import ast
import pathlib
import types

import pytest

import admin_users
from admin_users import AdminUserError

APP = pathlib.Path(__file__).resolve().parent.parent / "app.py"


class FakeAdmin:
    def __init__(self, emails=None, fail_update=False):
        self.emails, self.fail_update, self.updated, self.lookups = emails or {}, fail_update, [], []

    def get_user_by_id(self, uid):
        self.lookups.append(uid)
        if uid not in self.emails:
            raise RuntimeError("User not found")
        return types.SimpleNamespace(user=types.SimpleNamespace(email=self.emails[uid]))

    def update_user_by_id(self, uid, attrs):
        if self.fail_update:
            raise RuntimeError("weak password: " + attrs["password"])
        self.updated.append((uid, attrs))


class FakeClient:
    def __init__(self, rows, admin):
        self._rows, self.auth = rows, types.SimpleNamespace(admin=admin)

    def table(self, name):
        assert name == "stores"
        return self

    def select(self, cols):
        return self

    def execute(self):
        return types.SimpleNamespace(data=self._rows)


# ---------------------------------------------------------------- logic
def test_list_sorted_az_and_keeps_uid():
    c = FakeClient([{"store_id": 2, "store_name": "b med", "UID": "u2"},
                    {"store_id": 1, "store_name": "A Med", "UID": "u1"}], FakeAdmin())
    assert [r["store_id"] for r in admin_users.list_stores(c)] == [1, 2]


def test_email_ok_and_errors():
    c = FakeClient([], FakeAdmin({"u1": "a@x.com"}))
    assert admin_users.get_email(c, "u1") == "a@x.com"
    with pytest.raises(AdminUserError):
        admin_users.get_email(c, "missing")
    with pytest.raises(AdminUserError):
        admin_users.get_email(c, None)


@pytest.mark.parametrize("new,conf,msg", [
    ("", "", "likho"), ("abcdef", "abcdeX", "same nahi"),
    ("abc", "abc", "kam se kam"), ("a" * 21, "a" * 21, "zyada nahi"),
])
def test_validation_rejects(new, conf, msg):
    with pytest.raises(AdminUserError, match=msg):
        admin_users.validate_new_password(new, conf)


def test_set_password_calls_supabase_only_when_valid():
    admin = FakeAdmin()
    c = FakeClient([], admin)
    admin_users.set_password(c, "u1", "secret1", "secret1")
    assert admin.updated == [("u1", {"password": "secret1"})]
    with pytest.raises(AdminUserError):
        admin_users.set_password(c, "u1", "secret1", "nope")
    assert len(admin.updated) == 1


def test_supabase_error_never_leaks_password():
    c = FakeClient([], FakeAdmin(fail_update=True))
    with pytest.raises(AdminUserError) as e:
        admin_users.set_password(c, "u1", "secret1", "secret1")
    assert "secret1" not in str(e.value)


# ---------------------------------------------------------------- page flow (fake streamlit)
class Rerun(BaseException):
    pass


class FakeSt:
    """Records output; widget results come from `script`."""
    def __init__(self, script):
        self.session_state, self.script, self.out = {}, script, []
        self.sidebar = self

    def __getattr__(self, name):
        def rec(*a, **k):
            self.out.append((name, a, k)); return None
        return rec

    def cache_data(self, *a, **k):
        return (lambda f: f) if not (a and callable(a[0])) else a[0]

    def container(self, **k):
        return types.SimpleNamespace(__enter__=lambda s: None, __exit__=lambda *x: False)

    def button(self, label, key=None, **k):
        self.out.append(("button", (label,), {"key": key}))
        return key in self.script.get("click", set())

    def text_input(self, label, key=None, **k):
        return self.script.get("inputs", {}).get(key, "")

    def form(self, key, **k):
        return types.SimpleNamespace(__enter__=lambda s: None, __exit__=lambda *x: False)

    def form_submit_button(self, label, **k):
        return self.script.get("submit", False)

    def rerun(self):
        raise Rerun()

    def texts(self, kind):
        return [a[0] for n, a, k in self.out if n == kind]


class CM:
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _load_page(st, client):
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    wanted = {"_load_store_list", "_load_email", "_store_details", "_stores_page"}
    funcs = []
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name in wanted:
            n.decorator_list = []          # drop @st.cache_data
            funcs.append(n)
    assert {f.name for f in funcs} == wanted
    st.container = lambda **k: CM()
    st.form = lambda *a, **k: CM()
    ns = {"st": st, "admin_users": admin_users, "_client": lambda: client}
    exec(compile(ast.Module(body=funcs, type_ignores=[]), "app_extract", "exec"), ns)
    return ns


ROWS = [{"store_id": 1, "store_name": "Sharma Medical", "owner_name": "Raj", "UID": "u1"},
        {"store_id": 2, "store_name": "Gupta Medical", "owner_name": "Amit", "UID": "u2"}]


def _run(script, state=None, admin=None):
    admin = admin or FakeAdmin({"u1": "sharma@x.com", "u2": "gupta@x.com"})
    st = FakeSt(script)
    st.session_state.update(state or {})
    ns = _load_page(st, FakeClient(ROWS, admin))
    try:
        ns["_stores_page"]()
    except Rerun:
        pass
    return st, admin


def test_list_shows_all_stores_collapsed_and_no_email_lookup():
    st, admin = _run({})
    labels = [a[0] for n, a, k in st.out if n == "button"]
    assert any("Gupta Medical" in l for l in labels) and any("Sharma Medical" in l for l in labels)
    assert admin.lookups == []                       # nothing opened -> no email fetched
    assert "code" not in [n for n, *_ in st.out]


def test_click_store_opens_it():
    st, _ = _run({"click": {"store_btn_1"}})
    assert st.session_state["open_store"] == 1


def test_open_store_shows_email_and_change_password_button_only_that_one():
    st, admin = _run({}, state={"open_store": 2})
    assert st.texts("code") == ["gupta@x.com"]
    assert admin.lookups == ["u2"]
    assert "pw_btn_2" in [k["key"] for n, a, k in st.out if n == "button"]


def test_change_password_button_opens_form():
    st, _ = _run({"click": {"pw_btn_1"}}, state={"open_store": 1})
    assert st.session_state["pw_open_1"] is True


def test_form_submit_sets_password_and_shows_message():
    st, admin = _run({"submit": True, "inputs": {"pw_new_1": "newpass1", "pw_conf_1": "newpass1"}},
                     state={"open_store": 1, "pw_open_1": True})
    assert admin.updated == [("u1", {"password": "newpass1"})]
    assert st.session_state["pw_open_1"] is False and "Sharma Medical" in st.session_state["pw_done"]


def test_form_mismatch_shows_error_and_does_not_set():
    st, admin = _run({"submit": True, "inputs": {"pw_new_1": "newpass1", "pw_conf_1": "different"}},
                     state={"open_store": 1, "pw_open_1": True})
    assert admin.updated == [] and any("same nahi" in e for e in st.texts("error"))
    assert st.session_state["pw_open_1"] is True


def test_done_message_shown_once():
    st, _ = _run({}, state={"pw_done": "✅ ok"})
    assert st.texts("success") == ["✅ ok"] and "pw_done" not in st.session_state


def test_store_without_uid_shows_error_not_crash():
    rows = [{"store_id": 9, "store_name": "Old Store", "owner_name": "X", "UID": None}]
    st = FakeSt({}); st.session_state["open_store"] = 9
    ns = _load_page(st, FakeClient(rows, FakeAdmin()))
    ns["_stores_page"]()
    assert any("UID" in e for e in st.texts("error"))
