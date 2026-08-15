import base64, hashlib, hmac, os, secrets
from datetime import datetime, timedelta, timezone
import jwt
from fastapi import HTTPException, Header

APP_SECRET = os.getenv("APP_SECRET", "dev-secret-change-me")
SUPER_ADMIN_EMAIL = os.getenv("SUPER_ADMIN_EMAIL", "owner@example.com").lower()
SUPER_ADMIN_PASSWORD = os.getenv("SUPER_ADMIN_PASSWORD", "ChangeMe123!")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return base64.b64encode(salt).decode() + "." + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        salt_b64, digest_b64 = stored.split(".", 1)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def issue_token(role: str, **claims) -> str:
    now = datetime.now(timezone.utc)
    payload = {"role": role, "iat": now, "exp": now + timedelta(hours=24), **claims}
    return jwt.encode(payload, APP_SECRET, algorithm="HS256")


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, APP_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def bearer_payload(authorization: str | None = Header(None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Login required")
    return decode_token(authorization.split(" ", 1)[1])


def require_super(payload: dict) -> dict:
    if payload.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super Admin required")
    return payload


def require_shop(payload: dict) -> int:
    if payload.get("role") != "shop_admin" or not payload.get("shop_id"):
        raise HTTPException(status_code=403, detail="Shop Admin required")
    return int(payload["shop_id"])


def require_kitchen(payload: dict) -> int:
    if payload.get("role") != "kitchen" or not payload.get("shop_id"):
        raise HTTPException(status_code=403, detail="Kitchen login required")
    return int(payload["shop_id"])


def require_rider(payload: dict) -> int:
    if payload.get("role") != "rider" or not payload.get("rider_id"):
        raise HTTPException(status_code=403, detail="Rider login required")
    return int(payload["rider_id"])


def require_customer(payload: dict) -> int:
    if payload.get("role") != "customer" or not payload.get("customer_id"):
        raise HTTPException(status_code=403, detail="Customer login required")
    return int(payload["customer_id"])
