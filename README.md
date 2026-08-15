# Mahi Eats — Multi-Shop Delivery Platform

**Standalone project. It does not use or replace the existing Fai Fai production app, repo, Render service, or database.**

## Included in this ZIP
- **Customer Marketplace (one Mahi Eats app):** all active shops, shop/category search, shop menu, cart, cash checkout, optional customer GPS coordinates, order tracking.
- **Super Admin:** platform stats, create/suspend/open/close shops, create shop admins, set commission/delivery mode, create/disable central Mahi Eats riders, see all platform orders, manual rider assignment/reassignment.
- **Shop Admin (separate per shop):** only its own menu/categories/products/orders/sales, open/close, fees/minimum order/ETA, shop location, delivery mode, Kitchen PIN, own-delivery rider details.
- **Kitchen (separate per shop):** login by shop slug + Kitchen PIN, live active orders, Accept → Preparing → Ready/Cancel. Accepting a Mahi Eats delivery can auto-assign the nearest available central rider.
- **Mahi Eats Rider (central pool):** rider login, online/available status, live browser GPS updates, assigned deliveries from any Mahi Eats shop, Accept → Picked Up → On The Way → Delivered.
- **Customer live tracking:** kitchen status + delivery status + rider name/phone + latest rider GPS coordinates.
- **Two delivery modes:** `Mahi Eats riders` (platform fleet) or `Shop own delivery`.
- **Tenant isolation:** categories/products/orders/settings are scoped by `shop_id`.
- **Database:** PostgreSQL for production; SQLite fallback for local development.
- **Installable PWA basics:** manifest + service worker included.

## Main URLs
- Customer marketplace: `/`
- Shop: `/shop/<shop-slug>`
- Customer tracking: `/track/<order-id>?phone=<customer-phone>`
- Super Admin: `/super-admin`
- Shop Admin: `/shop-admin`
- Kitchen: `/kitchen`
- Central Mahi Eats Rider: `/rider`

## New-order / delivery flow
1. Customer chooses a shop and places an order.
2. The order appears only in that shop's Admin/Kitchen.
3. Kitchen accepts/prepares it.
4. For `mahi_eats` delivery, an online/available central rider is auto-assigned (nearest when shop/rider GPS exists). Super Admin can assign/reassign manually.
5. Kitchen marks Ready.
6. Rider marks Picked Up → On The Way → Delivered.
7. Customer tracking refreshes automatically.

## Local backend
```bash
cd backend
python -m venv .venv
# activate venv
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

## Local frontend
```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

## Production
Use a **new** GitHub repo, **new** Render web service + PostgreSQL database, and **new** Cloudflare Pages project. See `DEPLOY_START_HERE.txt`.
