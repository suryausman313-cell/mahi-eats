import json
import math
import os
import re
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session, selectinload

from .database import Base, engine, get_db
from .models import (
    ActivityLog, Category, CustomerAccount, Deal, Extra, Feedback, Offer, Order,
    OrderDeliveryMeta, OrderItem, Product, Rider, RiderCashSubmission, Shop, ShopAdmin, ShopDeliveryRule, ShopNotification
)
from .schemas import (
    AdminCreate,
    AdminUpdate,
    CustomerLoginIn,
    CustomerRegisterIn,
    DeliveryQuoteIn,
    DeliveryRuleIn,
    DealIn,
    ExtraIn,
    FeedbackIn,
    AssignRiderIn,
    CategoryIn,
    KitchenLoginIn,
    KitchenPinIn,
    LoginIn,
    MerchantRiderIn,
    NotificationIn,
    OfferIn,
    PromoIn,
    OrderCreate,
    OrderStatusIn,
    ProductIn,
    RiderCashIn,
    RiderCashReviewIn,
    RiderCreate,
    RiderLocationIn,
    RiderLoginIn,
    RiderStatusIn,
    RiderUpdate,
    ShopCreate,
    ShopSettingsIn,
    ShopUpdate,
)
from .security import (
    SUPER_ADMIN_EMAIL,
    SUPER_ADMIN_PASSWORD,
    bearer_payload,
    hash_password,
    issue_token,
    require_customer,
    require_kitchen,
    require_rider,
    require_shop,
    require_super,
    verify_password,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create new V6 tables first, then add columns to existing production tables without resetting data.
    Base.metadata.create_all(bind=engine)
    migrations = {
        "shops": {
            "operating_status": "VARCHAR(20) DEFAULT 'open'",
            "service_fee_enabled": "BOOLEAN DEFAULT FALSE",
            "service_fee": "FLOAT DEFAULT 0",
            "service_fee_type": "VARCHAR(20) DEFAULT 'fixed'",
            "service_fee_applies_to": "VARCHAR(20) DEFAULT 'delivery'",
            "small_order_fee_enabled": "BOOLEAN DEFAULT FALSE",
            "small_order_threshold": "FLOAT DEFAULT 20",
            "small_order_fee": "FLOAT DEFAULT 0",
        },
        "shop_admins": {
            "role": "VARCHAR(30) DEFAULT 'admin'",
            "permissions_json": "TEXT",
        },
        "products": {
            "sizes_json": "TEXT",
            "has_extras": "BOOLEAN DEFAULT FALSE",
            "is_popular": "BOOLEAN DEFAULT FALSE",
            "discount_enabled": "BOOLEAN DEFAULT FALSE",
            "discount_type": "VARCHAR(20) DEFAULT 'percentage'",
            "discount_value": "FLOAT DEFAULT 0",
        },
        "orders": {
            "discount_amount": "FLOAT DEFAULT 0",
            "service_fee": "FLOAT DEFAULT 0",
            "small_order_fee": "FLOAT DEFAULT 0",
            "promo_code": "VARCHAR(60)",
        },
        "order_items": {
            "size_name": "VARCHAR(80)",
            "extras_json": "TEXT",
            "item_kind": "VARCHAR(20) DEFAULT 'product'",
            "details_json": "TEXT",
        },
    }
    try:
        inspector = inspect(engine)
        with engine.begin() as conn:
            for table_name, columns in migrations.items():
                existing = {c["name"] for c in inspector.get_columns(table_name)}
                for name, sql_type in columns.items():
                    if name not in existing:
                        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {name} {sql_type}"))
            # Preserve current open/closed state while introducing the three-state switch.
            conn.execute(text("UPDATE shops SET operating_status = CASE WHEN is_open THEN COALESCE(NULLIF(operating_status,''),'open') ELSE 'closed' END WHERE operating_status IS NULL OR operating_status = ''"))
    except Exception as exc:
        print("V6 schema migration warning:", exc)
    yield


app = FastAPI(title="Mahi Eats API", version="9.0.0", lifespan=lifespan)
origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"https://([a-z0-9-]+\.)?mahi-eats\.pages\.dev",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()


def normalize_phone(value: str) -> str:
    raw = re.sub(r"[^0-9+]", "", (value or "").strip())
    if raw.startswith("00"):
        raw = "+" + raw[2:]
    if raw.startswith("971"):
        raw = "+" + raw
    if raw.startswith("05") and len(raw) == 10:
        raw = "+971" + raw[1:]
    return raw


def customer_json(c: CustomerAccount):
    return {"id": c.id, "name": c.name, "phone": c.phone}


def _loads(value, fallback):
    if not value:
        return fallback
    try:
        result = json.loads(value)
        return result if result is not None else fallback
    except (TypeError, ValueError):
        return fallback


def product_json(p: Product):
    sizes = _loads(p.sizes_json, [])
    if not sizes:
        sizes = [{"name": "Regular", "price": float(p.price or 0)}]
    return {
        "id": p.id, "category_id": p.category_id, "name": p.name,
        "description": p.description, "price": float(p.price or 0),
        "image_url": p.image_url, "is_active": bool(p.is_active),
        "sizes": sizes, "has_extras": bool(getattr(p, "has_extras", False)),
        "is_popular": bool(getattr(p, "is_popular", False)),
        "discount_enabled": bool(getattr(p, "discount_enabled", False)),
        "discount_type": getattr(p, "discount_type", "percentage") or "percentage",
        "discount_value": float(getattr(p, "discount_value", 0) or 0),
    }


def extra_json(x: Extra):
    return {"id": x.id, "name": x.name, "price": float(x.price or 0), "is_active": bool(x.is_active)}


def offer_json(x: Offer):
    return {"id": x.id, "title": x.title, "promo_code": x.promo_code, "discount_type": x.discount_type,
            "discount_value": float(x.discount_value or 0), "minimum_order": float(x.minimum_order or 0),
            "maximum_discount": float(x.maximum_discount or 0), "first_order_only": bool(x.first_order_only),
            "usage_limit_per_customer": int(x.usage_limit_per_customer or 0), "is_active": bool(x.is_active)}


def deal_json(x: Deal):
    return {"id": x.id, "title": x.title, "description": x.description, "price": float(x.price or 0),
            "image_url": x.image_url, "rules": _loads(x.rules_json, []), "is_active": bool(x.is_active)}


def admin_permissions(a: ShopAdmin):
    default = {"orders": True, "sales": True, "finance": True, "menu": True, "offers": True, "deals": True,
               "customers": True, "notifications": True, "feedback": True, "logs": True, "accounts": a.role == "owner",
               "settings": True, "kitchen": True}
    saved = _loads(a.permissions_json, {})
    default.update({str(k): bool(v) for k, v in saved.items()})
    return default


def activity(db: Session, shop_id: int, payload, action: str, detail: str = ""):
    aid = int(payload.get("admin_id", 0)) if payload and payload.get("role") == "shop_admin" and payload.get("admin_id") else None
    db.add(ActivityLog(shop_id=shop_id, admin_id=aid, action=action, detail=detail))


def delivery_rule_json(rule: ShopDeliveryRule | None, shop: Shop | None = None):
    if not rule:
        return {
            "area_note": None,
            "base_fee": float(shop.delivery_fee if shop else 0),
            "free_km": 0.0,
            "per_km_fee": 0.0,
            "max_delivery_km": 0.0,
            "max_fee": 0.0,
            "is_enabled": True,
        }
    return {
        "area_note": rule.area_note,
        "base_fee": float(rule.base_fee or 0),
        "free_km": float(rule.free_km or 0),
        "per_km_fee": float(rule.per_km_fee or 0),
        "max_delivery_km": float(rule.max_delivery_km or 0),
        "max_fee": float(rule.max_fee or 0),
        "is_enabled": bool(rule.is_enabled),
    }


def get_delivery_rule(db: Session, shop: Shop) -> ShopDeliveryRule | None:
    return db.scalar(select(ShopDeliveryRule).where(ShopDeliveryRule.shop_id == shop.id))


def compute_road_distance(origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float):
    if GOOGLE_MAPS_API_KEY:
        body = json.dumps({
            "origin": {"location": {"latLng": {"latitude": origin_lat, "longitude": origin_lon}}},
            "destination": {"location": {"latLng": {"latitude": dest_lat, "longitude": dest_lon}}},
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_UNAWARE",
            "computeAlternativeRoutes": False,
            "languageCode": "en-US",
            "units": "METRIC",
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://routes.googleapis.com/directions/v2:computeRoutes",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
                "X-Goog-FieldMask": "routes.distanceMeters,routes.duration",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            route = (payload.get("routes") or [None])[0]
            if route and route.get("distanceMeters") is not None:
                duration_raw = str(route.get("duration") or "0s").rstrip("s")
                try:
                    duration_seconds = int(float(duration_raw))
                except ValueError:
                    duration_seconds = None
                return round(float(route["distanceMeters"]) / 1000.0, 2), duration_seconds, "google_routes"
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, KeyError):
            # Never charge a customer from a straight-line estimate when Google Routes is configured.
            # If road routing fails, checkout should stop instead of calculating the wrong delivery fee.
            return None, None, "google_routes_unavailable"
    # Development-only fallback when no Google Routes key is configured.
    estimate = km_distance(origin_lat, origin_lon, dest_lat, dest_lon)
    return (round(float(estimate), 2) if estimate is not None else None), None, "straight_line_estimate"


def delivery_quote(db: Session, shop: Shop, latitude: float, longitude: float):
    if shop.latitude is None or shop.longitude is None:
        raise HTTPException(409, "Shop delivery location is not configured by Super Admin")
    rule = get_delivery_rule(db, shop)
    rule_data = delivery_rule_json(rule, shop)
    if not bool(rule_data.get("is_enabled", True)):
        raise HTTPException(409, "Delivery is disabled for this shop")
    distance_km, duration_seconds, source = compute_road_distance(shop.latitude, shop.longitude, latitude, longitude)
    if distance_km is None:
        raise HTTPException(503, "Could not calculate delivery distance")
    max_km = float(rule_data["max_delivery_km"] or 0)
    deliverable = not max_km or distance_km <= max_km + 1e-9
    extra_km = max(0.0, distance_km - float(rule_data["free_km"] or 0))
    fee = float(rule_data["base_fee"] or 0) + extra_km * float(rule_data["per_km_fee"] or 0)
    max_fee = float(rule_data["max_fee"] or 0)
    if max_fee > 0:
        fee = min(fee, max_fee)
    fee = round(fee + 1e-9, 2)
    return {
        "shop_id": shop.id,
        "distance_km": distance_km,
        "duration_seconds": duration_seconds,
        "distance_source": source,
        "is_road_distance": source == "google_routes",
        "deliverable": deliverable,
        "delivery_fee": fee,
        "max_delivery_km": max_km,
        "area_note": rule_data["area_note"],
        "base_fee": float(rule_data["base_fee"] or 0),
        "free_km": float(rule_data["free_km"] or 0),
        "per_km_fee": float(rule_data["per_km_fee"] or 0),
    }


def service_fee_for(shop: Shop, subtotal: float, order_type: str = "delivery") -> float:
    if not bool(getattr(shop, "service_fee_enabled", False)):
        return 0.0
    applies = str(getattr(shop, "service_fee_applies_to", "delivery") or "delivery").lower()
    if applies not in {"both", order_type}:
        return 0.0
    amount = max(float(getattr(shop, "service_fee", 0) or 0), 0.0)
    fee_type = str(getattr(shop, "service_fee_type", "fixed") or "fixed").lower()
    if fee_type == "percentage":
        return round(max(float(subtotal or 0), 0.0) * amount / 100.0, 2)
    return round(amount, 2)


def _product_size_price(product: Product, size_name: str | None):
    sizes = _loads(product.sizes_json, [])
    if not sizes:
        base = float(product.price or 0)
        selected = None
    else:
        selected = None
        if size_name:
            for size in sizes:
                if str(size.get("name", "")).strip().lower() == str(size_name).strip().lower():
                    selected = size
                    break
        if selected is None:
            selected = sizes[0]
        base = float(selected.get("price", product.price) or product.price or 0)
    final = base
    if product.discount_enabled and float(product.discount_value or 0) > 0:
        if (product.discount_type or "percentage") == "fixed":
            final = max(0, base - float(product.discount_value or 0))
        else:
            final = max(0, base * (1 - float(product.discount_value or 0) / 100.0))
    return round(final, 2), (str(selected.get("name")) if selected else (size_name or None)), round(base, 2)


def _promo_discount(db: Session, shop: Shop, customer_phone: str, subtotal: float, promo_code: str | None):
    if not promo_code:
        return 0.0, None
    code = promo_code.strip().upper()
    offer = db.scalar(select(Offer).where(Offer.shop_id == shop.id, func.upper(Offer.promo_code) == code, Offer.is_active == True))
    if not offer:
        raise HTTPException(400, "Invalid or inactive promo code")
    if subtotal < float(offer.minimum_order or 0):
        raise HTTPException(400, f"Promo minimum order is AED {float(offer.minimum_order or 0):.2f}")
    previous = int(db.scalar(select(func.count()).select_from(Order).where(
        Order.shop_id == shop.id, Order.customer_phone == customer_phone, Order.status != "cancelled"
    )) or 0)
    if offer.first_order_only and previous > 0:
        raise HTTPException(400, "This promo is for the first order only")
    if int(offer.usage_limit_per_customer or 0) > 0:
        used = int(db.scalar(select(func.count()).select_from(Order).where(
            Order.shop_id == shop.id, Order.customer_phone == customer_phone, func.upper(Order.promo_code) == code, Order.status != "cancelled"
        )) or 0)
        if used >= int(offer.usage_limit_per_customer):
            raise HTTPException(400, "Promo usage limit reached")
    if offer.discount_type == "fixed":
        amount = float(offer.discount_value or 0)
    else:
        amount = subtotal * float(offer.discount_value or 0) / 100.0
    if float(offer.maximum_discount or 0) > 0:
        amount = min(amount, float(offer.maximum_discount))
    return round(min(subtotal, max(0, amount)), 2), offer


def shop_json(s: Shop):
    return {
        "id": s.id,
        "name": s.name,
        "slug": s.slug,
        "category": s.category,
        "description": s.description,
        "logo_url": s.logo_url,
        "banner_url": s.banner_url,
        "phone": s.phone,
        "address": s.address,
        "city": s.city,
        "latitude": s.latitude,
        "longitude": s.longitude,
        "delivery_fee": s.delivery_fee,
        "delivery_pricing": delivery_rule_json(getattr(s, "delivery_rule", None), s),
        "min_order": s.min_order,
        "estimated_minutes": s.estimated_minutes,
        "delivery_mode": s.delivery_mode,
        "commission_percent": s.commission_percent,
        "is_active": s.is_active,
        "is_open": s.is_open,
        "operating_status": getattr(s, "operating_status", None) or ("open" if s.is_open else "closed"),
        "kitchen_ready": bool(s.kitchen_pin_hash),
        "service_fee_enabled": bool(getattr(s, "service_fee_enabled", False)),
        "service_fee": float(getattr(s, "service_fee", 0) or 0),
        "service_fee_type": str(getattr(s, "service_fee_type", "fixed") or "fixed"),
        "service_fee_applies_to": str(getattr(s, "service_fee_applies_to", "delivery") or "delivery"),
        "small_order_fee_enabled": bool(getattr(s, "small_order_fee_enabled", False)),
        "small_order_threshold": float(getattr(s, "small_order_threshold", 20) or 20),
        "small_order_fee": float(getattr(s, "small_order_fee", 0) or 0),
    }


def shop_rating_summary(db: Session, shop_id: int):
    row = db.execute(
        select(func.avg(Feedback.rating), func.count(Feedback.id))
        .where(Feedback.shop_id == shop_id)
    ).one()
    average = round(float(row[0] or 0), 1)
    count = int(row[1] or 0)
    return {"rating_average": average, "rating_count": count}


def rider_json(r: Rider, private: bool = False):
    data = {
        "id": r.id,
        "name": r.name,
        "phone": r.phone,
        "photo_url": r.photo_url,
        "is_online": r.is_online,
        "is_available": r.is_available,
        "latitude": r.latitude,
        "longitude": r.longitude,
        "location_updated_at": r.location_updated_at.isoformat() if r.location_updated_at else None,
    }
    if private:
        data.update({"email": r.email, "is_active": r.is_active})
    return data


def order_json(o: Order, include_items: bool = True, public: bool = False):
    data = {
        "id": o.id,
        "shop_id": o.shop_id,
        "customer_name": o.customer_name,
        "customer_phone": o.customer_phone,
        "delivery_address": o.delivery_address,
        "customer_latitude": o.customer_latitude,
        "customer_longitude": o.customer_longitude,
        "status": o.status,
        "payment_method": o.payment_method,
        "delivery_mode": o.delivery_mode,
        "rider_id": o.rider_id,
        "rider_status": o.rider_status,
        "merchant_rider_name": o.merchant_rider_name,
        "merchant_rider_phone": o.merchant_rider_phone,
        "subtotal": o.subtotal,
        "discount_amount": float(getattr(o, "discount_amount", 0) or 0),
        "service_fee": float(getattr(o, "service_fee", 0) or 0),
        "small_order_fee": float(getattr(o, "small_order_fee", 0) or 0),
        "promo_code": getattr(o, "promo_code", None),
        "delivery_fee": o.delivery_fee,
        "total": o.total,
        "delivery_distance_km": o.delivery_meta.distance_km if getattr(o, "delivery_meta", None) else None,
        "delivery_distance_source": o.delivery_meta.distance_source if getattr(o, "delivery_meta", None) else None,
        "created_at": o.created_at.isoformat(),
        "assigned_at": o.assigned_at.isoformat() if o.assigned_at else None,
        "picked_up_at": o.picked_up_at.isoformat() if o.picked_up_at else None,
        "delivered_at": o.delivered_at.isoformat() if o.delivered_at else None,
    }
    if o.shop:
        data["shop"] = {
            "id": o.shop.id,
            "name": o.shop.name,
            "slug": o.shop.slug,
            "phone": o.shop.phone,
            "address": o.shop.address,
            "city": o.shop.city,
            "latitude": o.shop.latitude,
            "longitude": o.shop.longitude,
        }
    if o.rider:
        data["rider"] = rider_json(o.rider)
    if include_items:
        data["items"] = [{
            "name": i.name, "qty": i.qty, "unit_price": i.unit_price, "line_total": i.line_total,
            "size_name": getattr(i, "size_name", None), "extras": _loads(getattr(i, "extras_json", None), []),
            "item_kind": getattr(i, "item_kind", "product") or "product",
            "details": _loads(getattr(i, "details_json", None), {}),
        } for i in o.items]
    if public:
        data.pop("shop_id", None)
    return data


def km_distance(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return None
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def auto_assign_rider(db: Session, order: Order):
    if order.delivery_mode != "mahi_eats" or order.rider_id:
        return None
    shop = db.get(Shop, order.shop_id)
    riders = db.scalars(
        select(Rider).where(Rider.is_active == True, Rider.is_online == True, Rider.is_available == True)
    ).all()
    if not riders:
        return None
    ranked = []
    for r in riders:
        dist = km_distance(shop.latitude if shop else None, shop.longitude if shop else None, r.latitude, r.longitude)
        ranked.append((999999 if dist is None else dist, r.id, r))
    ranked.sort(key=lambda x: (x[0], x[1]))
    rider = ranked[0][2]
    order.rider_id = rider.id
    order.rider_status = "assigned"
    order.assigned_at = datetime.utcnow()
    rider.is_available = False
    db.flush()
    return rider


def release_rider(db: Session, order: Order):
    if order.rider_id:
        rider = db.get(Rider, order.rider_id)
        if rider:
            rider.is_available = True


def _rider_active_deliveries(db: Session, rider_id: int):
    return int(
        db.scalar(
            select(func.count())
            .select_from(Order)
            .where(
                Order.rider_id == rider_id,
                Order.status.not_in(["delivered", "cancelled"]),
                Order.rider_status != "delivered",
            )
        )
        or 0
    )


def _gps_meta(rider: Rider):
    if not rider.location_updated_at:
        return {"gps_fresh": False, "location_age_seconds": None}
    updated = rider.location_updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    age = max(0, int((datetime.now(timezone.utc) - updated).total_seconds()))
    return {"gps_fresh": age <= 180, "location_age_seconds": age}


def _dispatch_rider_json(db: Session, rider: Rider, shop: Shop | None = None):
    data = rider_json(rider, private=True)
    data.update(_gps_meta(rider))
    data["active_deliveries"] = _rider_active_deliveries(db, rider.id)
    data["distance_to_shop_km"] = km_distance(
        shop.latitude if shop else None,
        shop.longitude if shop else None,
        rider.latitude,
        rider.longitude,
    )
    # Manual dispatch is intentionally Super-Admin controlled. Offline/busy riders stay visible
    # but cannot be selected, similar to a central fleet dispatcher view.
    data["eligible_for_assignment"] = bool(rider.is_active and rider.is_online and rider.is_available)
    return data


def _uae_period_bounds():
    now = datetime.now(ZoneInfo("Asia/Dubai"))
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    week = today - timedelta(days=today.weekday())
    month = today.replace(day=1)
    year = today.replace(month=1, day=1)

    def utc_naive(value):
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    return {
        "today": utc_naive(today),
        "yesterday": utc_naive(yesterday),
        "week": utc_naive(week),
        "month": utc_naive(month),
        "year": utc_naive(year),
        "now": utc_naive(now),
    }


def _shop_period_stats(db: Session, shop: Shop, start: datetime | None = None):
    filters = [Order.shop_id == shop.id, Order.status != "cancelled"]
    all_filters = [Order.shop_id == shop.id]
    if start is not None:
        filters.append(Order.created_at >= start)
        all_filters.append(Order.created_at >= start)

    sales = float(db.scalar(select(func.coalesce(func.sum(Order.total), 0)).where(*filters)) or 0)
    food_sales = float(db.scalar(select(func.coalesce(func.sum(Order.subtotal), 0)).where(*filters)) or 0)
    delivery_fees = float(db.scalar(select(func.coalesce(func.sum(Order.delivery_fee), 0)).where(*filters)) or 0)
    discounts = float(db.scalar(select(func.coalesce(func.sum(Order.discount_amount), 0)).where(*filters)) or 0)
    service_fees = float(db.scalar(select(func.coalesce(func.sum(Order.service_fee), 0)).where(*filters)) or 0)
    small_order_fees = float(db.scalar(select(func.coalesce(func.sum(Order.small_order_fee), 0)).where(*filters)) or 0)
    orders = int(db.scalar(select(func.count()).select_from(Order).where(*filters)) or 0)
    cancelled = int(db.scalar(select(func.count()).select_from(Order).where(*all_filters, Order.status == "cancelled")) or 0)
    pending = int(db.scalar(select(func.count()).select_from(Order).where(*all_filters, Order.status.not_in(["delivered", "cancelled"]))) or 0)
    delivered = int(db.scalar(select(func.count()).select_from(Order).where(*all_filters, Order.status == "delivered")) or 0)
    cash_sales = float(db.scalar(select(func.coalesce(func.sum(Order.total), 0)).where(*filters, func.lower(Order.payment_method).like("%cash%"))) or 0)
    cash_orders = int(db.scalar(select(func.count()).select_from(Order).where(*filters, func.lower(Order.payment_method).like("%cash%"))) or 0)
    card_sales = max(sales - cash_sales, 0.0)
    card_orders = max(orders - cash_orders, 0)
    net_food_sales = max(food_sales - discounts, 0.0)
    commission = net_food_sales * float(shop.commission_percent or 0) / 100.0
    platform_fees = commission + service_fees + small_order_fees
    shop_delivery_income = delivery_fees if shop.delivery_mode == "shop" else 0.0
    shop_receivable = max(net_food_sales - commission + shop_delivery_income, 0.0)
    return {
        "orders": orders,
        "pending": pending,
        "delivered": delivered,
        "cancelled": cancelled,
        "customer_sales": sales,
        "food_sales": food_sales,
        "shop_food_sale": net_food_sales,
        "delivery_fees": delivery_fees,
        "discounts": discounts,
        "service_fees": service_fees,
        "small_order_fees": small_order_fees,
        "cash_sales": cash_sales,
        "cash_orders": cash_orders,
        "card_sales": card_sales,
        "card_orders": card_orders,
        "commission": commission,
        "platform_fees": platform_fees,
        "commission_percent": float(shop.commission_percent or 0),
        "shop_receivable": shop_receivable,
    }


def _shop_dashboard(db: Session, shop: Shop):
    bounds = _uae_period_bounds()
    return {
        "shop": shop_json(shop),
        "today": _shop_period_stats(db, shop, bounds["today"]),
        "yesterday": _shop_period_stats(db, shop, bounds["yesterday"]),
        "week": _shop_period_stats(db, shop, bounds["week"]),
        "month": _shop_period_stats(db, shop, bounds["month"]),
        "year": _shop_period_stats(db, shop, bounds["year"]),
        "all": _shop_period_stats(db, shop, None),
    }


@app.get("/api/health")
def health():
    return {"ok": True, "app": "Mahi Eats", "version": "9.0.0", "road_routing_ready": bool(GOOGLE_MAPS_API_KEY)}


# ---------- AUTH ----------
@app.post("/api/super/login")
def super_login(data: LoginIn):
    if data.email.lower() != SUPER_ADMIN_EMAIL or data.password != SUPER_ADMIN_PASSWORD:
        raise HTTPException(401, "Wrong email or password")
    return {"token": issue_token("super_admin")}


@app.post("/api/shop-admin/login")
def shop_login(data: LoginIn, db: Session = Depends(get_db)):
    admin = db.scalar(select(ShopAdmin).where(func.lower(ShopAdmin.email) == data.email.lower(), ShopAdmin.is_active == True))
    if not admin or not verify_password(data.password, admin.password_hash):
        raise HTTPException(401, "Wrong email or password")
    shop = db.get(Shop, admin.shop_id)
    if not shop or not shop.is_active:
        raise HTTPException(403, "Shop is suspended")
    return {"token": issue_token("shop_admin", shop_id=shop.id, admin_id=admin.id), "shop": shop_json(shop), "admin": {"id": admin.id, "name": admin.name, "email": admin.email, "role": admin.role, "permissions": admin_permissions(admin)}}


@app.post("/api/kitchen/login")
def kitchen_login(data: KitchenLoginIn, db: Session = Depends(get_db)):
    shop = db.scalar(select(Shop).where(Shop.slug == data.shop_slug.lower().strip(), Shop.is_active == True))
    if not shop or not verify_password(data.pin, shop.kitchen_pin_hash):
        raise HTTPException(401, "Wrong shop or kitchen PIN")
    return {"token": issue_token("kitchen", shop_id=shop.id), "shop": shop_json(shop)}


@app.post("/api/rider/login")
def rider_login(data: RiderLoginIn, db: Session = Depends(get_db)):
    rider = None
    secret = None
    if data.phone and (data.pin or data.password):
        phone = normalize_phone(data.phone)
        rider = db.scalar(select(Rider).where(Rider.phone == phone, Rider.is_active == True))
        # Keep old production riders working even if their phone was saved before normalization.
        if not rider:
            rider = db.scalar(select(Rider).where(Rider.phone == data.phone.strip(), Rider.is_active == True))
        secret = data.pin or data.password
    elif data.email and data.password:
        rider = db.scalar(select(Rider).where(func.lower(Rider.email) == data.email.lower(), Rider.is_active == True))
        secret = data.password
    if not rider or not secret or not verify_password(secret, rider.password_hash):
        raise HTTPException(401, "Wrong mobile number or PIN")
    rider.is_online = True
    db.commit()
    db.refresh(rider)
    return {"token": issue_token("rider", rider_id=rider.id), "rider": rider_json(rider, private=True)}


@app.post("/api/customer/register")
def customer_register(data: CustomerRegisterIn, db: Session = Depends(get_db)):
    phone = normalize_phone(data.phone)
    if len(re.sub(r"\D", "", phone)) < 8:
        raise HTTPException(400, "Enter a valid mobile number")
    if db.scalar(select(CustomerAccount).where(CustomerAccount.phone == phone)):
        raise HTTPException(409, "This mobile number already has a Mahi Eats account")
    customer = CustomerAccount(name=data.name.strip(), phone=phone, pin_hash=hash_password(data.pin))
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return {"token": issue_token("customer", customer_id=customer.id, phone=customer.phone), "customer": customer_json(customer)}


@app.post("/api/customer/login")
def customer_login(data: CustomerLoginIn, db: Session = Depends(get_db)):
    phone = normalize_phone(data.phone)
    customer = db.scalar(select(CustomerAccount).where(CustomerAccount.phone == phone, CustomerAccount.is_active == True))
    if not customer:
        raise HTTPException(401, "Wrong mobile number or PIN")
    now = datetime.utcnow()
    if customer.locked_until and customer.locked_until > now:
        minutes = max(1, int((customer.locked_until - now).total_seconds() // 60) + 1)
        raise HTTPException(429, f"Too many wrong PIN attempts. Try again in {minutes} minute(s)")
    if not verify_password(data.pin, customer.pin_hash):
        customer.failed_attempts = int(customer.failed_attempts or 0) + 1
        if customer.failed_attempts >= 5:
            customer.failed_attempts = 0
            customer.locked_until = now + timedelta(minutes=10)
        db.commit()
        raise HTTPException(401, "Wrong mobile number or PIN")
    customer.failed_attempts = 0
    customer.locked_until = None
    customer.last_login_at = now
    db.commit()
    return {"token": issue_token("customer", customer_id=customer.id, phone=customer.phone), "customer": customer_json(customer)}


@app.get("/api/customer/me")
def customer_me(payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    cid = require_customer(payload)
    customer = db.get(CustomerAccount, cid)
    if not customer or not customer.is_active:
        raise HTTPException(401, "Customer account is unavailable")
    return customer_json(customer)


@app.get("/api/customer/orders")
def customer_orders(payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    cid = require_customer(payload)
    customer = db.get(CustomerAccount, cid)
    if not customer:
        raise HTTPException(404, "Customer not found")
    orders = db.scalars(
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.rider), selectinload(Order.shop), selectinload(Order.delivery_meta))
        .where(Order.customer_phone == customer.phone)
        .order_by(Order.id.desc())
        .limit(200)
    ).all()
    order_ids = [o.id for o in orders]
    feedback_by_order = {}
    if order_ids:
        feedback_rows = db.scalars(
            select(Feedback)
            .where(
                Feedback.customer_phone == customer.phone,
                Feedback.order_id.in_(order_ids),
            )
            .order_by(Feedback.id.desc())
        ).all()
        for fb in feedback_rows:
            if fb.order_id not in feedback_by_order:
                feedback_by_order[fb.order_id] = fb
    result = []
    for order in orders:
        row = order_json(order, public=True)
        fb = feedback_by_order.get(order.id)
        row["my_rating"] = fb.rating if fb else None
        row["my_review"] = fb.comment if fb else None
        result.append(row)
    return result


# ---------- CUSTOMER / PUBLIC ----------
@app.get("/api/public/shops")
def public_shops(
    q: str | None = Query(None), city: str | None = Query(None),
    latitude: float | None = Query(None), longitude: float | None = Query(None),
    db: Session = Depends(get_db),
):
    stmt = select(Shop).where(Shop.is_active == True)
    if q:
        term = f"%{q.strip()}%"
        stmt = stmt.where((Shop.name.ilike(term)) | (Shop.category.ilike(term)))
    if city and latitude is None:
        stmt = stmt.where(Shop.city.ilike(f"%{city.strip()}%"))
    shops = db.scalars(stmt.order_by(Shop.is_open.desc(), Shop.name.asc()).limit(300)).all()
    rating_rows = db.execute(
        select(Feedback.shop_id, func.avg(Feedback.rating), func.count(Feedback.id))
        .group_by(Feedback.shop_id)
    ).all()
    ratings = {
        int(shop_id): {
            "rating_average": round(float(avg_rating or 0), 1),
            "rating_count": int(review_count or 0),
        }
        for shop_id, avg_rating, review_count in rating_rows
    }
    rows = []
    for shop in shops:
        row = shop_json(shop)
        row.update(ratings.get(shop.id, {"rating_average": 0.0, "rating_count": 0}))
        if latitude is not None and longitude is not None and shop.latitude is not None and shop.longitude is not None:
            rule = delivery_rule_json(get_delivery_rule(db, shop), shop)
            direct = km_distance(shop.latitude, shop.longitude, latitude, longitude)
            max_km = float(rule.get("max_delivery_km") or 0)
            # Direct-line distance is a cheap safe pre-filter: road distance can only be longer.
            if max_km > 0 and direct is not None and direct > max_km:
                continue
            try:
                quote = delivery_quote(db, shop, latitude, longitude)
                if not quote["deliverable"]:
                    continue
                row["location_quote"] = quote
            except HTTPException:
                # Shops without map coordinates/config remain hidden in location mode.
                continue
        elif latitude is not None and longitude is not None:
            continue
        rows.append(row)
    return rows


@app.get("/api/public/shops/{slug}")
def public_shop(slug: str, db: Session = Depends(get_db)):
    shop = db.scalar(select(Shop).where(Shop.slug == slug, Shop.is_active == True))
    if not shop:
        raise HTTPException(404, "Shop not found")
    categories = db.scalars(select(Category).where(Category.shop_id == shop.id, Category.is_active == True).order_by(Category.sort_order, Category.name)).all()
    products = db.scalars(select(Product).where(Product.shop_id == shop.id, Product.is_active == True).order_by(Product.name)).all()
    extras = db.scalars(select(Extra).where(Extra.shop_id == shop.id, Extra.is_active == True).order_by(Extra.name)).all()
    offers = db.scalars(select(Offer).where(Offer.shop_id == shop.id, Offer.is_active == True).order_by(Offer.id.desc())).all()
    deals = db.scalars(select(Deal).where(Deal.shop_id == shop.id, Deal.is_active == True).order_by(Deal.id.desc())).all()
    notes = db.scalars(select(ShopNotification).where(ShopNotification.shop_id == shop.id, ShopNotification.is_active == True).order_by(ShopNotification.id.desc()).limit(5)).all()
    rating = shop_rating_summary(db, shop.id)
    recent_reviews = db.scalars(
        select(Feedback)
        .where(Feedback.shop_id == shop.id)
        .order_by(Feedback.id.desc())
        .limit(12)
    ).all()
    return {
        "shop": {**shop_json(shop), **rating},
        "categories": [{"id": c.id, "name": c.name, "sort_order": c.sort_order} for c in categories],
        "products": [product_json(p) for p in products],
        "extras": [extra_json(x) for x in extras],
        "offers": [offer_json(x) for x in offers],
        "deals": [deal_json(x) for x in deals],
        "notifications": [{"id": n.id, "title": n.title, "message": n.message} for n in notes],
        "reviews": [{
            "id": x.id,
            "rating": x.rating,
            "comment": x.comment,
            "created_at": x.created_at.isoformat(),
        } for x in recent_reviews],
    }


@app.post("/api/public/shops/{slug}/delivery-quote")
def public_delivery_quote(slug: str, data: DeliveryQuoteIn, db: Session = Depends(get_db)):
    shop = db.scalar(select(Shop).where(Shop.slug == slug, Shop.is_active == True))
    if not shop:
        raise HTTPException(404, "Shop not found")
    quote = delivery_quote(db, shop, data.latitude, data.longitude)
    subtotal = float(data.subtotal or 0)
    service_fee = service_fee_for(shop, subtotal, "delivery")
    small_fee = float(shop.small_order_fee or 0) if shop.small_order_fee_enabled and subtotal > 0 and subtotal < float(shop.small_order_threshold or 0) else 0.0
    quote.update({"service_fee": round(service_fee, 2), "small_order_fee": round(small_fee, 2), "small_order_threshold": float(shop.small_order_threshold or 0)})
    return quote


@app.post("/api/public/shops/{slug}/promo")
def public_promo(slug: str, data: PromoIn, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    cid = require_customer(payload)
    customer = db.get(CustomerAccount, cid)
    shop = db.scalar(select(Shop).where(Shop.slug == slug, Shop.is_active == True))
    if not shop or not customer:
        raise HTTPException(404, "Shop or customer not found")
    discount, offer = _promo_discount(db, shop, customer.phone, float(data.subtotal or 0), data.promo_code)
    return {"discount_amount": discount, "offer": offer_json(offer) if offer else None}


@app.post("/api/public/shops/{slug}/orders")
def create_order(slug: str, data: OrderCreate, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    cid = require_customer(payload)
    customer = db.get(CustomerAccount, cid)
    if not customer or not customer.is_active:
        raise HTTPException(401, "Customer login required")
    shop = db.scalar(select(Shop).where(Shop.slug == slug, Shop.is_active == True))
    if not shop:
        raise HTTPException(404, "Shop not found")
    if not shop.is_open or shop.operating_status == "closed":
        raise HTTPException(409, "Shop is closed")
    if not data.items:
        raise HTTPException(400, "Cart is empty")

    product_ids = [x.product_id for x in data.items if x.product_id]
    deal_ids = [x.deal_id for x in data.items if x.deal_id]
    products = db.scalars(select(Product).where(Product.shop_id == shop.id, Product.id.in_(product_ids), Product.is_active == True)).all() if product_ids else []
    deals = db.scalars(select(Deal).where(Deal.shop_id == shop.id, Deal.id.in_(deal_ids), Deal.is_active == True)).all() if deal_ids else []
    pmap, dmap = {p.id: p for p in products}, {d.id: d for d in deals}
    extras = db.scalars(select(Extra).where(Extra.shop_id == shop.id, Extra.is_active == True)).all()
    xmap = {x.id: x for x in extras}

    priced_lines = []
    subtotal = 0.0
    for line in data.items:
        if line.product_id:
            p = pmap.get(line.product_id)
            if not p:
                raise HTTPException(400, "One or more items are unavailable")
            price, size_name, original_price = _product_size_price(p, line.size_name)
            picked_extras = []
            extras_total = 0.0
            if line.extra_ids and not p.has_extras:
                raise HTTPException(400, f"{p.name} does not allow extras")
            for xid in line.extra_ids:
                x = xmap.get(xid)
                if not x:
                    raise HTTPException(400, "Invalid extra")
                extras_total += float(x.price or 0)
                picked_extras.append({"id": x.id, "name": x.name, "price": float(x.price or 0)})
            unit = round(price + extras_total, 2)
            total = round(unit * line.qty, 2)
            subtotal += total
            priced_lines.append({"kind": "product", "product": p, "name": p.name, "qty": line.qty, "unit": unit, "total": total, "size": size_name, "extras": picked_extras, "details": {"original_price": original_price}})
        elif line.deal_id:
            d = dmap.get(line.deal_id)
            if not d:
                raise HTTPException(400, "Deal is unavailable")
            rules = _loads(d.rules_json, [])
            selections = line.deal_selections or {}
            # Validate that customer selected the configured number of product IDs from each category.
            for rule in rules:
                cat = str(rule.get("category_id"))
                chosen = selections.get(cat, [])
                if not isinstance(chosen, list) or len(chosen) != int(rule.get("quantity", 1)):
                    raise HTTPException(400, f"Complete all selections for {d.title}")
                valid_count = int(db.scalar(select(func.count()).select_from(Product).where(Product.shop_id == shop.id, Product.category_id == int(cat), Product.id.in_(chosen), Product.is_active == True)) or 0)
                if valid_count != len(chosen):
                    raise HTTPException(400, "Invalid deal selection")
            unit = round(float(d.price or 0), 2)
            total = round(unit * line.qty, 2)
            subtotal += total
            priced_lines.append({"kind": "deal", "deal": d, "name": d.title, "qty": line.qty, "unit": unit, "total": total, "size": None, "extras": [], "details": {"selections": selections}})
        else:
            raise HTTPException(400, "Invalid cart line")

    subtotal = round(subtotal, 2)
    if subtotal < float(shop.min_order or 0):
        raise HTTPException(400, f"Minimum order is AED {shop.min_order:.2f}")

    rule = get_delivery_rule(db, shop)
    rule_data = delivery_rule_json(rule, shop)
    if not bool(rule_data.get("is_enabled", True)):
        raise HTTPException(409, "Delivery is disabled for this shop")

    # Every Mahi Eats delivery must have an exact customer pin. This guarantees the rider gets
    # a customer map location and the customer is charged from the actual driving route.
    if data.customer_latitude is None or data.customer_longitude is None:
        raise HTTPException(400, "Select your exact delivery location on the map")

    quote = delivery_quote(db, shop, data.customer_latitude, data.customer_longitude)
    if not quote["deliverable"]:
        raise HTTPException(409, f"This shop delivers up to {quote['max_delivery_km']:.1f} km by road")
    if GOOGLE_MAPS_API_KEY and quote.get("distance_source") != "google_routes":
        raise HTTPException(503, "Road distance is temporarily unavailable. Please try again.")
    delivery_fee = float(quote["delivery_fee"])

    discount_amount, promo = _promo_discount(db, shop, customer.phone, subtotal, data.promo_code)
    service_fee = service_fee_for(shop, subtotal, "delivery")
    small_order_fee = float(shop.small_order_fee or 0) if shop.small_order_fee_enabled and subtotal < float(shop.small_order_threshold or 0) else 0.0
    total = round(max(0, subtotal - discount_amount) + delivery_fee + service_fee + small_order_fee, 2)

    order = Order(
        shop_id=shop.id, customer_name=customer.name, customer_phone=customer.phone,
        delivery_address=data.delivery_address, customer_latitude=data.customer_latitude,
        customer_longitude=data.customer_longitude, payment_method=data.payment_method,
        delivery_mode=shop.delivery_mode, subtotal=subtotal, discount_amount=discount_amount,
        service_fee=service_fee, small_order_fee=small_order_fee,
        promo_code=promo.promo_code if promo else None, delivery_fee=delivery_fee, total=total,
    )
    db.add(order)
    db.flush()
    for line in priced_lines:
        product = line.get("product")
        db.add(OrderItem(
            order_id=order.id, product_id=product.id if product else None, name=line["name"], qty=line["qty"],
            unit_price=line["unit"], line_total=line["total"], size_name=line["size"],
            extras_json=json.dumps(line["extras"]), item_kind=line["kind"], details_json=json.dumps(line["details"]),
        ))
    if quote:
        db.add(OrderDeliveryMeta(order_id=order.id, distance_km=quote["distance_km"], duration_seconds=quote["duration_seconds"], distance_source=quote["distance_source"], base_fee=quote["base_fee"], free_km=quote["free_km"], per_km_fee=quote["per_km_fee"], calculated_fee=delivery_fee))
    db.commit()
    return {"order_id": order.id, "subtotal": subtotal, "discount_amount": discount_amount, "service_fee": service_fee, "small_order_fee": small_order_fee, "delivery_fee": delivery_fee, "total": total, "status": order.status, "tracking_phone": order.customer_phone, "delivery_quote": quote}


@app.get("/api/public/orders/{order_id}")
def public_order_tracking(order_id: int, phone: str = Query(...), db: Session = Depends(get_db)):
    order = db.scalar(
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.rider), selectinload(Order.shop), selectinload(Order.delivery_meta))
        .where(Order.id == order_id, Order.customer_phone == phone.strip())
    )
    if not order:
        raise HTTPException(404, "Order not found")
    data = order_json(order, public=True)
    if order.shop:
        data["estimated_minutes"] = order.shop.estimated_minutes
    return data


# ---------- SUPER ADMIN ----------
@app.get("/api/super/stats")
def super_stats(payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    require_super(payload)
    total_sales = float(db.scalar(select(func.coalesce(func.sum(Order.total), 0)).where(Order.status != "cancelled")) or 0)
    commission = float(
        db.scalar(
            select(
    func.coalesce(
        func.sum((Order.subtotal - Order.discount_amount) * Shop.commission_percent / 100.0),
        0,
    )
).select_from(Order).join(
    Shop, Shop.id == Order.shop_id
).where(Order.status != "cancelled")
        )
        or 0
    )
    service_fees = float(db.scalar(select(func.coalesce(func.sum(Order.service_fee), 0)).where(Order.status != "cancelled")) or 0)
    small_order_fees = float(db.scalar(select(func.coalesce(func.sum(Order.small_order_fee), 0)).where(Order.status != "cancelled")) or 0)
    platform_income = commission + service_fees + small_order_fees
    return {
        "shops": db.scalar(select(func.count()).select_from(Shop)) or 0,
        "active_shops": db.scalar(select(func.count()).select_from(Shop).where(Shop.is_active == True)) or 0,
        "riders": db.scalar(select(func.count()).select_from(Rider).where(Rider.is_active == True)) or 0,
        "online_riders": db.scalar(select(func.count()).select_from(Rider).where(Rider.is_active == True, Rider.is_online == True)) or 0,
        "orders": db.scalar(select(func.count()).select_from(Order)) or 0,
        "waiting_rider": db.scalar(
            select(func.count()).select_from(Order).where(
                Order.delivery_mode == "mahi_eats",
                Order.rider_id.is_(None),
                Order.status.not_in(["delivered", "cancelled"]),
            )
        ) or 0,
        "sales": total_sales,
        "commission": commission,
        "service_fees": service_fees,
        "small_order_fees": small_order_fees,
        "platform_income": platform_income,
        "road_routing_ready": bool(GOOGLE_MAPS_API_KEY),
    }


@app.get("/api/super/shops")
def super_shops(payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    require_super(payload)
    return [shop_json(s) for s in db.scalars(select(Shop).order_by(Shop.id.desc())).all()]


@app.post("/api/super/shops")
def add_shop(data: ShopCreate, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    require_super(payload)
    if data.delivery_mode not in {"mahi_eats", "shop"}:
        raise HTTPException(400, "delivery_mode must be mahi_eats or shop")
    if db.scalar(select(Shop).where(Shop.slug == data.slug)):
        raise HTTPException(409, "Slug already exists")
    shop = Shop(**data.model_dump())
    db.add(shop)
    db.commit()
    db.refresh(shop)
    return shop_json(shop)


@app.patch("/api/super/shops/{shop_id}")
def edit_shop(shop_id: int, data: ShopUpdate, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    require_super(payload)
    shop = db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(404, "Shop not found")
    updates = data.model_dump(exclude_unset=True)
    if "delivery_mode" in updates and updates["delivery_mode"] not in {"mahi_eats", "shop"}:
        raise HTTPException(400, "Invalid delivery mode")
    if "service_fee_type" in updates and updates["service_fee_type"] not in {"fixed", "percentage"}:
        raise HTTPException(400, "service_fee_type must be fixed or percentage")
    if "service_fee_applies_to" in updates and updates["service_fee_applies_to"] not in {"pickup", "delivery", "both"}:
        raise HTTPException(400, "Invalid service fee scope")
    for k, v in updates.items():
        setattr(shop, k, v)
    if "operating_status" in updates:
        status = str(updates["operating_status"] or "open").lower()
        if status not in {"open", "busy", "closed"}:
            raise HTTPException(400, "Invalid shop status")
        shop.operating_status = status
        shop.is_open = status != "closed"
    elif "is_open" in updates:
        shop.operating_status = "open" if shop.is_open else "closed"
    db.commit()
    db.refresh(shop)
    return shop_json(shop)


@app.get("/api/super/shops/{shop_id}/delivery-rule")
def get_super_delivery_rule(shop_id: int, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    require_super(payload)
    shop = db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(404, "Shop not found")
    return {**delivery_rule_json(get_delivery_rule(db, shop), shop), "shop_id": shop.id, "shop_latitude": shop.latitude, "shop_longitude": shop.longitude, "road_routing_ready": bool(GOOGLE_MAPS_API_KEY)}


@app.put("/api/super/shops/{shop_id}/delivery-rule")
def set_super_delivery_rule(shop_id: int, data: DeliveryRuleIn, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    require_super(payload)
    shop = db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(404, "Shop not found")
    rule = get_delivery_rule(db, shop)
    if not rule:
        rule = ShopDeliveryRule(shop_id=shop.id)
        db.add(rule)
    for key, value in data.model_dump().items():
        setattr(rule, key, value)
    # Keep the legacy flat fee field aligned with the base fee for older clients/cards.
    shop.delivery_fee = float(data.base_fee or 0)
    db.commit()
    db.refresh(rule)
    return {**delivery_rule_json(rule, shop), "shop_id": shop.id, "road_routing_ready": bool(GOOGLE_MAPS_API_KEY)}


@app.post("/api/super/shops/{shop_id}/admins")
def add_admin(shop_id: int, data: AdminCreate, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    require_super(payload)
    if not db.get(Shop, shop_id):
        raise HTTPException(404, "Shop not found")
    if db.scalar(select(ShopAdmin).where(func.lower(ShopAdmin.email) == data.email.lower())):
        raise HTTPException(409, "This admin email is already used")
    admin = ShopAdmin(shop_id=shop_id, name=data.name, email=data.email.lower(), password_hash=hash_password(data.password), role="owner", permissions_json=json.dumps(data.permissions or {}))
    db.add(admin)
    db.commit()
    return {"id": admin.id, "shop_id": shop_id, "name": admin.name, "email": admin.email}


@app.get("/api/super/shops/{shop_id}/dashboard")
def super_shop_dashboard(shop_id: int, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    require_super(payload)
    shop = db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(404, "Shop not found")
    data = _shop_dashboard(db, shop)
    recent = db.scalars(
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.rider), selectinload(Order.shop))
        .where(Order.shop_id == shop_id)
        .order_by(Order.id.desc())
        .limit(20)
    ).all()
    data["recent_orders"] = [order_json(o) for o in recent]
    return data


@app.get("/api/super/dispatch")
def super_dispatch(payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    require_super(payload)
    waiting = db.scalars(
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.rider), selectinload(Order.shop))
        .where(
            Order.delivery_mode == "mahi_eats",
            Order.rider_id.is_(None),
            Order.status.not_in(["delivered", "cancelled"]),
        )
        .order_by(Order.created_at.asc())
        .limit(200)
    ).all()
    assigned = db.scalars(
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.rider), selectinload(Order.shop))
        .where(
            Order.delivery_mode == "mahi_eats",
            Order.rider_id.is_not(None),
            Order.status.not_in(["delivered", "cancelled"]),
            Order.rider_status != "delivered",
        )
        .order_by(Order.assigned_at.desc(), Order.id.desc())
        .limit(100)
    ).all()
    now = datetime.utcnow()
    def row(order: Order):
        item = order_json(order)
        item["waiting_minutes"] = max(0, int((now - order.created_at).total_seconds() // 60))
        item["dispatch_priority"] = 0 if order.status == "ready" else 1 if order.status == "preparing" else 2
        return item
    return {
        "waiting": sorted([row(o) for o in waiting], key=lambda x: (x["dispatch_priority"], -x["waiting_minutes"], x["id"])),
        "assigned": [row(o) for o in assigned],
    }


@app.get("/api/super/orders/{order_id}/rider-candidates")
def super_rider_candidates(order_id: int, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    require_super(payload)
    order = db.scalar(select(Order).options(selectinload(Order.shop)).where(Order.id == order_id))
    if not order:
        raise HTTPException(404, "Order not found")
    if order.delivery_mode != "mahi_eats":
        raise HTTPException(409, "This shop uses its own delivery")
    riders = db.scalars(select(Rider).where(Rider.is_active == True).order_by(Rider.name.asc())).all()
    result = [_dispatch_rider_json(db, r, order.shop) for r in riders]
    result.sort(
        key=lambda r: (
            0 if r["eligible_for_assignment"] else 1,
            0 if r["gps_fresh"] else 1,
            999999 if r["distance_to_shop_km"] is None else r["distance_to_shop_km"],
            r["active_deliveries"],
            r["name"].lower(),
        )
    )
    return result


@app.get("/api/super/riders")
def super_riders(payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    require_super(payload)
    return [_dispatch_rider_json(db, r) for r in db.scalars(select(Rider).order_by(Rider.id.desc())).all()]


@app.post("/api/super/riders")
def super_add_rider(data: RiderCreate, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    require_super(payload)
    phone = normalize_phone(data.phone)
    if db.scalar(select(Rider).where(Rider.phone == phone)):
        raise HTTPException(409, "Rider mobile number already exists")
    secret = data.pin or data.password
    if not secret or len(secret) < 4:
        raise HTTPException(400, "Set a rider PIN of at least 4 digits")
    digits = re.sub(r"\D", "", phone) or str(int(datetime.utcnow().timestamp()))
    email = (data.email or f"rider-{digits}@mahi.local").lower()
    if db.scalar(select(Rider).where(func.lower(Rider.email) == email)):
        raise HTTPException(409, "Rider account already exists")
    rider = Rider(name=data.name, email=email, phone=phone, photo_url=data.photo_url, password_hash=hash_password(secret))
    db.add(rider)
    db.commit()
    db.refresh(rider)
    return rider_json(rider, private=True)


@app.patch("/api/super/riders/{rider_id}")
def super_edit_rider(rider_id: int, data: RiderUpdate, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    require_super(payload)
    rider = db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(404, "Rider not found")
    updates = data.model_dump(exclude_unset=True)
    pin = updates.pop("pin", None)
    if pin:
        rider.password_hash = hash_password(pin)
    if "phone" in updates and updates["phone"]:
        updates["phone"] = normalize_phone(updates["phone"])
    for k, v in updates.items():
        setattr(rider, k, v)
    db.commit()
    db.refresh(rider)
    return rider_json(rider, private=True)


@app.get("/api/super/orders")
def super_orders(payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    require_super(payload)
    orders = db.scalars(
        select(Order).options(selectinload(Order.items), selectinload(Order.rider), selectinload(Order.shop)).order_by(Order.id.desc()).limit(300)
    ).all()
    return [order_json(o) for o in orders]


@app.post("/api/super/orders/{order_id}/assign")
def super_assign_rider(order_id: int, data: AssignRiderIn, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    require_super(payload)
    order = db.get(Order, order_id)
    rider = db.get(Rider, data.rider_id)
    if not order:
        raise HTTPException(404, "Order not found")
    if not rider or not rider.is_active:
        raise HTTPException(404, "Rider not found")
    if order.delivery_mode != "mahi_eats":
        raise HTTPException(409, "This shop uses its own delivery")
    if order.status in {"delivered", "cancelled"}:
        raise HTTPException(409, "This order is already closed")
    if order.rider_id != rider.id and (not rider.is_online or not rider.is_available):
        raise HTTPException(409, "Select an online and available rider")
    if order.rider_id and order.rider_id != rider.id:
        old = db.get(Rider, order.rider_id)
        if old:
            old.is_available = True
    order.rider_id = rider.id
    order.rider_status = "assigned"
    order.assigned_at = datetime.utcnow()
    rider.is_available = False
    db.commit()
    return {"ok": True, "order_id": order.id, "rider": rider_json(rider)}


# ---------- SHOP ADMIN ----------
@app.get("/api/shop-admin/me")
def shop_me(payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_shop(payload)
    shop = db.get(Shop, sid)
    if not shop:
        raise HTTPException(404, "Shop not found")
    data = shop_json(shop)
    aid = payload.get("admin_id")
    admin = db.get(ShopAdmin, int(aid)) if aid else None
    data["admin"] = {"id": admin.id, "name": admin.name, "email": admin.email, "role": admin.role, "permissions": admin_permissions(admin)} if admin else None
    return data


@app.patch("/api/shop-admin/settings")
def shop_settings(data: ShopSettingsIn, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_shop(payload)
    shop = db.get(Shop, sid)
    updates = data.model_dump(exclude_unset=True)
    protected = {"delivery_mode", "delivery_fee", "latitude", "longitude"}
    if protected.intersection(updates):
        raise HTTPException(403, "Delivery mode, shop map location and delivery pricing are controlled by Mahi Eats Super Admin")
    status = updates.pop("operating_status", None)
    if status is not None:
        status = str(status).lower()
        if status not in {"open", "busy", "closed"}:
            raise HTTPException(400, "Invalid shop status")
        shop.operating_status = status
        shop.is_open = status != "closed"
        updates.pop("is_open", None)
    elif "is_open" in updates:
        shop.operating_status = "open" if updates["is_open"] else "closed"
    for k, v in updates.items():
        setattr(shop, k, v)
    db.commit()
    db.refresh(shop)
    return shop_json(shop)


@app.post("/api/shop-admin/kitchen-pin")
def set_kitchen_pin(data: KitchenPinIn, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_shop(payload)
    shop = db.get(Shop, sid)
    shop.kitchen_pin_hash = hash_password(data.pin)
    db.commit()
    return {"ok": True, "shop_slug": shop.slug}


@app.get("/api/shop-admin/dashboard")
def shop_dashboard(payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_shop(payload)
    shop = db.get(Shop, sid)
    if not shop:
        raise HTTPException(404, "Shop not found")
    data = _shop_dashboard(db, shop)
    recent = db.scalars(
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.rider), selectinload(Order.shop))
        .where(Order.shop_id == sid)
        .order_by(Order.id.desc())
        .limit(12)
    ).all()
    data["recent_orders"] = [order_json(o) for o in recent]
    return data


@app.get("/api/shop-admin/reports")
def shop_reports(period: str = Query("today"), payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_shop(payload)
    shop = db.get(Shop, sid)
    if not shop:
        raise HTTPException(404, "Shop not found")
    bounds = _uae_period_bounds()
    if period not in {"today", "yesterday", "week", "month", "year", "all"}:
        raise HTTPException(400, "period must be today, yesterday, week, month, year or all")
    start = None if period == "all" else bounds[period]
    end = bounds["today"] if period == "yesterday" else None
    stats = _shop_period_stats(db, shop, start)
    if end is not None:
        # Recalculate the one-day window precisely.
        qstats = select(Order).where(Order.shop_id == sid, Order.created_at >= start, Order.created_at < end, Order.status != "cancelled")
        day_orders = db.scalars(qstats).all()
        food_sales = sum(float(o.subtotal or 0) for o in day_orders); customer_sales = sum(float(o.total or 0) for o in day_orders)
        cash_orders = [o for o in day_orders if "cash" in (o.payment_method or "").lower()]
        stats.update({"orders": len(day_orders), "customer_sales": customer_sales, "food_sales": food_sales, "cash_sales": sum(float(o.total or 0) for o in cash_orders), "cash_orders": len(cash_orders), "card_sales": customer_sales-sum(float(o.total or 0) for o in cash_orders), "card_orders": len(day_orders)-len(cash_orders), "commission": food_sales*float(shop.commission_percent or 0)/100.0})
    q = select(Order).options(selectinload(Order.items), selectinload(Order.rider), selectinload(Order.shop)).where(Order.shop_id == sid)
    if start is not None:
        q = q.where(Order.created_at >= start)
    if end is not None:
        q = q.where(Order.created_at < end)
    orders = db.scalars(q.order_by(Order.id.desc()).limit(500)).all()
    return {"period": period, "stats": stats, "orders": [order_json(o) for o in orders]}


@app.get("/api/shop-admin/categories")
def admin_categories(payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_shop(payload)
    return [{"id": c.id, "name": c.name, "sort_order": c.sort_order, "is_active": c.is_active} for c in db.scalars(select(Category).where(Category.shop_id == sid).order_by(Category.sort_order, Category.name)).all()]


@app.post("/api/shop-admin/categories")
def admin_add_category(data: CategoryIn, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_shop(payload)
    c = Category(shop_id=sid, **data.model_dump())
    db.add(c); activity(db, sid, payload, "Category created", data.name)
    db.commit(); db.refresh(c)
    return {"id": c.id, "name": c.name, "sort_order": c.sort_order, "is_active": c.is_active}


@app.patch("/api/shop-admin/categories/{category_id}")
def admin_edit_category(category_id: int, data: CategoryIn, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_shop(payload)
    c = db.scalar(select(Category).where(Category.id == category_id, Category.shop_id == sid))
    if not c: raise HTTPException(404, "Category not found")
    for k, v in data.model_dump().items(): setattr(c, k, v)
    activity(db, sid, payload, "Category updated", c.name); db.commit()
    return {"id": c.id, "name": c.name, "sort_order": c.sort_order, "is_active": c.is_active}


@app.delete("/api/shop-admin/categories/{category_id}")
def admin_delete_category(category_id: int, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_shop(payload)
    c = db.scalar(select(Category).where(Category.id == category_id, Category.shop_id == sid))
    if not c: raise HTTPException(404, "Category not found")
    db.execute(text("UPDATE products SET category_id=NULL WHERE shop_id=:sid AND category_id=:cid"), {"sid": sid, "cid": category_id})
    activity(db, sid, payload, "Category deleted", c.name); db.delete(c); db.commit()
    return {"ok": True}


@app.get("/api/shop-admin/products")
def admin_products(payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_shop(payload)
    return [product_json(p) for p in db.scalars(select(Product).where(Product.shop_id == sid).order_by(Product.id.desc())).all()]


@app.post("/api/shop-admin/products")
def admin_add_product(data: ProductIn, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_shop(payload)
    if data.category_id and not db.scalar(select(Category).where(Category.id == data.category_id, Category.shop_id == sid)):
        raise HTTPException(400, "Invalid category")
    raw = data.model_dump(); sizes = raw.pop("sizes", [])
    if sizes: raw["price"] = min(float(x["price"] if isinstance(x, dict) else x.price) for x in sizes)
    p = Product(shop_id=sid, sizes_json=json.dumps([x if isinstance(x, dict) else x.model_dump() for x in sizes]), **raw)
    db.add(p); activity(db, sid, payload, "Product created", p.name); db.commit(); db.refresh(p)
    return product_json(p)


@app.patch("/api/shop-admin/products/{product_id}")
def admin_edit_product(product_id: int, data: ProductIn, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_shop(payload)
    p = db.scalar(select(Product).where(Product.id == product_id, Product.shop_id == sid))
    if not p: raise HTTPException(404, "Product not found")
    if data.category_id and not db.scalar(select(Category).where(Category.id == data.category_id, Category.shop_id == sid)):
        raise HTTPException(400, "Invalid category")
    raw = data.model_dump(); sizes = raw.pop("sizes", [])
    if sizes: raw["price"] = min(float(x["price"] if isinstance(x, dict) else x.price) for x in sizes)
    raw["sizes_json"] = json.dumps([x if isinstance(x, dict) else x.model_dump() for x in sizes])
    for k, v in raw.items(): setattr(p, k, v)
    activity(db, sid, payload, "Product updated", p.name); db.commit()
    return product_json(p)


@app.delete("/api/shop-admin/products/{product_id}")
def admin_delete_product(product_id: int, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_shop(payload)
    p = db.scalar(select(Product).where(Product.id == product_id, Product.shop_id == sid))
    if not p: raise HTTPException(404, "Product not found")
    activity(db, sid, payload, "Product deleted", p.name); db.delete(p); db.commit(); return {"ok": True}


@app.get("/api/shop-admin/extras")
def admin_extras(payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_shop(payload); return [extra_json(x) for x in db.scalars(select(Extra).where(Extra.shop_id == sid).order_by(Extra.id.desc())).all()]


@app.post("/api/shop-admin/extras")
def admin_add_extra(data: ExtraIn, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_shop(payload); x=Extra(shop_id=sid, **data.model_dump()); db.add(x); activity(db,sid,payload,"Extra created",x.name); db.commit(); db.refresh(x); return extra_json(x)


@app.patch("/api/shop-admin/extras/{extra_id}")
def admin_edit_extra(extra_id:int,data:ExtraIn,payload=Depends(bearer_payload),db:Session=Depends(get_db)):
    sid=require_shop(payload); x=db.scalar(select(Extra).where(Extra.id==extra_id,Extra.shop_id==sid))
    if not x: raise HTTPException(404,"Extra not found")
    for k,v in data.model_dump().items(): setattr(x,k,v)
    activity(db,sid,payload,"Extra updated",x.name); db.commit(); return extra_json(x)


@app.delete("/api/shop-admin/extras/{extra_id}")
def admin_delete_extra(extra_id:int,payload=Depends(bearer_payload),db:Session=Depends(get_db)):
    sid=require_shop(payload); x=db.scalar(select(Extra).where(Extra.id==extra_id,Extra.shop_id==sid))
    if not x: raise HTTPException(404,"Extra not found")
    db.delete(x); activity(db,sid,payload,"Extra deleted",x.name); db.commit(); return {"ok":True}


@app.get("/api/shop-admin/offers")
def admin_offers(payload=Depends(bearer_payload),db:Session=Depends(get_db)):
    sid=require_shop(payload); return [offer_json(x) for x in db.scalars(select(Offer).where(Offer.shop_id==sid).order_by(Offer.id.desc())).all()]


@app.post("/api/shop-admin/offers")
def admin_add_offer(data:OfferIn,payload=Depends(bearer_payload),db:Session=Depends(get_db)):
    sid=require_shop(payload); raw=data.model_dump(); raw["promo_code"]=raw["promo_code"].strip().upper(); x=Offer(shop_id=sid,**raw); db.add(x)
    try: activity(db,sid,payload,"Offer created",x.promo_code); db.commit(); db.refresh(x)
    except Exception: db.rollback(); raise HTTPException(409,"Promo code already exists for this shop")
    return offer_json(x)


@app.patch("/api/shop-admin/offers/{offer_id}")
def admin_edit_offer(offer_id:int,data:OfferIn,payload=Depends(bearer_payload),db:Session=Depends(get_db)):
    sid=require_shop(payload); x=db.scalar(select(Offer).where(Offer.id==offer_id,Offer.shop_id==sid))
    if not x: raise HTTPException(404,"Offer not found")
    raw=data.model_dump(); raw["promo_code"]=raw["promo_code"].strip().upper()
    for k,v in raw.items(): setattr(x,k,v)
    activity(db,sid,payload,"Offer updated",x.promo_code); db.commit(); return offer_json(x)


@app.delete("/api/shop-admin/offers/{offer_id}")
def admin_delete_offer(offer_id:int,payload=Depends(bearer_payload),db:Session=Depends(get_db)):
    sid=require_shop(payload); x=db.scalar(select(Offer).where(Offer.id==offer_id,Offer.shop_id==sid))
    if not x: raise HTTPException(404,"Offer not found")
    db.delete(x); activity(db,sid,payload,"Offer deleted",x.promo_code); db.commit(); return {"ok":True}


@app.get("/api/shop-admin/deals")
def admin_deals(payload=Depends(bearer_payload),db:Session=Depends(get_db)):
    sid=require_shop(payload); return [deal_json(x) for x in db.scalars(select(Deal).where(Deal.shop_id==sid).order_by(Deal.id.desc())).all()]


@app.post("/api/shop-admin/deals")
def admin_add_deal(data:DealIn,payload=Depends(bearer_payload),db:Session=Depends(get_db)):
    sid=require_shop(payload); raw=data.model_dump(); rules=raw.pop("rules",[]); x=Deal(shop_id=sid,rules_json=json.dumps(rules),**raw); db.add(x); activity(db,sid,payload,"Deal created",x.title); db.commit(); db.refresh(x); return deal_json(x)


@app.patch("/api/shop-admin/deals/{deal_id}")
def admin_edit_deal(deal_id:int,data:DealIn,payload=Depends(bearer_payload),db:Session=Depends(get_db)):
    sid=require_shop(payload); x=db.scalar(select(Deal).where(Deal.id==deal_id,Deal.shop_id==sid))
    if not x: raise HTTPException(404,"Deal not found")
    raw=data.model_dump(); rules=raw.pop("rules",[]); raw["rules_json"]=json.dumps(rules)
    for k,v in raw.items(): setattr(x,k,v)
    activity(db,sid,payload,"Deal updated",x.title); db.commit(); return deal_json(x)


@app.delete("/api/shop-admin/deals/{deal_id}")
def admin_delete_deal(deal_id:int,payload=Depends(bearer_payload),db:Session=Depends(get_db)):
    sid=require_shop(payload); x=db.scalar(select(Deal).where(Deal.id==deal_id,Deal.shop_id==sid))
    if not x: raise HTTPException(404,"Deal not found")
    db.delete(x); activity(db,sid,payload,"Deal deleted",x.title); db.commit(); return {"ok":True}


@app.get("/api/shop-admin/notifications")
def admin_notifications(payload=Depends(bearer_payload),db:Session=Depends(get_db)):
    sid=require_shop(payload); return [{"id":x.id,"title":x.title,"message":x.message,"is_active":x.is_active,"created_at":x.created_at.isoformat()} for x in db.scalars(select(ShopNotification).where(ShopNotification.shop_id==sid).order_by(ShopNotification.id.desc())).all()]


@app.post("/api/shop-admin/notifications")
def admin_add_notification(data:NotificationIn,payload=Depends(bearer_payload),db:Session=Depends(get_db)):
    sid=require_shop(payload); x=ShopNotification(shop_id=sid,**data.model_dump()); db.add(x); activity(db,sid,payload,"Notification created",x.title); db.commit(); db.refresh(x); return {"id":x.id,"title":x.title,"message":x.message,"is_active":x.is_active}


@app.get("/api/shop-admin/customers")
def admin_customers(payload=Depends(bearer_payload),db:Session=Depends(get_db)):
    sid=require_shop(payload)
    rows=db.execute(select(Order.customer_phone,func.max(Order.customer_name),func.count(Order.id),func.coalesce(func.sum(Order.total),0),func.max(Order.created_at)).where(Order.shop_id==sid,Order.status!="cancelled").group_by(Order.customer_phone).order_by(func.max(Order.created_at).desc())).all()
    return [{"phone":r[0],"name":r[1],"orders":int(r[2]),"spend":float(r[3] or 0),"last_order":r[4].isoformat() if r[4] else None} for r in rows]


@app.get("/api/shop-admin/feedback")
def admin_feedback(payload=Depends(bearer_payload),db:Session=Depends(get_db)):
    sid=require_shop(payload); return [{"id":x.id,"order_id":x.order_id,"customer_phone":x.customer_phone,"rating":x.rating,"comment":x.comment,"created_at":x.created_at.isoformat()} for x in db.scalars(select(Feedback).where(Feedback.shop_id==sid).order_by(Feedback.id.desc())).all()]


@app.post("/api/public/shops/{slug}/feedback")
def public_feedback(slug:str,data:FeedbackIn,payload=Depends(bearer_payload),db:Session=Depends(get_db)):
    cid=require_customer(payload)
    customer=db.get(CustomerAccount,cid)
    shop=db.scalar(select(Shop).where(Shop.slug==slug,Shop.is_active==True))
    if not customer or not shop:
        raise HTTPException(404,"Not found")
    order=None
    if data.order_id:
        order=db.scalar(select(Order).where(Order.id==data.order_id,Order.shop_id==shop.id,Order.customer_phone==customer.phone))
        if not order:
            raise HTTPException(404,"Order not found")
        if order.status != "delivered" and order.rider_status != "delivered":
            raise HTTPException(400,"You can rate this shop after delivery")
    existing = None
    if data.order_id:
        existing = db.scalar(
            select(Feedback)
            .where(
                Feedback.shop_id == shop.id,
                Feedback.order_id == data.order_id,
                Feedback.customer_phone == customer.phone,
            )
            .order_by(Feedback.id.desc())
        )
    if existing:
        existing.rating = data.rating
        existing.comment = data.comment
        x = existing
    else:
        x=Feedback(shop_id=shop.id,order_id=data.order_id,customer_phone=customer.phone,rating=data.rating,comment=data.comment)
        db.add(x)
    db.commit()
    rating = shop_rating_summary(db, shop.id)
    return {"ok":True,"rating":x.rating,**rating}


@app.get("/api/shop-admin/activity-logs")
def admin_activity_logs(payload=Depends(bearer_payload),db:Session=Depends(get_db)):
    sid=require_shop(payload); return [{"id":x.id,"action":x.action,"detail":x.detail,"admin_id":x.admin_id,"created_at":x.created_at.isoformat()} for x in db.scalars(select(ActivityLog).where(ActivityLog.shop_id==sid).order_by(ActivityLog.id.desc()).limit(300)).all()]


@app.get("/api/shop-admin/accounts")
def admin_accounts(payload=Depends(bearer_payload),db:Session=Depends(get_db)):
    sid=require_shop(payload); admins=db.scalars(select(ShopAdmin).where(ShopAdmin.shop_id==sid).order_by(ShopAdmin.id)).all(); return [{"id":a.id,"name":a.name,"email":a.email,"role":a.role,"is_active":a.is_active,"permissions":admin_permissions(a)} for a in admins]


@app.post("/api/shop-admin/accounts")
def admin_add_account(data:AdminCreate,payload=Depends(bearer_payload),db:Session=Depends(get_db)):
    sid=require_shop(payload); current=db.get(ShopAdmin,int(payload.get("admin_id",0)))
    if not current or current.role!="owner": raise HTTPException(403,"Owner account required")
    if db.scalar(select(ShopAdmin).where(ShopAdmin.shop_id==sid,func.lower(ShopAdmin.email)==data.email.lower())): raise HTTPException(409,"Email already exists")
    a=ShopAdmin(shop_id=sid,name=data.name,email=data.email.lower(),password_hash=hash_password(data.password),role=data.role,permissions_json=json.dumps(data.permissions or {})); db.add(a); activity(db,sid,payload,"Admin account created",a.email); db.commit(); db.refresh(a); return {"id":a.id,"email":a.email}


@app.patch("/api/shop-admin/accounts/{admin_id}")
def admin_update_account(admin_id:int,data:AdminUpdate,payload=Depends(bearer_payload),db:Session=Depends(get_db)):
    sid=require_shop(payload); current=db.get(ShopAdmin,int(payload.get("admin_id",0)))
    if not current or current.role!="owner": raise HTTPException(403,"Owner account required")
    a=db.scalar(select(ShopAdmin).where(ShopAdmin.id==admin_id,ShopAdmin.shop_id==sid));
    if not a: raise HTTPException(404,"Admin not found")
    raw=data.model_dump(exclude_unset=True); password=raw.pop("password",None); permissions=raw.pop("permissions",None)
    if password: a.password_hash=hash_password(password)
    if permissions is not None: a.permissions_json=json.dumps(permissions)
    for k,v in raw.items(): setattr(a,k,v)
    activity(db,sid,payload,"Admin account updated",a.email); db.commit(); return {"ok":True}


@app.get("/api/shop-admin/orders")
def admin_orders(payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_shop(payload)
    orders = db.scalars(
        select(Order).options(selectinload(Order.items), selectinload(Order.rider), selectinload(Order.shop)).where(Order.shop_id == sid).order_by(Order.id.desc()).limit(250)
    ).all()
    return [order_json(o) for o in orders]


@app.patch("/api/shop-admin/orders/{order_id}/status")
def admin_order_status(order_id: int, data: OrderStatusIn, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_shop(payload)
    order = db.scalar(select(Order).where(Order.id == order_id, Order.shop_id == sid))
    if not order:
        raise HTTPException(404, "Order not found")
    if data.status in {"accepted", "preparing", "ready"}:
        raise HTTPException(409, "Accept, Preparing and Ready are controlled from the Kitchen app")
    if data.status not in {"cancelled", "delivered"}:
        raise HTTPException(400, "Shop Admin can only cancel an order or complete shop-owned delivery")
    order.status = data.status
    if data.status == "cancelled":
        release_rider(db, order)
        order.rider_status = "cancelled"
    if data.status == "delivered":
        if order.delivery_mode != "shop":
            raise HTTPException(409, "Mahi Eats rider must complete this delivery")
        order.rider_status = "delivered"
        order.delivered_at = datetime.utcnow()
    db.commit()
    return {"id": order.id, "status": order.status, "rider_id": order.rider_id, "rider_status": order.rider_status}


@app.patch("/api/shop-admin/orders/{order_id}/merchant-rider")
def set_merchant_rider(order_id: int, data: MerchantRiderIn, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_shop(payload)
    order = db.scalar(select(Order).where(Order.id == order_id, Order.shop_id == sid))
    if not order:
        raise HTTPException(404, "Order not found")
    if order.delivery_mode != "shop":
        raise HTTPException(409, "This order uses Mahi Eats delivery")
    order.merchant_rider_name = data.name
    order.merchant_rider_phone = data.phone
    order.rider_status = "assigned"
    order.assigned_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@app.get("/api/shop-admin/stats")
def admin_stats(payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_shop(payload)
    return {
        "orders": db.scalar(select(func.count()).select_from(Order).where(Order.shop_id == sid)) or 0,
        "sales": float(db.scalar(select(func.coalesce(func.sum(Order.total), 0)).where(Order.shop_id == sid, Order.status != "cancelled")) or 0),
        "products": db.scalar(select(func.count()).select_from(Product).where(Product.shop_id == sid)) or 0,
        "pending": db.scalar(select(func.count()).select_from(Order).where(Order.shop_id == sid, Order.status.not_in(["delivered", "cancelled"]))) or 0,
    }


# ---------- KITCHEN ----------
@app.get("/api/kitchen/me")
def kitchen_me(payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_kitchen(payload)
    shop = db.get(Shop, sid)
    return shop_json(shop)


@app.get("/api/kitchen/orders")
def kitchen_orders(payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_kitchen(payload)
    orders = db.scalars(
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.rider), selectinload(Order.shop))
        .where(Order.shop_id == sid, Order.status.not_in(["delivered", "cancelled"]))
        .order_by(Order.id.asc())
        .limit(200)
    ).all()
    return [order_json(o) for o in orders]


@app.get("/api/kitchen/history")
def kitchen_history(day: str = Query("today"), payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_kitchen(payload)
    if day not in {"today", "yesterday"}:
        raise HTTPException(400, "day must be today or yesterday")
    bounds = _uae_period_bounds()
    today_start = bounds["today"]
    start = today_start if day == "today" else today_start - timedelta(days=1)
    end = bounds["now"] if day == "today" else today_start
    orders = db.scalars(
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.rider), selectinload(Order.shop))
        .where(Order.shop_id == sid, Order.created_at >= start, Order.created_at < end)
        .order_by(Order.id.desc())
        .limit(300)
    ).all()
    return [order_json(o) for o in orders]


@app.patch("/api/kitchen/orders/{order_id}/status")
def kitchen_status(order_id: int, data: OrderStatusIn, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_kitchen(payload)
    order = db.scalar(select(Order).where(Order.id == order_id, Order.shop_id == sid))
    if not order:
        raise HTTPException(404, "Order not found")
    transitions = {
        "new": {"accepted", "cancelled"},
        "accepted": {"preparing", "cancelled"},
        "preparing": {"ready", "cancelled"},
        "ready": {"cancelled"},
    }
    if data.status == order.status:
        return {"id": order.id, "status": order.status, "rider_id": order.rider_id, "rider_status": order.rider_status}
    if data.status not in transitions.get(order.status, set()):
        raise HTTPException(409, f"Kitchen cannot change {order.status} directly to {data.status}")
    order.status = data.status
    if data.status == "cancelled":
        release_rider(db, order)
        order.rider_status = "cancelled"
    db.commit()
    return {"id": order.id, "status": order.status, "rider_id": order.rider_id, "rider_status": order.rider_status}


# ---------- CENTRAL MAHI EATS RIDER ----------
@app.get("/api/rider/me")
def rider_me(payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    rid = require_rider(payload)
    rider = db.get(Rider, rid)
    if not rider or not rider.is_active:
        raise HTTPException(403, "Rider account disabled")
    return rider_json(rider, private=True)


@app.patch("/api/rider/status")
def rider_status(data: RiderStatusIn, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    rid = require_rider(payload)
    rider = db.get(Rider, rid)
    updates = data.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(rider, k, v)
    if not rider.is_online:
        rider.is_available = False
    db.commit()
    db.refresh(rider)
    return rider_json(rider, private=True)


@app.post("/api/rider/location")
def rider_location(data: RiderLocationIn, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    rid = require_rider(payload)
    rider = db.get(Rider, rid)
    rider.latitude = data.latitude
    rider.longitude = data.longitude
    rider.location_updated_at = datetime.utcnow()
    rider.is_online = True
    db.commit()
    return {"ok": True, "updated_at": rider.location_updated_at.isoformat()}


@app.post("/api/rider/heartbeat")
def rider_heartbeat(payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    rid = require_rider(payload)
    rider = db.get(Rider, rid)
    if not rider or not rider.is_active:
        raise HTTPException(403, "Rider account disabled")
    rider.is_online = True
    db.commit()
    return {"ok": True}


def _rider_period_window(period: str, date_from: str | None = None, date_to: str | None = None):
    bounds = _uae_period_bounds()
    if period == "all":
        return None, None, "All Time"
    if period == "today":
        return bounds["today"], None, "Today"
    if period == "yesterday":
        return bounds["yesterday"], bounds["today"], "Yesterday"
    if period == "week":
        return bounds["week"], None, "This Week"
    if period == "month":
        return bounds["month"], None, "This Month"
    if period == "year":
        return bounds["year"], None, "This Year"
    if period == "custom":
        if not date_from or not date_to:
            raise HTTPException(400, "Select custom from and to dates")
        try:
            tz = ZoneInfo("Asia/Dubai")
            start_local = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=tz)
            end_local = (datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)).replace(tzinfo=tz)
            start = start_local.astimezone(timezone.utc).replace(tzinfo=None)
            end = end_local.astimezone(timezone.utc).replace(tzinfo=None)
            return start, end, f"{date_from} to {date_to}"
        except ValueError:
            raise HTTPException(400, "Use YYYY-MM-DD for custom dates")
    raise HTTPException(400, "Invalid report period")


def _rider_cash_balance(db: Session, rider_id: int):
    cash_filter = func.lower(Order.payment_method).like("%cash%")
    cash_due = float(db.scalar(
        select(func.coalesce(func.sum(Order.total), 0)).where(
            Order.rider_id == rider_id,
            Order.status == "delivered",
            cash_filter,
        )
    ) or 0)
    approved = float(db.scalar(
        select(func.coalesce(func.sum(RiderCashSubmission.amount), 0)).where(
            RiderCashSubmission.rider_id == rider_id,
            RiderCashSubmission.status == "approved",
        )
    ) or 0)
    awaiting = float(db.scalar(
        select(func.coalesce(func.sum(RiderCashSubmission.amount), 0)).where(
            RiderCashSubmission.rider_id == rider_id,
            RiderCashSubmission.status == "pending",
        )
    ) or 0)
    rejected = float(db.scalar(
        select(func.coalesce(func.sum(RiderCashSubmission.amount), 0)).where(
            RiderCashSubmission.rider_id == rider_id,
            RiderCashSubmission.status == "rejected",
        )
    ) or 0)
    return {
        "cash_due_to_admin": round(cash_due, 2),
        "approved_cash": round(approved, 2),
        "awaiting_approval": round(awaiting, 2),
        "rejected_cash": round(rejected, 2),
        "remaining_to_submit": round(max(cash_due - approved - awaiting, 0), 2),
        "total_pending_cash": round(max(cash_due - approved, 0), 2),
    }


@app.get("/api/rider/history")
def rider_history(
    period: str = Query("today"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    payload=Depends(bearer_payload),
    db: Session = Depends(get_db),
):
    rid = require_rider(payload)
    start, end, _ = _rider_period_window(period, date_from, date_to)
    time_col = func.coalesce(Order.delivered_at, Order.created_at)
    filters = [Order.rider_id == rid, Order.status == "delivered"]
    if start is not None:
        filters.append(time_col >= start)
    if end is not None:
        filters.append(time_col < end)
    orders = db.scalars(
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.shop), selectinload(Order.rider), selectinload(Order.delivery_meta))
        .where(*filters)
        .order_by(time_col.desc(), Order.id.desc())
        .limit(300)
    ).all()
    return [order_json(o) for o in orders]


@app.get("/api/rider/finance")
def rider_finance(
    period: str = Query("today"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    payload=Depends(bearer_payload),
    db: Session = Depends(get_db),
):
    rid = require_rider(payload)
    rider = db.get(Rider, rid)
    if not rider:
        raise HTTPException(404, "Rider not found")
    start, end, label = _rider_period_window(period, date_from, date_to)
    time_col = func.coalesce(Order.delivered_at, Order.created_at)
    filters = [Order.rider_id == rid, Order.status == "delivered"]
    if start is not None:
        filters.append(time_col >= start)
    if end is not None:
        filters.append(time_col < end)
    orders = db.scalars(select(Order).where(*filters).order_by(time_col.desc())).all()
    cash_orders = [o for o in orders if "cash" in str(o.payment_method or "").lower()]
    card_orders = [o for o in orders if o not in cash_orders]
    customer_total = sum(float(o.total or 0) for o in orders)
    delivery_charges = sum(float(o.delivery_fee or 0) for o in orders)
    cash_collected = sum(float(o.total or 0) for o in cash_orders)
    balance = _rider_cash_balance(db, rid)
    submissions = int(db.scalar(select(func.count()).select_from(RiderCashSubmission).where(RiderCashSubmission.rider_id == rid)) or 0)
    return {
        "rider": rider_json(rider),
        "period": {"key": period, "label": label, "date_from": date_from, "date_to": date_to},
        "totals": {
            "delivered_orders": len(orders),
            "customer_total": round(customer_total, 2),
            "delivery_charges": round(delivery_charges, 2),
            "rider_tips": 0.0,
            "rider_earnings": round(delivery_charges, 2),
            "cash_collected": round(cash_collected, 2),
            "cash_orders": len(cash_orders),
            "card_orders": len(card_orders),
        },
        "settlements": {
            "approved_cash": balance["approved_cash"],
            "awaiting_approval": balance["awaiting_approval"],
            "rejected_cash": balance["rejected_cash"],
            "submissions": submissions,
        },
        "current_balance": balance,
    }


@app.get("/api/rider/cash-submissions")
def rider_cash_submissions(payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    rid = require_rider(payload)
    items = db.scalars(
        select(RiderCashSubmission)
        .where(RiderCashSubmission.rider_id == rid)
        .order_by(RiderCashSubmission.id.desc())
        .limit(100)
    ).all()
    return [{
        "id": x.id,
        "amount": float(x.amount or 0),
        "status": x.status,
        "rider_note": x.rider_note,
        "admin_note": x.admin_note,
        "reviewed_by": x.reviewed_by,
        "submitted_at": x.submitted_at.isoformat() if x.submitted_at else None,
        "reviewed_at": x.reviewed_at.isoformat() if x.reviewed_at else None,
    } for x in items]


@app.post("/api/rider/cash-submissions")
def rider_submit_cash(data: RiderCashIn, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    rid = require_rider(payload)
    balance = _rider_cash_balance(db, rid)
    amount = round(float(data.amount), 2)
    if amount > balance["remaining_to_submit"] + 0.01:
        raise HTTPException(409, f"Maximum cash available is AED {balance['remaining_to_submit']:.2f}")
    item = RiderCashSubmission(rider_id=rid, amount=amount, rider_note=(data.note or "").strip() or None)
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"ok": True, "id": item.id, "status": item.status}



@app.get("/api/super/feedback")
def super_feedback(payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    require_super(payload)
    rows = db.execute(
        select(Feedback, Shop.name, Shop.slug)
        .join(Shop, Shop.id == Feedback.shop_id)
        .order_by(Feedback.id.desc())
        .limit(1000)
    ).all()
    return [{
        "id": feedback.id,
        "shop_id": feedback.shop_id,
        "shop_name": shop_name,
        "shop_slug": shop_slug,
        "order_id": feedback.order_id,
        "customer_phone": feedback.customer_phone,
        "rating": feedback.rating,
        "comment": feedback.comment,
        "created_at": feedback.created_at.isoformat(),
    } for feedback, shop_name, shop_slug in rows]


@app.delete("/api/super/feedback/{feedback_id}")
def super_delete_feedback(feedback_id: int, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    require_super(payload)
    feedback = db.get(Feedback, feedback_id)
    if not feedback:
        raise HTTPException(404, "Feedback not found")
    db.delete(feedback)
    db.commit()
    return {"ok": True}


@app.get("/api/super/rider-cash")
def super_rider_cash(payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    require_super(payload)
    rows = db.scalars(select(RiderCashSubmission).order_by(RiderCashSubmission.id.desc()).limit(300)).all()
    result = []
    for x in rows:
        rider = db.get(Rider, x.rider_id)
        result.append({
            "id": x.id, "rider_id": x.rider_id,
            "rider_name": rider.name if rider else "Rider",
            "rider_phone": rider.phone if rider else "",
            "amount": float(x.amount or 0), "status": x.status,
            "rider_note": x.rider_note, "admin_note": x.admin_note,
            "submitted_at": x.submitted_at.isoformat() if x.submitted_at else None,
            "reviewed_at": x.reviewed_at.isoformat() if x.reviewed_at else None,
        })
    return result


@app.patch("/api/super/rider-cash/{submission_id}")
def super_review_rider_cash(submission_id: int, data: RiderCashReviewIn, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    require_super(payload)
    item = db.get(RiderCashSubmission, submission_id)
    if not item:
        raise HTTPException(404, "Cash submission not found")
    status = str(data.status or "").lower()
    if status not in {"approved", "rejected"}:
        raise HTTPException(400, "Status must be approved or rejected")
    if item.status != "pending":
        raise HTTPException(409, "This cash submission is already reviewed")
    item.status = status
    item.admin_note = (data.admin_note or "").strip() or None
    item.reviewed_by = "Super Admin"
    item.reviewed_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "id": item.id, "status": item.status}


@app.get("/api/rider/orders")
def rider_orders(payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    rid = require_rider(payload)
    orders = db.scalars(
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.shop), selectinload(Order.rider), selectinload(Order.delivery_meta))
        .where(Order.rider_id == rid, Order.status.not_in(["cancelled"]), Order.rider_status != "delivered")
        .order_by(Order.id.asc())
        .limit(100)
    ).all()

    # Backfill the road distance for an older active order if it already has an exact customer GPS pin.
    # We do not change the old customer's price; this only gives the rider the correct route distance.
    changed = False
    for order in orders:
        if order.delivery_meta is None and order.shop and order.customer_latitude is not None and order.customer_longitude is not None:
            try:
                quote = delivery_quote(db, order.shop, order.customer_latitude, order.customer_longitude)
                if quote.get("distance_km") is not None:
                    order.delivery_meta = OrderDeliveryMeta(
                        order_id=order.id,
                        distance_km=quote["distance_km"],
                        duration_seconds=quote.get("duration_seconds"),
                        distance_source=quote.get("distance_source"),
                        base_fee=quote.get("base_fee", 0),
                        free_km=quote.get("free_km", 0),
                        per_km_fee=quote.get("per_km_fee", 0),
                        calculated_fee=float(order.delivery_fee or 0),
                    )
                    db.add(order.delivery_meta)
                    changed = True
            except HTTPException:
                pass
    if changed:
        db.commit()
    return [order_json(o) for o in orders]


@app.patch("/api/rider/orders/{order_id}/status")
def rider_order_status(order_id: int, data: OrderStatusIn, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    rid = require_rider(payload)
    order = db.scalar(select(Order).where(Order.id == order_id, Order.rider_id == rid))
    if not order:
        raise HTTPException(404, "Assigned order not found")
    status = str(data.status or "").lower().strip()
    if status not in {"accepted", "rejected", "picked_up", "on_the_way", "delivered"}:
        raise HTTPException(400, "Invalid rider status")
    current = str(order.rider_status or "assigned").lower().strip()
    allowed = {
        "assigned": {"accepted", "rejected"},
        "accepted": {"picked_up", "rejected"},
        "picked_up": {"on_the_way", "delivered"},
        "on_the_way": {"delivered"},
    }
    if status == current:
        return {"id": order.id, "status": order.status, "rider_status": order.rider_status}
    if status not in allowed.get(current, set()):
        raise HTTPException(409, f"Cannot change rider status from {current} to {status}")
    if status == "picked_up" and order.status != "ready":
        raise HTTPException(409, "Waiting for Kitchen Ready")
    rider = db.get(Rider, rid)
    if status == "rejected":
        order.rider_id = None
        order.rider_status = "unassigned"
        order.assigned_at = None
        if rider:
            rider.is_available = True
        db.commit()
        return {"id": order.id, "status": order.status, "rider_status": "rejected"}
    order.rider_status = status
    if status == "picked_up":
        order.picked_up_at = datetime.utcnow()
    elif status == "on_the_way" and not order.picked_up_at:
        order.picked_up_at = datetime.utcnow()
    elif status == "delivered":
        order.delivered_at = datetime.utcnow()
        order.status = "delivered"
        if rider:
            rider.is_available = True
    db.commit()
    return {"id": order.id, "status": order.status, "rider_status": order.rider_status}
