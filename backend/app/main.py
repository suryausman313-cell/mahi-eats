import math
import os
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .database import Base, engine, get_db
from .models import Category, Order, OrderItem, Product, Rider, Shop, ShopAdmin
from .schemas import (
    AdminCreate,
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
    require_kitchen,
    require_rider,
    require_shop,
    require_super,
    verify_password,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Mahi Eats API", version="2.0.0", lifespan=lifespan)
origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
        "min_order": s.min_order,
        "estimated_minutes": s.estimated_minutes,
        "delivery_mode": s.delivery_mode,
        "commission_percent": s.commission_percent,
        "is_active": s.is_active,
        "is_open": s.is_open,
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
        "created_at": o.created_at.isoformat(),
        "assigned_at": o.assigned_at.isoformat() if o.assigned_at else None,
        "picked_up_at": o.picked_up_at.isoformat() if o.picked_up_at else None,
        "delivered_at": o.delivered_at.isoformat() if o.delivered_at else None,
    }
    if o.shop:
        data["shop"] = {"id": o.shop.id, "name": o.shop.name, "slug": o.shop.slug, "phone": o.shop.phone, "address": o.shop.address}
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


@app.get("/api/health")
def health():
    return {"ok": True, "app": "Mahi Eats", "version": "2.0.0"}


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


# ---------- CUSTOMER / PUBLIC ----------
@app.get("/api/public/shops")
def public_shops(q: str | None = Query(None), city: str | None = Query(None), db: Session = Depends(get_db)):
    stmt = select(Shop).where(Shop.is_active == True)
    if q:
        term = f"%{q.strip()}%"
        stmt = stmt.where((Shop.name.ilike(term)) | (Shop.category.ilike(term)))
    if city:
        stmt = stmt.where(Shop.city.ilike(city.strip()))
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


@app.post("/api/public/shops/{slug}/orders")
def create_order(slug: str, data: OrderCreate, db: Session = Depends(get_db)):
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
    order = Order(
        shop_id=shop.id,
        customer_name=data.customer_name,
        customer_phone=data.customer_phone,
        delivery_address=data.delivery_address,
        customer_latitude=data.customer_latitude,
        customer_longitude=data.customer_longitude,
        payment_method=data.payment_method,
        delivery_mode=shop.delivery_mode,
        subtotal=subtotal,
        delivery_fee=shop.delivery_fee,
        total=subtotal + shop.delivery_fee,
    )
    db.add(order)
    db.flush()
    for line in data.items:
        p = pmap[line.product_id]
        db.add(OrderItem(order_id=order.id, product_id=p.id, name=p.name, qty=line.qty, unit_price=p.price, line_total=p.price * line.qty))
    db.commit()
    return {"order_id": order.id, "total": order.total, "status": order.status, "tracking_phone": order.customer_phone}


@app.get("/api/public/orders/{order_id}")
def public_order_tracking(order_id: int, phone: str = Query(...), db: Session = Depends(get_db)):
    order = db.scalar(
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.rider), selectinload(Order.shop))
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
        "sales": total_sales,
        "commission": commission,
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
    db.commit()
    db.refresh(shop)
    return shop_json(shop)


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


@app.get("/api/super/riders")
def super_riders(payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    require_super(payload)
    return [rider_json(r, private=True) for r in db.scalars(select(Rider).order_by(Rider.id.desc())).all()]


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
    if "delivery_mode" in updates and updates["delivery_mode"] not in {"mahi_eats", "shop"}:
        raise HTTPException(400, "Invalid delivery mode")
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
    allowed = {"new", "accepted", "preparing", "ready", "cancelled", "delivered"}
    if data.status not in allowed:
        raise HTTPException(400, "Invalid shop order status")
    order.status = data.status
    if data.status in {"accepted", "preparing", "ready"} and order.delivery_mode == "mahi_eats" and not order.rider_id:
        auto_assign_rider(db, order)
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


@app.patch("/api/kitchen/orders/{order_id}/status")
def kitchen_status(order_id: int, data: OrderStatusIn, payload=Depends(bearer_payload), db: Session = Depends(get_db)):
    sid = require_kitchen(payload)
    order = db.scalar(select(Order).where(Order.id == order_id, Order.shop_id == sid))
    if not order:
        raise HTTPException(404, "Order not found")
    if data.status not in {"accepted", "preparing", "ready", "cancelled"}:
        raise HTTPException(400, "Invalid kitchen status")
    order.status = data.status
    if data.status in {"accepted", "preparing", "ready"} and order.delivery_mode == "mahi_eats" and not order.rider_id:
        auto_assign_rider(db, order)
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
