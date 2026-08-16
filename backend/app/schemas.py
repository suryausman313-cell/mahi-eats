from typing import Any
from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    email: str
    password: str


class CustomerRegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=7, max_length=25)
    pin: str = Field(pattern=r"^[0-9]{4,6}$")


class CustomerLoginIn(BaseModel):
    phone: str = Field(min_length=7, max_length=25)
    pin: str = Field(pattern=r"^[0-9]{4,6}$")


class KitchenLoginIn(BaseModel):
    shop_slug: str
    pin: str


class ShopCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    category: str = "Restaurant"
    description: str | None = None
    logo_url: str | None = None
    banner_url: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str = "Fujairah"
    latitude: float | None = None
    longitude: float | None = None
    delivery_fee: float = 0
    min_order: float = 0
    estimated_minutes: int = 30
    delivery_mode: str = "mahi_eats"
    commission_percent: float = 0
    is_active: bool = True
    is_open: bool = True
    operating_status: str = "open"
    service_fee_enabled: bool = False
    service_fee: float = Field(default=0, ge=0)
    service_fee_type: str = "fixed"
    service_fee_applies_to: str = "delivery"
    small_order_fee_enabled: bool = False
    small_order_threshold: float = Field(default=20, ge=0)
    small_order_fee: float = Field(default=0, ge=0)


class ShopUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    description: str | None = None
    logo_url: str | None = None
    banner_url: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    delivery_fee: float | None = None
    min_order: float | None = None
    estimated_minutes: int | None = None
    delivery_mode: str | None = None
    commission_percent: float | None = None
    is_active: bool | None = None
    is_open: bool | None = None
    operating_status: str | None = None
    service_fee_enabled: bool | None = None
    service_fee: float | None = Field(default=None, ge=0)
    service_fee_type: str | None = None
    service_fee_applies_to: str | None = None
    small_order_fee_enabled: bool | None = None
    small_order_threshold: float | None = Field(default=None, ge=0)
    small_order_fee: float | None = Field(default=None, ge=0)


class ShopSettingsIn(BaseModel):
    is_open: bool | None = None
    operating_status: str | None = None
    delivery_mode: str | None = None
    delivery_fee: float | None = None
    min_order: float | None = None
    estimated_minutes: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    address: str | None = None
    phone: str | None = None
    description: str | None = None
    logo_url: str | None = None
    banner_url: str | None = None
    service_fee_enabled: bool | None = None
    service_fee: float | None = Field(default=None, ge=0)
    service_fee_type: str | None = None
    service_fee_applies_to: str | None = None
    small_order_fee_enabled: bool | None = None
    small_order_threshold: float | None = Field(default=None, ge=0)
    small_order_fee: float | None = Field(default=None, ge=0)


class KitchenPinIn(BaseModel):
    pin: str = Field(min_length=4, max_length=12)


class AdminCreate(BaseModel):
    name: str = "Shop Admin"
    email: str
    password: str = Field(min_length=6)
    role: str = "admin"
    permissions: dict[str, bool] | None = None


class AdminUpdate(BaseModel):
    name: str | None = None
    password: str | None = Field(default=None, min_length=6)
    is_active: bool | None = None
    permissions: dict[str, bool] | None = None


class RiderLoginIn(BaseModel):
    phone: str | None = None
    pin: str | None = None
    email: str | None = None
    password: str | None = None


class RiderCreate(BaseModel):
    name: str
    phone: str
    pin: str | None = Field(default=None, min_length=4, max_length=12)
    email: str | None = None
    password: str | None = Field(default=None, min_length=4)
    photo_url: str | None = None


class RiderUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    pin: str | None = Field(default=None, min_length=4, max_length=12)
    photo_url: str | None = None
    is_active: bool | None = None
    is_online: bool | None = None
    is_available: bool | None = None


class RiderCashIn(BaseModel):
    amount: float = Field(gt=0)
    note: str | None = Field(default=None, max_length=500)


class RiderCashReviewIn(BaseModel):
    status: str
    admin_note: str | None = Field(default=None, max_length=500)


class RiderStatusIn(BaseModel):
    is_online: bool | None = None
    is_available: bool | None = None


class RiderLocationIn(BaseModel):
    latitude: float
    longitude: float


class AssignRiderIn(BaseModel):
    rider_id: int


class DeliveryRuleIn(BaseModel):
    area_note: str | None = None
    base_fee: float = Field(default=0, ge=0)
    free_km: float = Field(default=0, ge=0)
    per_km_fee: float = Field(default=0, ge=0)
    max_delivery_km: float = Field(default=0, ge=0)
    max_fee: float = Field(default=0, ge=0)
    is_enabled: bool = True


class DeliveryQuoteIn(BaseModel):
    latitude: float
    longitude: float
    promo_code: str | None = None
    subtotal: float | None = Field(default=None, ge=0)


class PromoIn(BaseModel):
    promo_code: str
    subtotal: float = Field(ge=0)


class MerchantRiderIn(BaseModel):
    name: str
    phone: str


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    sort_order: int = 0
    is_active: bool = True


class SizeIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    price: float = Field(gt=0)


class ProductIn(BaseModel):
    category_id: int | None = None
    name: str = Field(min_length=1, max_length=180)
    description: str | None = None
    price: float = Field(gt=0)
    image_url: str | None = None
    is_active: bool = True
    sizes: list[SizeIn] = []
    has_extras: bool = False
    is_popular: bool = False
    discount_enabled: bool = False
    discount_type: str = "percentage"
    discount_value: float = Field(default=0, ge=0)


class ExtraIn(BaseModel):
    name: str = Field(min_length=1, max_length=140)
    price: float = Field(default=0, ge=0)
    is_active: bool = True


class OfferIn(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    promo_code: str = Field(min_length=1, max_length=60)
    discount_type: str = "percentage"
    discount_value: float = Field(gt=0)
    minimum_order: float = Field(default=0, ge=0)
    maximum_discount: float = Field(default=0, ge=0)
    first_order_only: bool = False
    usage_limit_per_customer: int = Field(default=0, ge=0)
    is_active: bool = True


class DealRuleIn(BaseModel):
    category_id: int
    quantity: int = Field(default=1, ge=1, le=20)
    label: str | None = None


class DealIn(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    description: str | None = None
    price: float = Field(gt=0)
    image_url: str | None = None
    rules: list[DealRuleIn] = []
    is_active: bool = True


class NotificationIn(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    message: str = Field(min_length=1)
    is_active: bool = True


class FeedbackIn(BaseModel):
    order_id: int | None = None
    rating: int = Field(ge=1, le=5)
    comment: str | None = None


class OrderLineIn(BaseModel):
    product_id: int | None = None
    deal_id: int | None = None
    qty: int = Field(ge=1, le=50)
    size_name: str | None = None
    extra_ids: list[int] = []
    deal_selections: dict[str, Any] | None = None


class OrderCreate(BaseModel):
    customer_name: str | None = None
    customer_phone: str | None = None
    delivery_address: str | None = None
    customer_latitude: float | None = None
    customer_longitude: float | None = None
    payment_method: str = "cash"
    promo_code: str | None = None
    items: list[OrderLineIn]


class OrderStatusIn(BaseModel):
    status: str
