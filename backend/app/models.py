from __future__ import annotations
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


class Shop(Base):
    __tablename__ = "shops"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(80), default="Restaurant")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    banner_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str] = mapped_column(String(80), default="Fujairah")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    delivery_fee: Mapped[float] = mapped_column(Float, default=0)
    min_order: Mapped[float] = mapped_column(Float, default=0)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=30)
    delivery_mode: Mapped[str] = mapped_column(String(30), default="mahi_eats", index=True)
    commission_percent: Mapped[float] = mapped_column(Float, default=0)
    kitchen_pin_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    admins = relationship("ShopAdmin", back_populates="shop", cascade="all, delete-orphan")
    delivery_rule = relationship("ShopDeliveryRule", back_populates="shop", uselist=False, cascade="all, delete-orphan")


class ShopAdmin(Base):
    __tablename__ = "shop_admins"
    __table_args__ = (UniqueConstraint("shop_id", "email", name="uq_shop_admin_email"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), default="Shop Admin")
    email: Mapped[str] = mapped_column(String(200), index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    shop = relationship("Shop", back_populates="admins")


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("shop_id", "name", name="uq_category_shop_name"),
        Index("ix_category_shop_sort", "shop_id", "sort_order"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        Index("ix_product_shop_category", "shop_id", "category_id"),
        Index("ix_product_shop_active", "shop_id", "is_active"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(180))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[float] = mapped_column(Float)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Rider(Base):
    __tablename__ = "riders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True, nullable=False)
    phone: Mapped[str] = mapped_column(String(40), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    photo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_order_shop_created", "shop_id", "created_at"),
        Index("ix_order_shop_status", "shop_id", "status"),
        Index("ix_order_rider_status", "rider_id", "status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True)
    customer_name: Mapped[str] = mapped_column(String(120))
    customer_phone: Mapped[str] = mapped_column(String(40), index=True)
    delivery_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    customer_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="new", index=True)
    payment_method: Mapped[str] = mapped_column(String(30), default="cash")
    delivery_mode: Mapped[str] = mapped_column(String(30), default="mahi_eats")
    rider_id: Mapped[int | None] = mapped_column(ForeignKey("riders.id", ondelete="SET NULL"), nullable=True, index=True)
    rider_status: Mapped[str] = mapped_column(String(30), default="unassigned", index=True)
    merchant_rider_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    merchant_rider_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    subtotal: Mapped[float] = mapped_column(Float, default=0)
    delivery_fee: Mapped[float] = mapped_column(Float, default=0)
    total: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    rider = relationship("Rider")
    shop = relationship("Shop")
    delivery_meta = relationship("OrderDeliveryMeta", back_populates="order", uselist=False, cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(180))
    qty: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[float] = mapped_column(Float)
    line_total: Mapped[float] = mapped_column(Float)
    order = relationship("Order", back_populates="items")


class CustomerAccount(Base):
    __tablename__ = "customer_accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    pin_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ShopDeliveryRule(Base):
    __tablename__ = "shop_delivery_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    area_note: Mapped[str | None] = mapped_column(String(240), nullable=True)
    base_fee: Mapped[float] = mapped_column(Float, default=0)
    free_km: Mapped[float] = mapped_column(Float, default=0)
    per_km_fee: Mapped[float] = mapped_column(Float, default=0)
    max_delivery_km: Mapped[float] = mapped_column(Float, default=0)
    max_fee: Mapped[float] = mapped_column(Float, default=0)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    shop = relationship("Shop", back_populates="delivery_rule")


class OrderDeliveryMeta(Base):
    __tablename__ = "order_delivery_meta"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distance_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    base_fee: Mapped[float] = mapped_column(Float, default=0)
    free_km: Mapped[float] = mapped_column(Float, default=0)
    per_km_fee: Mapped[float] = mapped_column(Float, default=0)
    calculated_fee: Mapped[float] = mapped_column(Float, default=0)
    order = relationship("Order", back_populates="delivery_meta")
