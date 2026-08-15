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
from .models import Category, CustomerAccount, Order, OrderDeliveryMeta, OrderItem, Product, Rider, Shop, ShopAdmin, ShopDeliveryRule
from .schemas import (
    AdminCreate,
    CustomerLoginIn,
    CustomerRegisterIn,
    DeliveryQuoteIn,
    DeliveryRuleIn,
    AssignRiderIn,
    CategoryIn,
    KitchenLoginIn,
    KitchenPinIn,
    LoginIn,
    MerchantRiderIn,
    OrderCreate,
    OrderStatusIn,
    ProductIn,
    RiderCreate,
    RiderLocationIn,
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
    Base.metadata.create_all(bind=engine)
    # V5: safely add operating_status to existing databases without resetting data.
    try:
        cols = {c["name"] for c in inspect(engine).get_columns("shops")}
        if "operating_status" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE shops ADD COLUMN operating_status VARCHAR(20) DEFAULT 'open'"))
                conn.execute(text("UPDATE shops SET operating_status = CASE WHEN is_open THEN 'open' ELSE 'closed' END"))
    except Exception as exc:
        print("V5 schema migration warning:", exc)
    yield


app = FastAPI(title="Mahi Eats API", version="5.0.0", lifespan=lifespan)
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
            pass
    # Development fallback so the app can still be tested before a routing key is configured.
    estimate = km_distance(origin_lat, origin_lon, dest_lat, dest_lon)
    return (round(float(estimate), 2) if estimate is not None else None), None, "straight_line_estimate"


def delivery_quote(db: Session, shop: Shop, latitude: float, longitude: float):
    if shop.latitude is None or shop.longitude is None:
        raise HTTPException(409, "Shop delivery location is not configured by Super Admin")
    rule = get_delivery_rule(db, shop)
    rule_data = delivery_rule_json(rule, shop)
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
    }


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
        data["items"] = [{"name": i.name, "qty": i.qty, "unit_price": i.unit_price, "line_total": i.line_total} for i in o.items]
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
    week = today - timedelta(days=today.weekday())
    month = today.replace(day=1)

    def utc_naive(value):
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    return {
        "today": utc_naive(today),
        "week": utc_naive(week),
        "month": utc_naive(month),
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
    orders = int(db.scalar(select(func.count()).select_from(Order).where(*filters)) or 0)
    cancelled = int(db.scalar(select(func.count()).select_from(Order).where(*all_filters, Order.status == "cancelled")) or 0)
    pending = int(db.scalar(select(func.count()).select_from(Order).where(*all_filters, Order.status.not_in(["delivered", "cancelled"]))) or 0)
    delivered = int(db.scalar(select(func.count()).select_from(Order).where(*all_filters, Order.status == "delivered")) or 0)
    cash_sales = float(db.scalar(select(func.coalesce(func.sum(Order.total), 0)).where(*filters, func.lower(Order.payment_method).like("%cash%"))) or 0)
    cash_orders = int(db.scalar(select(func.count()).select_from(Order).where(*filters, func.lower(Order.payment_method).like("%cash%"))) or 0)
    card_sales = max(sales - cash_sales, 0.0)
    card_orders = max(orders - cash_orders, 0)
    commission = food_sales * float(shop.commission_percent or 0) / 100.0
    shop_delivery_income = delivery_fees if shop.delivery_mode == "shop" else 0.0
    shop_receivable = max(food_sales - commission + shop_delivery_income, 0.0)
    return {
        "orders": orders,
        "pending": pending,
        "delivered": delivered,
        "cancelled": cancelled,
        "customer_sales": sales,
        "food_sales": food_sales,
        "delivery_fees": delivery_fees,
        "cash_sales": cash_sales,
        "cash_orders": cash_orders,
        "card_sales": card_sales,
        "card_orders": card_orders,
        "commission": commission,
        "commission_percent": float(shop.commission_percent or 0),
        "shop_receivable": shop_receivable,
    }


def _shop_dashboard(db: Session, shop: Shop):
    bounds = _uae_period_bounds()
    return {
        "shop": shop_json(shop),
        "today": _shop_period_stats(db, shop, bounds["today"]),
        "week": _shop_period_stats(db, shop, bounds["week"]),
        "month": _shop_period_stats(db, shop, bounds["month"]),
        "all": _shop_period_stats(db, shop, None),
    }


@app.get("/api/health")
def health():
    return {"ok": True, "app": "Mahi Eats", "version": "4.0.0", "road_routing_ready": bool(GOOGLE_MAPS_API_KEY)}


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
    return {"token": issue_token("shop_admin", shop_id=shop.id, admin_id=admin.id), "shop": shop_json(shop)}


@app.post("/api/kitchen/login")
def kitchen_login(data: KitchenLoginIn, db: Session = Depends(get_db)):
    shop = db.scalar(select(Shop).where(Shop.slug == data.shop_slug.lower().strip(), Shop.is_active == True))
    if not shop or not verify_password(data.pin, shop.kitchen_pin_hash):
        raise HTTPException(401, "Wrong shop or kitchen PIN")
    return {"token": issue_token("kitchen", shop_id=shop.id), "shop": shop_json(shop)}


@app.post("/api/rider/login")
def rider_login(data: LoginIn, db: Session = Depends(get_db)):
    rider = db.scalar(select(Rider).where(func.lower(Rider.email) == data.email.lower(), Rider.is_active == True))
    if not rider or not verify_password(data.password, rider.password_hash):
        raise HTTPException(401, "Wrong email or password")
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
    return [order_json(o, public=True) for o in orders]


# ---------- CUSTOMER / PUBLIC ----------
@app.get("/api/public/shops")
def public_shops(q: str | None = Query(None), city: str | None = Query(None), db: Session = Depends(get_db)):
    stmt = select(Shop).where(Shop.is_active == True)
    if q:
        term = f"%{q.strip()}%"
        stmt = stmt.where((Shop.name.ilike(term)) | (Shop.category.ilike(term)))
    if city:
        stmt = stmt.where(Shop.city.ilike(f"%{city.strip()}%"))
    shops = db.scalars(stmt.order_by(Shop.is_open.desc(), Shop.name.asc()).limit(300)).all()
    return [shop_json(s) for s in shops]


@app.get("/api/public/shops/{slug}")
def public_shop(slug: str, db: Session = Depends(get_db)):
    shop = db.scalar(select(Shop).where(Shop.slug == slug, Shop.is_active == True))
    if not shop:
        raise HTTPException(404, "Shop not found")
    categories = db.scalars(select(Category).where(Category.shop_id == shop.id, Category.is_active == True).order_by(Category.sort_order, Category.name)).all()
    products = db.scalars(select(Product).where(Product.shop_id == shop.id, Product.is_active == True).order_by(Product.name)).all()
    return {
        "shop": shop_json(shop),
        "categories": [{"id": c.id, "name": c.name, "sort_order": c.sort_order} for c in categories],
        "products": [{"id": p.id, "category_id": p.category_id, "name": p.name, "description": p.description, "price": p.price, "image_url": p.image_url} for p in products],
    }


@app.post("/api/public/shops/{slug}/delivery-quote")
def public_delivery_quote(slug: str, data: DeliveryQuoteIn, db: Session = Depends(get_db)):
    shop = db.scalar(select(Shop).where(Shop.slug == slug, Shop.is_active == True))
    if not shop:
        raise HTTPException(404, "Shop not found")
    return delivery_quote(db, shop, data.latitude, data.longitude)


@app.post("/api/public/shops/{slug}/orders")
def create_order(slug: str, data: OrderCreate, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    cid = require_customer(payload)
    customer = db.get(CustomerAccount, cid)
    if not customer or not customer.is_active:
        raise HTTPException(401, "Customer login required")
    shop = db.scalar(select(Shop).where(Shop.slug == slug, Shop.is_active == True))
    if not shop:
        raise HTTPException(404, "Shop not found")
    if not shop.is_open:
        raise HTTPException(409, "Shop is closed")
    if not data.items:
        raise HTTPException(400, "Cart is empty")
    ids = [x.product_id for x in data.items]
    products = db.scalars(select(Product).where(Product.shop_id == shop.id, Product.id.in_(ids), Product.is_active == True)).all()
    pmap = {p.id: p for p in products}
    if len(pmap) != len(set(ids)):
        raise HTTPException(400, "One or more items are unavailable")
    subtotal = sum(pmap[i.product_id].price * i.qty for i in data.items)
    if subtotal < shop.min_order:
        raise HTTPException(400, f"Minimum order is AED {shop.min_order:.2f}")

    rule = get_delivery_rule(db, shop)
    rule_data = delivery_rule_json(rule, shop)
    dynamic_delivery = bool(float(rule_data["per_km_fee"] or 0) > 0 or float(rule_data["max_delivery_km"] or 0) > 0 or float(rule_data["free_km"] or 0) > 0)
    quote = None
    if dynamic_delivery:
        if data.customer_latitude is None or data.customer_longitude is None:
            raise HTTPException(400, "Add your delivery location to calculate road distance and delivery fee")
        quote = delivery_quote(db, shop, data.customer_latitude, data.customer_longitude)
        if not quote["deliverable"]:
            raise HTTPException(409, f"This shop delivers up to {quote['max_delivery_km']:.1f} km by road")
        delivery_fee = float(quote["delivery_fee"])
    else:
        delivery_fee = float(rule_data["base_fee"] if rule else shop.delivery_fee or 0)

    order = Order(
        shop_id=shop.id,
        customer_name=customer.name,
        customer_phone=customer.phone,
        delivery_address=data.delivery_address,
        customer_latitude=data.customer_latitude,
        customer_longitude=data.customer_longitude,
        payment_method=data.payment_method,
        delivery_mode=shop.delivery_mode,
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        total=subtotal + delivery_fee,
    )
    db.add(order)
    db.flush()
    for line in data.items:
        p = pmap[line.product_id]
        db.add(OrderItem(order_id=order.id, product_id=p.id, name=p.name, qty=line.qty, unit_price=p.price, line_total=p.price * line.qty))
    if quote:
        db.add(OrderDeliveryMeta(
            order_id=order.id,
            distance_km=quote["distance_km"],
            duration_seconds=quote["duration_seconds"],
            distance_source=quote["distance_source"],
            base_fee=quote["base_fee"],
            free_km=quote["free_km"],
            per_km_fee=quote["per_km_fee"],
            calculated_fee=delivery_fee,
        ))
    db.commit()
    return {"order_id": order.id, "total": order.total, "status": order.status, "tracking_phone": order.customer_phone, "delivery_fee": delivery_fee, "delivery_quote": quote}


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
            select(func.coalesce(func.sum(Order.subtotal * Shop.commission_percent / 100.0), 0)).join(Shop, Shop.id == Order.shop_id).where(Order.status != "cancelled")
        )
        or 0
    )
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
    admin = ShopAdmin(shop_id=shop_id, name=data.name, email=data.email.lower(), password_hash=hash_password(data.password))
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
    if db.scalar(select(Rider).where(func.lower(Rider.email) == data.email.lower())):
        raise HTTPException(409, "Rider email already exists")
    rider = Rider(name=data.name, email=data.email.lower(), phone=data.phone, photo_url=data.photo_url, password_hash=hash_password(data.password))
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
    for k, v in data.model_dump(exclude_unset=True).items():
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
    return shop_json(shop)


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
    if period not in {"today", "week", "month", "all"}:
        raise HTTPException(400, "period must be today, week, month or all")
    start = None if period == "all" else bounds[period]
    stats = _shop_period_stats(db, shop, start)
    q = select(Order).options(selectinload(Order.items), selectinload(Order.rider), selectinload(Order.shop)).where(Order.shop_id == sid)
    if start is not None:
        q = q.where(Order.created_at >= start)
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
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"id": c.id, "name": c.name, "sort_order": c.sort_order, "is_active": c.is_active}


@app.patch("/api/shop-admin/categories/{category_id}")
def admin_edit_category(category_id: int, data: CategoryIn, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_shop(payload)
    c = db.scalar(select(Category).where(Category.id == category_id, Category.shop_id == sid))
    if not c:
        raise HTTPException(404, "Category not found")
    for k, v in data.model_dump().items():
        setattr(c, k, v)
    db.commit()
    return {"id": c.id, "name": c.name, "sort_order": c.sort_order, "is_active": c.is_active}


@app.get("/api/shop-admin/products")
def admin_products(payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_shop(payload)
    ps = db.scalars(select(Product).where(Product.shop_id == sid).order_by(Product.id.desc())).all()
    return [{"id": p.id, "category_id": p.category_id, "name": p.name, "description": p.description, "price": p.price, "image_url": p.image_url, "is_active": p.is_active} for p in ps]


@app.post("/api/shop-admin/products")
def admin_add_product(data: ProductIn, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_shop(payload)
    if data.category_id:
        c = db.scalar(select(Category).where(Category.id == data.category_id, Category.shop_id == sid))
        if not c:
            raise HTTPException(400, "Invalid category")
    p = Product(shop_id=sid, **data.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return {"id": p.id, "name": p.name, "price": p.price}


@app.patch("/api/shop-admin/products/{product_id}")
def admin_edit_product(product_id: int, data: ProductIn, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_shop(payload)
    p = db.scalar(select(Product).where(Product.id == product_id, Product.shop_id == sid))
    if not p:
        raise HTTPException(404, "Product not found")
    if data.category_id:
        c = db.scalar(select(Category).where(Category.id == data.category_id, Category.shop_id == sid))
        if not c:
            raise HTTPException(400, "Invalid category")
    for k, v in data.model_dump().items():
        setattr(p, k, v)
    db.commit()
    return {"id": p.id, "name": p.name, "price": p.price, "is_active": p.is_active}


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


@app.get("/api/rider/orders")
def rider_orders(payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    rid = require_rider(payload)
    orders = db.scalars(
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.shop), selectinload(Order.rider))
        .where(Order.rider_id == rid, Order.status.not_in(["cancelled"]), Order.rider_status != "delivered")
        .order_by(Order.id.asc())
        .limit(100)
    ).all()
    return [order_json(o) for o in orders]


@app.patch("/api/rider/orders/{order_id}/status")
def rider_order_status(order_id: int, data: OrderStatusIn, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    rid = require_rider(payload)
    order = db.scalar(select(Order).where(Order.id == order_id, Order.rider_id == rid))
    if not order:
        raise HTTPException(404, "Assigned order not found")
    if data.status not in {"accepted", "picked_up", "on_the_way", "delivered"}:
        raise HTTPException(400, "Invalid rider status")
    if data.status == "picked_up" and order.status != "ready":
        raise HTTPException(409, "Kitchen has not marked the order ready yet")
    previous_rider_status = order.rider_status
    if data.status == "delivered" and previous_rider_status not in {"picked_up", "on_the_way"}:
        raise HTTPException(409, "Mark the order picked up before delivered")
    order.rider_status = data.status
    if data.status == "picked_up":
        order.picked_up_at = datetime.utcnow()
    elif data.status == "on_the_way" and not order.picked_up_at:
        order.picked_up_at = datetime.utcnow()
    elif data.status == "delivered":
        order.delivered_at = datetime.utcnow()
        order.status = "delivered"
        rider = db.get(Rider, rid)
        if rider:
            rider.is_available = True
    db.commit()
    return {"id": order.id, "status": order.status, "rider_status": order.rider_status}
