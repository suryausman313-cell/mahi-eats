from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    email: str
    password: str


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


class ShopSettingsIn(BaseModel):
    is_open: bool | None = None
    delivery_mode: str | None = None
    delivery_fee: float | None = None
    min_order: float | None = None
    estimated_minutes: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    address: str | None = None


class KitchenPinIn(BaseModel):
    pin: str = Field(min_length=4, max_length=12)


class AdminCreate(BaseModel):
    name: str = "Shop Admin"
    email: str
    password: str = Field(min_length=6)


class RiderCreate(BaseModel):
    name: str
    email: str
    phone: str
    password: str = Field(min_length=6)
    photo_url: str | None = None


class RiderUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    photo_url: str | None = None
    is_active: bool | None = None
    is_online: bool | None = None
    is_available: bool | None = None


class RiderStatusIn(BaseModel):
    is_online: bool | None = None
    is_available: bool | None = None


class RiderLocationIn(BaseModel):
    latitude: float
    longitude: float


class AssignRiderIn(BaseModel):
    rider_id: int


class MerchantRiderIn(BaseModel):
    name: str
    phone: str


class CategoryIn(BaseModel):
    name: str
    sort_order: int = 0
    is_active: bool = True


class ProductIn(BaseModel):
    category_id: int | None = None
    name: str
    description: str | None = None
    price: float = Field(gt=0)
    image_url: str | None = None
    is_active: bool = True


class OrderLineIn(BaseModel):
    product_id: int
    qty: int = Field(ge=1, le=50)


class OrderCreate(BaseModel):
    customer_name: str
    customer_phone: str
    delivery_address: str | None = None
    customer_latitude: float | None = None
    customer_longitude: float | None = None
    payment_method: str = "cash"
    items: list[OrderLineIn]


class OrderStatusIn(BaseModel):
    status: str
