"""Medical stores + password reset - no Streamlit here, so it is easy to test.

Supabase never lets anyone READ a password (it is stored only as a hash).
What the admin CAN do is SET a new one for a user: that is all this file does.
It needs the service_role key client (the same one the dashboard already uses).
"""

# Same rule as the main EasyStock app (utils/validators.validate_password).
PASSWORD_MIN_LENGTH = 6
PASSWORD_MAX_LENGTH = 20


class AdminUserError(Exception):
    """A problem the admin should be told about, in plain words."""


def list_stores(client) -> list:
    """Every medical store, A-Z. Each row has store_id, store_name,
    owner_name and UID (the Supabase Auth user id of the owner)."""
    try:
        rows = client.table("stores").select("*").execute().data or []
    except Exception as error:
        raise AdminUserError(f"Stores list nahi aa saki: {error}")
    return sorted(rows, key=lambda row: str(row.get("store_name") or "").lower())


def get_email(client, uid: str) -> str:
    """Login email of the store owner, read from Supabase Auth."""
    if not uid:
        raise AdminUserError("Is store ke saath koi login (UID) jura nahi hai.")
    try:
        response = client.auth.admin.get_user_by_id(uid)
        user = getattr(response, "user", None)
        email = getattr(user, "email", None)
    except Exception as error:
        raise AdminUserError(f"Email nahi mili: {error}")
    if not email:
        raise AdminUserError("Is user ka email Supabase me nahi mila.")
    return email


def validate_new_password(new_password: str, confirm_password: str) -> str:
    """Return the password if it is fine, otherwise raise AdminUserError."""
    if not new_password:
        raise AdminUserError("Naya password likho.")
    if new_password != confirm_password:
        raise AdminUserError("Dono password same nahi hain. Dobara likho.")
    if len(new_password) < PASSWORD_MIN_LENGTH:
        raise AdminUserError(f"Password kam se kam {PASSWORD_MIN_LENGTH} akshar ka hona chahiye.")
    if len(new_password) > PASSWORD_MAX_LENGTH:
        raise AdminUserError(f"Password {PASSWORD_MAX_LENGTH} akshar se zyada nahi ho sakta.")
    return new_password


def set_password(client, uid: str, new_password: str, confirm_password: str) -> None:
    """Validate, then set the new password for this user in Supabase Auth."""
    if not uid:
        raise AdminUserError("Is store ke saath koi login (UID) jura nahi hai.")
    password = validate_new_password(new_password, confirm_password)
    try:
        client.auth.admin.update_user_by_id(uid, {"password": password})
    except Exception as error:
        # The password itself is never put into the message.
        raise AdminUserError(f"Password set nahi ho saka: {str(error).replace(password, '***')}")
