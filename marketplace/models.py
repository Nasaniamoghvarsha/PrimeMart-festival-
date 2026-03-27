"""
Data Models and Database Interactions for PrimeMart.
This module handles all interactions with MongoDB, including users, 
products, orders, carts, and wishlists.
"""
from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError
from werkzeug.security import check_password_hash
from marketplace.config import Config
from datetime import datetime
from bson import ObjectId
import re

# ---------------------------------------------------------
# Database Connection and Initialization
# ---------------------------------------------------------
try:
    # Configure MongoDB client with connection timeout and server selection timeout
    _client = MongoClient(
        getattr(Config, "MONGO_URI", "mongodb://localhost:27017"),
        serverSelectionTimeoutMS=5000,  # 5 second timeout
        connectTimeoutMS=10000,         # 10 second connection timeout
        socketTimeoutMS=45000,          # 45 second socket timeout
        retryWrites=True,
        w='majority'
    )
    
    # Test the connection
    _client.admin.command('ping')
    print("Successfully connected to MongoDB!")
    
    _db = _client[getattr(Config, "DB_NAME", "marketplace")]  # database
    _users = _db["users"]        # users collection
    _products = _db["products"]  # products collection
    _orders = _db["orders"]      # orders collection
    _carts = _db["carts"]        # each doc: { user_id: str, items: [{product_id: str, qty: int}], updated_at: str }
    _wishlists = _db["wishlists"]  # each doc: { user_id: str, product_ids: [str], updated_at: str }
    _receipts = _db["receipts"]    # each doc: { order_id: ObjectId, user_id: str, total: float, items: list, created_at: datetime }
    
except Exception as e:
    print(f"Error connecting to MongoDB: {e}")
    print("Please make sure MongoDB is running and accessible at the configured URI.")
    print(f"Current MONGO_URI: {getattr(Config, 'MONGO_URI', 'mongodb://localhost:27017')}")
    print(f"Current DB_NAME: {getattr(Config, 'DB_NAME', 'marketplace')}")
    # Re-raise the exception to stop the application
    raise

# ---------- Utilities ----------
def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat()

def _as_object_id(oid):
    """Best-effort convert to ObjectId (if it looks like one), otherwise return original."""
    try:
        return ObjectId(oid)
    except Exception:
        return oid  # retailer_id is likely stored as a string; leave as-is

# Ensure indexes, called from app startup
def init_db():
    # Users
    _users.create_index([("email", ASCENDING)], unique=True)

    # Products
    _products.create_index([("retailer_id", ASCENDING)])
    _products.create_index([("is_active", ASCENDING)])
    _products.create_index([("name", ASCENDING)])  # helpful for sorting/search prefix scans

    # Orders
    _orders.create_index([("retailer_id", ASCENDING)])
    _orders.create_index([("user_id", ASCENDING)])

    # Carts
    _carts.create_index([("user_id", ASCENDING)], unique=True)
    
    # Wishlists
    _wishlists.create_index([("user_id", ASCENDING)], unique=True)
    _wishlists.create_index([("product_ids", ASCENDING)])
    
    # Receipts
    _receipts.create_index([("order_id", ASCENDING)], unique=True)
    _receipts.create_index([("user_id", ASCENDING)])

# ---------- Users ----------
def validate_user(email, password):
    user = _users.find_one({"email": email})
    if not user:
        return None
    if check_password_hash(user.get("password", ""), password):
        return {
            "id": str(user.get("_id")),
            "name": user.get("name", "User"),
            "email": user.get("email"),
            "role": user.get("role", "user"),
        }
    return None

def create_user(name, email, hashed_password, role="user"):
    try:
        _users.insert_one({
            "name": name,
            "email": email,
            "password": hashed_password,
            "role": role if role in ("user", "retailer") else "user",
            "created_at": _utc_now_iso(),
            "updated_at": _utc_now_iso(),
        })
    except DuplicateKeyError as e:
        raise e

# ---------- Products ----------
def create_product(retailer_id, name, description, price, image_url, stock=0):
    """
    Create a new product with the given details.
    
    Args:
        retailer_id: ID of the retailer/owner of the product
        name: Product name
        description: Product description
        price: Product price (will be converted to float)
        image_url: URL of the product image
        stock: Initial stock quantity (default: 0)
    """
    doc = {
        "retailer_id": str(retailer_id),  # Ensure retailer_id is a string
        "name": name.strip(),
        "description": (description or "").strip(),
        "price": float(price),
        "stock": int(stock) if stock is not None else 0,
        "image_url": (image_url or "").strip(),
        "is_active": True,
        "created_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
    }
    res = _products.insert_one(doc)
    return str(res.inserted_id)

def list_products(limit=100, include_inactive=False):
    query = {} if include_inactive else {"is_active": True}
    return list(_products.find(query).limit(limit))

def list_products_by_retailer(retailer_id, include_inactive=False, limit=100):
    query = {"retailer_id": retailer_id}
    if not include_inactive:
        query["is_active"] = True
    return list(_products.find(query).limit(limit))

def search_products(query: str = "", limit: int = 100):
    """
    Case-insensitive search over name/description; returns only active products.
    """
    q = {"is_active": True}
    if query:
        regex = re.compile(re.escape(query), re.IGNORECASE)
        q["$or"] = [{"name": regex}, {"description": regex}]
    return list(_products.find(q).limit(limit))

def get_products_by_ids(ids):
    """
    Fetch active products for a list of string ObjectId values.
    Returns a list of product docs.
    """
    oids = []
    for pid in ids or []:
        try:
            oids.append(ObjectId(pid))
        except Exception:
            pass
    if not oids:
        return []
    cur = _products.find({"_id": {"$in": oids}, "is_active": True})
    return list(cur)

def get_product(product_id):
    """Fetch a product by its id (regardless of retailer). Returns dict or None."""
    pid = _as_object_id(product_id)
    doc = _products.find_one({"_id": pid})
    if not doc:
        return None
    doc["id"] = str(doc["_id"])
    return doc

def get_product_owned(product_id, retailer_id):
    """Fetch a product ensuring it belongs to the given retailer. Returns dict or None."""
    pid = _as_object_id(product_id)
    doc = _products.find_one({"_id": pid, "retailer_id": retailer_id})
    if not doc:
        return None
    doc["id"] = str(doc["_id"])
    return doc

def update_product(product_id, retailer_id, name=None, description=None, price=None, stock=None, image_url=None):
    """
    Retailer-scoped product update.
    Only updates fields provided (non-None). Returns True if a document was modified.
    Validates name and non-negative price/stock when provided.
    """
    pid = _as_object_id(product_id)

    to_set = {"updated_at": _utc_now_iso()}

    if name is not None:
        if not str(name).strip():
            return False
        to_set["name"] = str(name).strip()

    if description is not None:
        to_set["description"] = str(description)

    if price is not None:
        try:
            price_val = float(price)
        except Exception:
            return False
        if price_val < 0:
            return False
        to_set["price"] = price_val

    # Optional stock
    if stock is not None:
        try:
            stock_val = int(stock)
        except Exception:
            return False
        if stock_val < 0:
            return False
        to_set["stock"] = stock_val

    if image_url is not None:
        to_set["image_url"] = str(image_url)

    res = _products.update_one(
        {"_id": pid, "retailer_id": retailer_id, "is_active": True},
        {"$set": to_set}
    )
    return res.modified_count == 1

def delete_product(product_id, retailer_id, soft=True):
    """
    Retailer-scoped delete. By default performs a soft delete (sets is_active=False).
    Set soft=False to hard delete the document.
    Returns True if a document was modified/deleted.
    """
    pid = _as_object_id(product_id)

    if soft:
        res = _products.update_one(
            {"_id": pid, "retailer_id": retailer_id, "is_active": True},
            {"$set": {"is_active": False, "updated_at": _utc_now_iso()}}
        )
        return res.modified_count == 1
    else:
        res = _products.delete_one({"_id": pid, "retailer_id": retailer_id})
        return res.deleted_count == 1

# ---------- Orders ----------
def create_order(user_id, retailer_id, product_id, quantity, price):
    """
    Create a new order with the given product and quantity.
    Returns the order ID if successful, None otherwise.
    """
    try:
        # First, get the product to include its details in the order
        product = _products.find_one({"_id": ObjectId(product_id)})
        if not product:
            return None
            
        # Create the order document
        order = {
            "user_id": user_id,
            "retailer_id": retailer_id,
            "status": "processing",
            "total": float(price) * quantity,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "items": [{
                "product_id": str(product["_id"]),
                "name": product.get("name", "Unknown Product"),
                "price": float(price),
                "qty": quantity,
                "image_url": product.get("image_url")
            }]
        }
        
        result = _orders.insert_one(order)
        return str(result.inserted_id)
    except Exception as e:
        print(f"Error creating order: {e}")
        return None

def list_orders_for_retailer(retailer_id):
    """List all orders for a specific retailer, sorted by creation date (newest first)."""
    return list(_orders.find({"retailer_id": retailer_id}).sort("created_at", -1))

def get_user_orders(user_id, limit=50):
    """
    Get all orders for a specific user, sorted by creation date (newest first).
    Returns a list of order documents.
    """
    try:
        return list(_orders.find({"user_id": user_id})
                         .sort("created_at", -1)
                         .limit(limit))
    except Exception as e:
        print(f"Error fetching user orders: {e}")
        return []

# ---------- Cart ----------
def _ensure_cart(user_id: str):
    cart = _carts.find_one({"user_id": user_id})
    if not cart:
        _carts.insert_one({"user_id": user_id, "items": [], "updated_at": _utc_now_iso()})
        cart = _carts.find_one({"user_id": user_id})
    return cart

def get_cart(user_id: str):
    return _ensure_cart(user_id)

def add_to_cart(user_id: str, product_id: str, qty: int = 1):
    """Upsert item (increment qty). Returns True on success."""
    # Normalize qty
    if qty <= 0:
        qty = 1

    # Ensure the cart exists
    _ensure_cart(user_id)

    # Check product exists, is active and has sufficient stock
    pid = _as_object_id(product_id)
    product = _products.find_one({"_id": pid, "is_active": True})
    if not product:
        # Product missing or inactive
        return False

    available = int(product.get("stock", 0))

    # Get current qty in cart for this product (best-effort)
    cart = _carts.find_one({"user_id": user_id})
    current_qty = 0
    if cart:
        for it in cart.get("items", []):
            if it.get("product_id") == product_id:
                try:
                    current_qty = int(it.get("qty", 0))
                except Exception:
                    current_qty = 0
                break

    if available <= 0 or current_qty + qty > available:
        # Not enough stock to satisfy request
        return False

    # Safe to add/increment
    res = _carts.update_one(
        {"user_id": user_id, "items.product_id": product_id},
        {"$inc": {"items.$.qty": qty}, "$set": {"updated_at": _utc_now_iso()}}
    )
    if res.matched_count == 0:
        _carts.update_one(
            {"user_id": user_id},
            {"$push": {"items": {"product_id": product_id, "qty": qty}},
             "$set": {"updated_at": _utc_now_iso()}}
        )
    return True

def update_cart_item(user_id: str, product_id: str, qty: int):
    """Set quantity; if qty <= 0, remove the item."""
    _ensure_cart(user_id)
    if qty <= 0:
        return remove_from_cart(user_id, product_id)
    # Check product availability and stock
    pid = _as_object_id(product_id)
    product = _products.find_one({"_id": pid, "is_active": True})
    if not product:
        return False

    available = int(product.get("stock", 0))
    if qty > available:
        # Do not allow setting qty greater than available stock
        return False

    res = _carts.update_one(
        {"user_id": user_id, "items.product_id": product_id},
        {"$set": {"items.$.qty": qty, "updated_at": _utc_now_iso()}}
    )
    return res.modified_count == 1

def remove_from_cart(user_id: str, product_id: str):
    res = _carts.update_one(
        {"user_id": user_id},
        {"$pull": {"items": {"product_id": product_id}}, "$set": {"updated_at": _utc_now_iso()}}
    )
    return res.modified_count == 1

def clear_cart(user_id: str):
    """Remove all items from the user's cart."""
    result = _carts.update_one(
        {"user_id": user_id},
        {"$set": {"items": [], "updated_at": _utc_now_iso()}},
        upsert=True
    )
    return result.modified_count > 0

def add_to_wishlist(user_id: str, product_id: str) -> bool:
    """Add a product to user's wishlist. Returns True if added, False if already exists."""
    result = _wishlists.update_one(
        {"user_id": user_id},
        {
            "$addToSet": {"product_ids": product_id},
            "$setOnInsert": {"created_at": _utc_now_iso()},
            "$set": {"updated_at": _utc_now_iso()}
        },
        upsert=True
    )
    return result.upserted_id is not None or result.modified_count > 0

def remove_from_wishlist(user_id: str, product_id: str) -> bool:
    """Remove a product from user's wishlist. Returns True if removed, False if not found."""
    result = _wishlists.update_one(
        {"user_id": user_id},
        {
            "$pull": {"product_ids": product_id},
            "$set": {"updated_at": _utc_now_iso()}
        }
    )
    return result.modified_count > 0

def get_wishlist(user_id: str) -> list:
    """Get list of product IDs in user's wishlist."""
    wishlist = _wishlists.find_one({"user_id": user_id})
    return wishlist["product_ids"] if wishlist else []

def is_in_wishlist(user_id: str, product_id: str) -> bool:
    """Check if a product is in user's wishlist."""
    return _wishlists.count_documents({
        "user_id": user_id,
        "product_ids": product_id
    }) > 0

def update_user_budget(user_id: str, budget: float):
    """Update or set the user's budget.

    This function is lenient about the format of `user_id`:
    - If it's a valid ObjectId string, update the document with that _id.
    - Otherwise, attempt to update by a string `id` field or by matching a string _id.

    Returns True when an update was applied (matched_count > 0) or False otherwise.
    """
    try:
        uid = ObjectId(user_id)
        res = _users.update_one(
            {"_id": uid},
            {"$set": {"budget": float(budget) if budget is not None else None}}
        )
        if res.matched_count:
            return True
    except Exception:
        # not an ObjectId or failed conversion
        pass

    # Try fallback: match on a string _id (in case some users were stored that way)
    try:
        res = _users.update_one(
            {"_id": user_id},
            {"$set": {"budget": float(budget) if budget is not None else None}}
        )
        if res.matched_count:
            return True
    except Exception:
        pass

    # Try matching an 'id' field if user documents store user IDs there
    try:
        res = _users.update_one(
            {"id": user_id},
            {"$set": {"budget": float(budget) if budget is not None else None}}
        )
        return res.matched_count > 0
    except Exception:
        return False

def get_user_budget(user_id: str) -> float:
    """Get the user's budget."""
    try:
        user = _users.find_one({"_id": ObjectId(user_id)}, {"budget": 1})
        if user:
            return user.get('budget')
    except Exception:
        pass

    # Fallbacks: try string _id or id field
    user = _users.find_one({"_id": user_id}, {"budget": 1})
    if user and 'budget' in user:
        return user.get('budget')

    user = _users.find_one({"id": user_id}, {"budget": 1})
    return user.get('budget') if user else None