from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, json, send_file, make_response
from datetime import datetime, timedelta
from bson.objectid import ObjectId
import os
from io import BytesIO
from bson import ObjectId as BsonObjectId
from ..pdf_utils import get_receipt_as_bytes

from marketplace.models import (
    # Store / search
    list_products,
    search_products,            # NEW
    # Orders / products
    create_order,
    create_product,
    list_products_by_retailer,
    list_orders_for_retailer,
    get_product_owned,
    update_product,
    delete_product,
    # Cart helpers (NEW)
    get_cart,
    add_to_cart,
    remove_from_cart,
    update_cart_item,
    get_products_by_ids,
    update_user_budget,
    # Wishlist
    add_to_wishlist,
    remove_from_wishlist,
    get_wishlist,
    is_in_wishlist,
    # Internal helpers (used in some debug/admin flows)
    _products,
    _utc_now_iso,
)

product_bp = Blueprint("product_bp", __name__, template_folder="../templates")


# ---------- User Store (with search) ----------
@product_bp.route("/store")
def store():
    q = (request.args.get("q") or "").strip()
    products = search_products(q, limit=200) if q else list_products(limit=200)
    # Convert ObjectIds to strings for templates
    for p in products:
        p["_id"] = str(p.get("_id"))
    # Get wishlist status for each product if user is logged in
    wishlist_status = {}
    if "user" in session and session["user"].get("role") == "user":
        user_id = session["user"]["id"]
        for p in products:
            wishlist_status[str(p["_id"])] = is_in_wishlist(user_id, str(p["_id"]))
    
    return render_template(
        "store.html", 
        products=products, 
        q=q,
        wishlist_status=wishlist_status
    )


@product_bp.route("/store/buy/<product_id>", methods=["POST"])
def buy_product(product_id):
    if "user" not in session:
        flash("Please login to buy products.", "warning")
        return redirect(url_for("auth_bp.login"))
    user = session.get("user")
    if user.get("role") != "user":
        flash("Only shoppers can buy products.", "danger")
        return redirect(url_for("product_bp.store"))

    try:
        retailer_id = request.form.get("retailer_id")
        create_order(user_id=user.get("id"), retailer_id=retailer_id, product_id=product_id)
        flash("Order placed! The retailer has been notified to prepare for pickup.", "success")
    except Exception as e:
        print("DEBUG: buy_product error:", e)
        flash("Could not place order. Please try again.", "danger")
    return redirect(url_for("product_bp.store"))


# ---------- Cart ----------
@product_bp.route("/cart")
def cart_view():
    if "user" not in session or session["user"].get("role") != "user":
        flash("Please login as a shopper to view your cart.", "warning")
        return redirect(url_for("auth_bp.login"))

    uid = session["user"].get("id") or session["user"].get("_id")
    if not uid:
        flash("Invalid user session. Please login again.", "error")
        return redirect(url_for("auth_bp.login"))
        
    print(f"DEBUG: Cart view - User ID: {uid}, Type: {type(uid)}")
    
    # Get cart directly from database
    from pymongo import MongoClient
    from bson import ObjectId
    
    client = MongoClient('mongodb://localhost:27017')
    db = client['marketplace']
    
    # Try to find the cart with the user_id as string
    cart = db.carts.find_one({'user_id': uid})
    print(f"DEBUG: Cart from database (string user_id): {cart}")
    
    # If not found, try with ObjectId
    if not cart and ObjectId.is_valid(uid):
        cart = db.carts.find_one({'user_id': ObjectId(uid)})
        print(f"DEBUG: Cart from database (ObjectId user_id): {cart}")
    
    # Ensure cart has the right structure
    if not cart or not isinstance(cart, dict):
        cart = {"items": []}
    if "items" not in cart:
        cart["items"] = []
    
    print(f"DEBUG: Cart items: {cart.get('items')}")
    
    # Get product details for items in cart
    ids = [it.get("product_id") for it in cart.get("items", [])]
    print(f"DEBUG: Product IDs in cart: {ids}")
    
    products = get_products_by_ids(ids)
    pmap = {str(p["_id"]): p for p in products}
    print(f"DEBUG: Found {len(products)} products in database")

    enriched = []
    total = 0.0
    for it in cart.get("items", []):
        pid = it.get("product_id")
        qty = int(it.get("qty", 1))
        prod = pmap.get(pid)
        if not prod:
            # product might be inactive/soft-deleted; skip it
            continue
        price = float(prod.get("price", 0.0))
        line_total = price * qty
        total += line_total
        enriched.append({
            "product_id": pid,
            "name": prod.get("name"),
            "price": price,
            "qty": qty,
            "image_url": prod.get("image_url"),
            "line_total": line_total
        })

    # Get user's budget if set
    budget = None
    if "user" in session:
        from marketplace.models import get_user_budget
        budget = get_user_budget(session["user"]["id"])
    
    return render_template("cart.html", items=enriched, total=total, budget=budget)


@product_bp.route("/cart/add", methods=["POST"])
def cart_add():
    if "user" not in session or session["user"].get("role") != "user":
        flash("Please login as a shopper to add to cart.", "warning")
        return redirect(url_for("auth_bp.login"))

    uid = session["user"]["id"]
    product_id = (request.form.get("product_id") or "").strip()
    qty_raw = request.form.get("qty") or "1"
    try:
        qty = max(1, int(qty_raw))
    except Exception:
        qty = 1

    if not product_id:
        flash("Invalid product.", "danger")
        return redirect(url_for("product_bp.store"))
    success = add_to_cart(uid, product_id, qty)
    if not success:
        # Determine reason: check product status/stock
        from marketplace.models import get_product
        prod = get_product(product_id)
        if not prod or not prod.get("is_active", True):
            flash("This product is no longer available.", "warning")
        else:
            stock = prod.get("stock", 0)
            if int(stock) <= 0:
                flash("This product is out of stock.", "warning")
            else:
                flash(f"Cannot add requested quantity. Only {stock} left in stock.", "warning")
        return redirect(request.referrer or url_for("product_bp.store"))

    flash("Added to cart.", "success")
    return redirect(request.referrer or url_for("product_bp.store"))


@product_bp.route("/cart/remove", methods=["POST"])
def cart_remove():
    if "user" not in session or session["user"].get("role") != "user":
        flash("Please login as a shopper to modify your cart.", "warning")
        return redirect(url_for("auth_bp.login"))

    uid = session["user"]["id"]
    product_id = (request.form.get("product_id") or "").strip()
    if not product_id:
        flash("Invalid product.", "danger")
        return redirect(url_for("product_bp.cart_view"))

    remove_from_cart(uid, product_id)
    flash("Removed from cart.", "success")
    return redirect(url_for("product_bp.cart_view"))


@product_bp.route("/cart/update", methods=["POST"])
def cart_update():
    if "user" not in session or session["user"].get("role") != "user":
        flash("Please login as a shopper to modify your cart.", "warning")
        return redirect(url_for("auth_bp.login"))

    uid = session["user"]["id"]
    product_id = (request.form.get("product_id") or "").strip()
    qty_raw = request.form.get("qty") or "1"
    try:
        qty = int(qty_raw)
    except Exception:
        qty = 1

    if not product_id:
        flash("Invalid product.", "danger")
        return redirect(url_for("product_bp.cart_view"))
    success = update_cart_item(uid, product_id, qty)
    if not success:
        # Determine the cause and flash message
        from marketplace.models import get_product
        prod = get_product(product_id)
        if not prod or not prod.get("is_active", True):
            flash("This product is no longer available and was not updated in your cart.", "warning")
        else:
            stock = prod.get("stock", 0)
            if int(stock) <= 0:
                flash("This product is out of stock and was not updated in your cart.", "warning")
            else:
                flash(f"Cannot set quantity to {qty}. Only {stock} available.", "warning")
        return redirect(url_for("product_bp.cart_view"))

    flash("Cart updated.", "success")
    return redirect(url_for("product_bp.cart_view"))


@product_bp.route("/set_budget", methods=["POST"])
def set_budget():
    """Set a spending budget for the current user and report whether
    the user's current cart already exceeds that budget.
    Returns JSON: {status: 'success'|'budget_exceeded'|'error', ...}
    """
    if "user" not in session or session["user"].get("role") != "user":
        return jsonify({"status": "error", "message": "Please login as a shopper."}), 401

    # Accept either form-encoded or JSON body
    budget_raw = None
    if request.form and request.form.get("budget") is not None:
        budget_raw = request.form.get("budget")
    else:
        try:
            budget_raw = (request.get_json(silent=True) or {}).get("budget")
        except Exception:
            budget_raw = None

    try:
        budget = float(budget_raw)
        if budget < 0:
            raise ValueError("negative")
    except Exception:
        return jsonify({"status": "error", "message": "Invalid budget value."}), 400

    uid = session["user"].get("id")

    try:
        # Compute current cart total
        cart = get_cart(uid) or {"items": []}
        ids = [it.get("product_id") for it in cart.get("items", [])]
        products = get_products_by_ids(ids)
        pmap = {str(p.get("_id")): p for p in products}

        cart_total = 0.0
        for it in cart.get("items", []):
            pid = it.get("product_id")
            qty = int(it.get("qty", 1))
            prod = pmap.get(pid)
            if not prod:
                continue
            cart_total += float(prod.get("price", 0.0)) * qty

        # Persist the user's budget (ensure it succeeded)
        success = update_user_budget(uid, budget)
        if not success:
            return jsonify({"status": "error", "message": "Could not persist budget for this user."}), 500

        if cart_total > budget:
            exceed = round(cart_total - budget, 2)
            return jsonify({
                "status": "budget_exceeded",
                "message": "Your cart total exceeds the set budget.",
                "cart_total": cart_total,
                "budget": budget,
                "exceed_amount": exceed
            })

        return jsonify({"status": "success", "message": "Budget updated.", "cart_total": cart_total, "budget": budget})
    except Exception as e:
        print("Error in set_budget:", e)
        return jsonify({"status": "error", "message": "Could not set budget."}), 500


# ---------- Wishlist ----------
@product_bp.route("/wishlist")
def view_wishlist():
    if "user" not in session or session["user"].get("role") != "user":
        flash("Please login to view your wishlist.", "warning")
        return redirect(url_for("auth_bp.login"))
    
    user_id = session["user"]["id"]
    product_ids = get_wishlist(user_id)
    
    if not product_ids:
        return render_template("wishlist.html", products=[], wishlist_status={})
    
    # Get full product details for items in wishlist
    products = list(_products.find({"_id": {"$in": [ObjectId(pid) for pid in product_ids]}}))
    
    # Convert ObjectIds to strings for the template
    for p in products:
        p["_id"] = str(p.get("_id"))
    
    # Mark all as in wishlist
    wishlist_status = {pid: True for pid in product_ids}
    
    return render_template(
        "wishlist.html",
        products=products,
        wishlist_status=wishlist_status
    )


@product_bp.route("/wishlist/toggle/<product_id>", methods=["POST"])
def toggle_wishlist(product_id):
    if "user" not in session or session["user"].get("role") != "user":
        return jsonify({"status": "error", "message": "Please login to manage your wishlist."}), 401
    
    user_id = session["user"]["id"]
    action = request.json.get("action")
    
    try:
        if action == "add":
            added = add_to_wishlist(user_id, product_id)
            if added:
                return jsonify({"status": "success", "message": "Added to wishlist"})
            return jsonify({"status": "info", "message": "Already in wishlist"})
        elif action == "remove":
            removed = remove_from_wishlist(user_id, product_id)
            if removed:
                return jsonify({"status": "success", "message": "Removed from wishlist"})
            return jsonify({"status": "info", "message": "Not in wishlist"})
        else:
            return jsonify({"status": "error", "message": "Invalid action"}), 400
    except Exception as e:
        print(f"Error in wishlist toggle: {str(e)}")
        return jsonify({"status": "error", "message": "An error occurred"}), 500


# ---------- Retailer Dashboard ----------
def get_sales_data(orders, period='week'):
    """Generate sales data for the given time period"""
    now = datetime.utcnow()
    sales_data = {}
    
    if period == 'week':
        # Last 7 days
        for i in range(7, -1, -1):
            date = (now - timedelta(days=i)).strftime('%a')
            sales_data[date] = 0
    elif period == 'month':
        # Last 30 days, grouped by week
        for i in range(4, 0, -1):
            week_start = (now - timedelta(weeks=i, days=now.weekday())).strftime('%b %d')
            week_end = (now - timedelta(weeks=i-1, days=now.weekday()+1)).strftime('%b %d')
            sales_data[f"{week_start} - {week_end}"] = 0
    else:  # year
        # Last 12 months in chronological order
        current_month = now.month
        current_year = now.year
        
        # Create a list to store months in order
        months = []
        for i in range(11, -1, -1):
            # Calculate month and year for each of the last 12 months
            month = (current_month - 1 - i) % 12 + 1
            year = current_year + (current_month - 1 - i) // 12
            month_name = datetime(year, month, 1).strftime('%b')
            months.append(month_name)
        
        # Initialize sales data with 0 for each month
        for month in months:
            sales_data[month] = 0
    
    # Count orders in each period
    for order in orders:
        try:
            order_date = datetime.fromisoformat(order.get('created_at', '')) if isinstance(order.get('created_at'), str) else order.get('created_at', now)
            order_value = float(order.get('total', 0))
            
            if period == 'week':
                days_ago = (now - order_date).days
                if 0 <= days_ago <= 7:
                    date_key = order_date.strftime('%a')
                    sales_data[date_key] = sales_data.get(date_key, 0) + order_value
            elif period == 'month':
                weeks_ago = (now - order_date).days // 7
                if 0 <= weeks_ago <= 4:
                    week_start = (now - timedelta(weeks=weeks_ago, days=now.weekday())).strftime('%b %d')
                    week_end = (now - timedelta(weeks=weeks_ago-1, days=now.weekday()+1)).strftime('%b %d')
                    date_key = f"{week_start} - {week_end}"
                    sales_data[date_key] = sales_data.get(date_key, 0) + order_value
            else:  # year
                # Get the month name for the order date
                month_key = order_date.strftime('%b')
                # Only add to sales if this month is in our current year view
                if month_key in sales_data:
                    sales_data[month_key] += order_value
        except (ValueError, TypeError):
            continue
    
    return {
        'labels': list(sales_data.keys()),
        'data': list(sales_data.values())
    }

@product_bp.route("/api/sales-data")
def sales_data():
    if "user" not in session or session["user"].get("role") != "retailer":
        return jsonify({"error": "Unauthorized"}), 401
    
    retailer_id = session["user"].get("retailer_id", session["user"].get("id"))
    period = request.args.get('period', 'week')
    orders = list_orders_for_retailer(retailer_id)
    
    return jsonify(get_sales_data(orders, period))

@product_bp.route("/retailer", methods=["GET"])
def retailer_dashboard():
    if "user" not in session:
        flash("Please login as a retailer.", "warning")
        return redirect(url_for("auth_bp.login"))
    
    user = session.get("user")
    if user.get("role") != "retailer":
        flash("Access restricted to retailers.", "danger")
        return redirect(url_for("product_bp.store"))

    retailer_id = user.get("retailer_id", user.get("id"))
    
    # Get retailer's products
    products = list_products_by_retailer(retailer_id)
    for p in products:
        p["_id"] = str(p.get("_id"))
    
    # Get retailer's orders
    orders = list_orders_for_retailer(retailer_id)
    for o in orders:
        o["_id"] = str(o.get("_id"))
    
    # Calculate statistics
    total_sales = len(orders)
    total_revenue = sum(float(order.get("total", 0)) for order in orders if order.get("total"))
    total_products = len(products)
    
    # Count new products (added in last 30 days)
    new_products = 0
    for p in products:
        if p.get("created_at"):
            try:
                created_at = datetime.fromisoformat(p["created_at"])
                if (datetime.utcnow() - created_at).days <= 30:
                    new_products += 1
            except (ValueError, TypeError):
                continue
    
    # Prepare stats dictionary
    stats = {
        "total_sales": total_sales,
        "revenue": f"${total_revenue:,.2f}",
        "total_products": total_products,
        "new_products": new_products,
        "conversion_rate": f"{min(100, int((total_sales / max(1, total_products)) * 100))}%"
    }
    
    # Get recent orders (last 5)
    def get_order_date(order):
        created_at = order.get("created_at", "")
        if isinstance(created_at, str):
            try:
                return datetime.fromisoformat(created_at)
            except (ValueError, TypeError):
                return datetime.min
        return created_at
    
    recent_orders = sorted(orders, key=get_order_date, reverse=True)[:5]
    
    # Get top products (by price as a proxy for revenue since we don't track sales count)
    def get_product_price(product):
        try:
            return float(product.get("price", 0))
        except (ValueError, TypeError):
            return 0.0
    
    top_products = sorted(products, key=get_product_price, reverse=True)[:4]
    
    # Get initial sales data for the chart
    sales_data = get_sales_data(orders, 'week')
    
    return render_template(
        "retailer_dashboard.html",
        products=products,
        orders=orders,
        stats=stats,
        recent_orders=recent_orders,
        top_products=top_products,
        initial_sales_data=json.dumps(sales_data)
    )


@product_bp.route("/retailer/products/new")
def new_product():
    """Display the form to add a new product."""
    if "user" not in session or session.get("user", {}).get("role") != "retailer":
        flash("Please login as a retailer.", "warning")
        return redirect(url_for("auth_bp.login"))
    return render_template("add_product.html")

@product_bp.route("/retailer/products/add", methods=["POST"])
def add_product():
    """Handle the submission of a new product."""
    if "user" not in session:
        flash("Please login as a retailer.", "warning")
        return redirect(url_for("auth_bp.login"))
        
    user = session.get("user")
    if user.get("role") != "retailer":
        flash("Access restricted to retailers.", "danger")
        return redirect(url_for("product_bp.store"))

    # Get form data with proper defaults and validation
    name = (request.form.get("name") or "").strip()
    description = (request.form.get("description") or "").strip()
    price_str = (request.form.get("price") or "0").strip()
    stock_str = (request.form.get("stock") or "0").strip()
    image_url = (request.form.get("image_url") or "").strip()

    # Validate required fields
    if not name:
        flash("Product name is required.", "danger")
        return redirect(url_for("product_bp.new_product"))
        
    try:
        price = float(price_str)
        if price < 0:
            raise ValueError("Price cannot be negative")
    except ValueError:
        flash("Please enter a valid price.", "danger")
        return redirect(url_for("product_bp.new_product"))
        
    try:
        stock = int(stock_str) if stock_str.isdigit() else 0
        if stock < 0:
            raise ValueError("Stock cannot be negative")
    except ValueError:
        flash("Please enter a valid stock quantity.", "danger")
        return redirect(url_for("product_bp.new_product"))

    try:
        # Create the product
        product_id = create_product(
            retailer_id=user.get("retailer_id", user.get("id")),
            name=name,
            description=description,
            price=price,
            image_url=image_url,
            stock=stock
        )
        
        if not product_id:
            raise Exception("Failed to create product")
            
        flash("Product added successfully!", "success")
        return redirect(url_for("product_bp.retailer_dashboard"))
        
    except Exception as e:
        print(f"Error adding product: {str(e)}")
        flash(f"Could not add product: {str(e)}", "danger")
    return redirect(url_for("product_bp.retailer_dashboard"))


@product_bp.route("/retailer/products/<product_id>/edit", methods=["GET", "POST"])
def edit_product(product_id):
    """Edit an existing product."""
    if "user" not in session:
        flash("Please login as a retailer.", "warning")
        return redirect(url_for("auth_bp.login"))
        
    user = session.get("user")
    if user.get("role") != "retailer":
        flash("Access restricted to retailers.", "danger")
        return redirect(url_for("product_bp.store"))

    # Get the product, ensuring it belongs to the current retailer
    retailer_id = user.get("retailer_id", user.get("id"))
    product = get_product_owned(product_id, retailer_id)
    
    if not product:
        flash("Product not found or access denied.", "danger")
        return redirect(url_for("product_bp.retailer_dashboard"))

    if request.method == "POST":
        # Handle form submission
        name = (request.form.get("name") or "").strip()
        description = (request.form.get("description") or "").strip()
        price_str = (request.form.get("price") or "0").strip()
        stock_str = (request.form.get("stock") or "0").strip()
        image_url = (request.form.get("image_url") or "").strip()
        is_active = request.form.get("is_active") == "on"

        # Validate input
        if not name:
            flash("Product name is required.", "danger")
            return render_template("edit_product.html", product=product)
            
        try:
            price = float(price_str)
            if price < 0:
                raise ValueError("Price cannot be negative")
        except ValueError:
            flash("Please enter a valid price.", "danger")
            return render_template("edit_product.html", product=product)
            
        try:
            stock = int(stock_str) if stock_str.isdigit() else 0
            if stock < 0:
                raise ValueError("Stock cannot be negative")
        except ValueError:
            flash("Please enter a valid stock quantity.", "danger")
            return render_template("edit_product.html", product=product)

        # Update the product
        try:
            updated = update_product(
                product_id=product_id,
                retailer_id=retailer_id,
                name=name,
                description=description,
                price=price,
                stock=stock,
                image_url=image_url
            )
            
            if not updated:
                raise Exception("Failed to update product")
                
            # Handle active status separately as it might be a different operation
            if product.get("is_active") != is_active:
                if is_active:
                    # Reactivate product
                    _products.update_one(
                        {"_id": ObjectId(product_id), "retailer_id": retailer_id},
                        {"$set": {"is_active": True, "updated_at": _utc_now_iso()}}
                    )
                else:
                    # Deactivate product (soft delete)
                    _products.update_one(
                        {"_id": ObjectId(product_id), "retailer_id": retailer_id},
                        {"$set": {"is_active": False, "updated_at": _utc_now_iso()}}
                    )
            
            flash("Product updated successfully!", "success")
            return redirect(url_for("product_bp.retailer_dashboard"))
            
        except Exception as e:
            print(f"Error updating product: {str(e)}")
            flash(f"Could not update product: {str(e)}", "danger")
            return render_template("edit_product.html", product=product)

    # For GET request, show the edit form
    return render_template("edit_product.html", product=product)


@product_bp.route("/retailer/products/<product_id>/update", methods=["POST"])
def update_product_action(product_id):
    if "user" not in session:
        flash("Please login as a retailer.", "warning")
        return redirect(url_for("auth_bp.login"))
    user = session.get("user")
    if user.get("role") != "retailer":
        flash("Access restricted to retailers.", "danger")
        return redirect(url_for("product_bp.store"))

    retailer_id = user.get("retailer_id", user.get("id"))

    name = (request.form.get("name") or "").strip()
    description = (request.form.get("description") or "").strip()
    price_raw = request.form.get("price")
    stock_raw = request.form.get("stock")  # optional
    image_url = (request.form.get("image_url") or "").strip()

    # Convert optional numerics safely
    price = None
    stock = None
    if price_raw is not None and price_raw != "":
        try:
            price = float(price_raw)
        except Exception:
            flash("Invalid price value.", "warning")
            return redirect(url_for("product_bp.edit_product", product_id=product_id))
    if stock_raw is not None and stock_raw != "":
        try:
            stock = int(stock_raw)
        except Exception:
            flash("Invalid stock value.", "warning")
            return redirect(url_for("product_bp.edit_product", product_id=product_id))

    # Server-side validation
    if name == "":
        flash("Product name cannot be empty.", "warning")
        return redirect(url_for("product_bp.edit_product", product_id=product_id))
    if price is not None and price < 0:
        flash("Price cannot be negative.", "warning")
        return redirect(url_for("product_bp.edit_product", product_id=product_id))
    if stock is not None and stock < 0:
        flash("Stock cannot be negative.", "warning")
        return redirect(url_for("product_bp.edit_product", product_id=product_id))

    ok = update_product(
        product_id=product_id,
        retailer_id=retailer_id,
        name=name,
        description=description,
        price=price,
        stock=stock,
        image_url=image_url if image_url else None,
    )

    if ok:
        flash("Product updated.", "success")
    else:
        flash("Update failed (not found, not owned, or invalid input).", "danger")
    return redirect(url_for("product_bp.retailer_dashboard"))


@product_bp.route("/retailer/products/<product_id>/delete", methods=["POST"])
def delete_product_action(product_id):
    if "user" not in session or session["user"].get("role") != "retailer":
        flash("Unauthorized.", "danger")
        return redirect(url_for("auth_bp.login"))

    from marketplace.models import delete_product
    try:
        success = delete_product(product_id, retailer_id=session["user"]["id"])
        if success:
            flash("Product deleted.", "success")
        else:
            flash("Could not delete product. It may have already been removed.", "warning")
    except Exception as e:
        print("DEBUG: delete_product_action error:", e)
        flash("Could not delete product.", "danger")

    return redirect(url_for("product_bp.retailer_dashboard"))


def update_budget(user_id, budget):
    """Helper function to update user budget"""
    # Handle clear budget case
    if budget is None or (isinstance(budget, str) and (budget.strip() == "" or budget.lower() == "clear")):
        from marketplace.models import update_user_budget
        update_user_budget(user_id, None)
        return jsonify({
            "status": "success", 
            "budget": None,
            "message": "Budget cleared successfully"
        })
        
    # Handle set budget case
    try:
        budget_value = float(budget)
        from marketplace.models import update_user_budget
        update_user_budget(user_id, budget_value)
        return jsonify({
            "status": "success",
            "budget": budget_value,
            "message": "Budget updated successfully"
        })
    except (ValueError, TypeError):
        return jsonify({
            "status": "error",
            "message": "Invalid budget amount. Please enter a valid number."
        }), 400
        
        # Handle set to 0 case (unlimited budget)
        if budget_value == 0:
            from marketplace.models import update_user_budget
            update_user_budget(user_id, 0)
            return jsonify({
                "status": "success", 
                "budget": 0,
                "message": "Budget set to unlimited"
            })
            
        if budget_value < 0:
            return jsonify({"status": "error", "message": "Budget cannot be negative"}), 400
            
        # Get current cart and calculate total
        cart = get_cart(user_id)
        cart_items = cart.get("items", [])
        
        if cart_items:
            # Get all product details at once
            from marketplace.models import get_products_by_ids
            product_ids = [item["product_id"] for item in cart_items]
            products = {str(p["_id"]): p for p in get_products_by_ids(product_ids) if p}
            
            # Calculate current total and check against new budget
            current_total = 0
            items_to_remove = []
            
            for item in cart_items:
                pid = item["product_id"]
                product = products.get(pid)
                if product:
                    current_total += float(product.get("price", 0)) * item.get("qty", 1)
            
            # If current total exceeds new budget, suggest items to remove
            if current_total > budget_value:
                # Sort items by price (highest first) to suggest most expensive items first
                sorted_items = sorted(
                    [it for it in cart_items if products.get(it["product_id"])],
                    key=lambda x: float(products[x["product_id"]].get("price", 0)),
                    reverse=True
                )
                
                # Calculate how much we need to reduce the total by
                reduction_needed = current_total - budget_value
                suggestions = []
                running_total = 0
                
                # Find the minimum set of items that would bring the total under budget
                for item in sorted_items:
                    if running_total >= reduction_needed:
                        break
                        
                    product = products[item["product_id"]]
                    item_price = float(product.get("price", 0)) * item.get("qty", 1)
                    
                    suggestions.append({
                        "product_id": item["product_id"],
                        "name": product.get("name"),
                        "price": float(product.get("price", 0)),
                        "qty": item.get("qty", 1),
                        "total_price": item_price
                    })
                    
                    running_total += item_price
                
                # Calculate how much more needs to be removed
                additional_needed = max(0, reduction_needed - running_total)
                
                return jsonify({
                    "status": "budget_exceeded",
                    "current_total": current_total,
                    "budget": budget_value,
                    "reduction_needed": reduction_needed,
                    "suggested_removals": suggestions,
                    "message": f"Your cart total (${current_total:.2f}) exceeds the new budget (${budget_value:.2f}). "
                               f"Please remove items worth at least ${reduction_needed:.2f} to continue."
                })
        
        # If we get here, either cart is empty or total is within budget
        from marketplace.models import update_user_budget
        update_user_budget(user_id, budget_value)
        return jsonify({
            "status": "success",
            "budget": budget_value,
            "message": "Budget updated successfully"
        })
        
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid budget amount"}), 400
    except Exception as e:
        print(f"Error updating budget: {e}")
        return jsonify({"status": "error", "message": "Failed to update budget"}), 500


@product_bp.route("/checkout", methods=["POST"])
def checkout():
    print("\n=== CHECKOUT REQUEST RECEIVED ===")
    print(f"Session data: {session}")
    print(f"Form data: {request.form}")
    
    if "user" not in session:
        error_msg = "No user in session"
        print(f"Error: {error_msg}")
        return jsonify({
            "status": "error", 
            "message": "Your session has expired. Please log in again.",
            "error_type": "AuthenticationError"
        }), 401
        
    if session["user"].get("role") != "user":
        error_msg = f"Invalid user role - {session['user'].get('role')}"
        print(f"Error: {error_msg}")
        return jsonify({
            "status": "error", 
            "message": "Unauthorized access. Only regular users can place orders.",
            "error_type": "AuthorizationError"
        }), 403
    
    try:
        user_id = session["user"]["id"]
        print(f"\n=== CHECKOUT PROCESS STARTED ===")
        print(f"User ID: {user_id}")
        
        # Log MongoDB connection status
        from flask import current_app
        from pymongo import MongoClient
            
        try:
            # Test MongoDB connection
            client = MongoClient(current_app.config.get("MONGO_URI", "mongodb://localhost:27017"))
            client.admin.command('ping')
            print("MongoDB Connection: Successful")
            print(f"Database: {current_app.config.get('MONGO_URI', 'mongodb://localhost:27017')}")
        except Exception as e:
            print(f"MongoDB Connection Error: {str(e)}")
            return jsonify({
                "status": "error",
                "message": "Database connection error. Please try again later.",
                "error_type": "DatabaseError"
            }), 500
        
        # Get delivery address from form data
        delivery_address = request.form.get("delivery_address")
        print(f"Delivery address: {delivery_address}")
        
        if not delivery_address or not delivery_address.strip():
            print("Error: No delivery address provided")
            return jsonify({"status": "error", "message": "Please provide a delivery address"}), 400
        
        # Get user's budget
        from marketplace.models import get_user_budget
        try:
            budget = get_user_budget(user_id)
            print(f"User budget: {budget}")
        except Exception as e:
            print(f"Error getting user budget: {str(e)}")
            budget = None
        
        print("Retrieving cart...")
        try:
            cart = get_cart(user_id)
            print(f"Cart items: {len(cart.get('items', [])) if cart else 0} items")
        except Exception as e:
            print(f"Error getting cart: {str(e)}")
            return jsonify({
                "status": "error",
                "message": "Could not retrieve your cart. Please try again.",
                "error_type": "CartError"
            }), 400
        
        if not cart:
            error_msg = "Could not retrieve your cart. Please try again."
            print(f"Error: {error_msg}")
            return jsonify({"status": "error", "message": error_msg}), 400
            
        cart_items = cart.get("items", [])
        print(f"Found {len(cart_items)} items in cart")
        if not cart_items:
            return jsonify({"status": "error", "message": "Your cart is empty"}), 400
        
        # Get all product details
        print("Retrieving product details...")
        from marketplace.models import get_products_by_ids
        
        try:
            product_ids = [item["product_id"] for item in cart_items]
            print(f"Product IDs in cart: {product_ids}")
            
            products_data = get_products_by_ids(product_ids)
            print(f"Retrieved {len(products_data) if products_data else 0} products from database")
            
            if not products_data:
                error_msg = "Could not retrieve any product information. Please try again."
                print(f"Error: {error_msg}")
                return jsonify({
                    "status": "error", 
                    "message": error_msg,
                    "error_type": "ProductError"
                }), 400
                
            # Create a dictionary of product_id to product data
            products = {}
            for p in products_data:
                if p and "_id" in p:
                    products[str(p["_id"])] = p
            
            print(f"Successfully processed {len(products)} products")
            
            # Check if any products are missing
            if len(products) != len(product_ids):
                missing_products = set(product_ids) - set(products.keys())
                error_msg = f"{len(missing_products)} product(s) are no longer available. Please update your cart."
                print(f"Error: {error_msg} Missing IDs: {missing_products}")
                return jsonify({
                    "status": "error", 
                    "message": error_msg,
                    "missing_products": list(missing_products),
                    "error_type": "ProductUnavailable"
                }), 400
                
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print("\n=== ERROR GETTING PRODUCT DETAILS ===")
            print(f"Error type: {type(e).__name__}")
            print(f"Error message: {str(e)}")
            print(f"Traceback:\n{error_details}")
            
            return jsonify({
                "status": "error", 
                "message": "An error occurred while retrieving product information.",
                "error_type": type(e).__name__
            }), 500
        
        # Calculate total and check stock
        total = 0
        try:
            print("\n=== CALCULATING ORDER TOTAL ===")
            for item in cart_items:
                product_id = item.get("product_id")
                print(f"Processing product ID: {product_id}")
                
                product = products.get(product_id)
                if not product:
                    error_msg = f"Product {product_id} not found in products"
                    print(f"Error: {error_msg}")
                    print(f"Available product IDs: {list(products.keys())}")
                    return jsonify({
                        "status": "error",
                        "message": error_msg,
                        "error_type": "ProductNotFound",
                        "product_id": product_id
                    }), 400
                
                # Check stock
                stock = product.get("stock", 0)
                quantity = item.get("qty", 1)
                print(f"Product: {product.get('name')}, Stock: {stock}, Requested Qty: {quantity}")
                
                if stock < quantity:
                    error_msg = f"Not enough stock for {product.get('name', 'product')}. Available: {stock}, Requested: {quantity}"
                    print(f"Error: {error_msg}")
                    return jsonify({
                        "status": "error",
                        "message": error_msg,
                        "error_type": "InsufficientStock",
                        "product_id": product_id,
                        "available_stock": stock,
                        "requested_quantity": quantity
                    }), 400
                
                # Calculate item total
                price = float(product.get("price", 0))
                item_total = price * quantity
                total += item_total
                print(f"Item total: ${item_total:.2f} (${price:.2f} x {quantity})")
                
            print(f"Order subtotal: ${total:.2f}")
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print("\n=== ERROR CALCULATING ORDER TOTAL ===")
            print(f"Error type: {type(e).__name__}")
            print(f"Error message: {str(e)}")
            print(f"Traceback:\n{error_details}")
            print(f"Item causing error: {item}" if 'item' in locals() else "No item data available")
            
            return jsonify({
                "status": "error",
                "message": "An error occurred while calculating your order total.",
                "error_type": type(e).__name__,
                "error_details": str(e)
            }), 500
        
        # Check budget
        if budget is not None and budget > 0 and total > budget:
            return jsonify({
                "status": "budget_exceeded",
                "message": f"Order total (${total:.2f}) exceeds your budget (${budget:.2f})",
                "total": total,
                "budget": budget
            }), 400
        
        try:
            print("\n=== PROCESSING ORDER ===")
            from marketplace.models import clear_cart, _orders, _receipts, _products
            from bson import ObjectId
            
            # Create a single order with all items
            order_items = []
            print("Preparing order items...")
            for item in cart_items:
                try:
                    product_id = item["product_id"]
                    product = products[product_id]
                    print(f"Adding to order - Product: {product.get('name')}, Qty: {item.get('qty', 1)}")
                    
                    order_item = {
                        "product_id": product_id,
                        "name": product.get("name", "Unknown Product"),
                        "price": float(product.get("price", 0)),
                        "qty": item["qty"],
                        "image_url": product.get("image_url")
                    }
                    order_items.append(order_item)
                    
                except Exception as item_error:
                    print(f"Error processing item {item}: {str(item_error)}")
                    raise Exception(f"Failed to process item {item.get('product_id')}: {str(item_error)}")
            
            # Create order document with proper ObjectId conversion
            order = {
                "user_id": ObjectId(user_id) if not isinstance(user_id, ObjectId) else user_id,
                "status": "processing",
                "total": total,
                "delivery_address": delivery_address,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
                "items": order_items
            }
            
            print("Saving order to database...")
            try:
                result = _orders.insert_one(order)
                
                if not result.inserted_id:
                    raise Exception("Failed to save order to database")
                    
                print(f"Order created with ID: {result.inserted_id}")
                
            except Exception as e:
                print(f"Error saving order to database: {str(e)}")
                raise Exception(f"Failed to save order: {str(e)}")
                
            print(f"Order created successfully. Order ID: {result.inserted_id}")
            
            try:
                # Update product stock levels
                print("Updating product stock levels...")
                for item in cart_items:
                    product_id = item["product_id"]
                    quantity = item["qty"]
                    _products.update_one(
                        {"_id": ObjectId(product_id)},
                        {"$inc": {"stock": -quantity}},
                        upsert=False
                    )
                
                # Generate receipt
                print("Generating receipt...")
                receipt = {
                    "order_id": result.inserted_id,
                    "user_id": user_id,
                    "total": total,
                    "delivery_address": delivery_address,
                    "items": order_items,
                    "created_at": datetime.utcnow(),
                    "receipt_number": f"RCPT-{datetime.utcnow().strftime('%Y%m%d')}-{result.inserted_id}"
                }
                receipt_id = _receipts.insert_one(receipt).inserted_id
                print(f"Receipt generated. Receipt ID: {receipt_id}")
                
                # Clear the cart only if order was created successfully
                print("Clearing user's cart...")
                clear_cart(user_id)
                
                print("Order processing completed successfully!")
                response_data = {
                    "status": "success",
                    "message": "Order placed successfully!",
                    "order_id": str(result.inserted_id),
                    "receipt_id": str(receipt_id),
                    "data": {
                        "order_id": str(result.inserted_id)
                    }
                }
                print("Sending response:", json.dumps(response_data, indent=2))
                return jsonify(response_data)
                
            except Exception as post_order_error:
                # If we fail after creating the order but before completing other steps
                print(f"Error after order creation: {str(post_order_error)}")
                # We still return success since the order was created, but log the issue
                return jsonify({
                    "status": "partial_success",
                    "message": "Order placed, but there was an issue with post-processing. Please contact support.",
                    "order_id": str(result.inserted_id),
                    "warning": str(post_order_error)
                }), 200
                
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print("\n=== ERROR DURING CHECKOUT ===")
            print(f"Error type: {type(e).__name__}")
            print(f"Error message: {str(e)}")
            print(f"Traceback:\n{error_details}")
            
            error_message = "An error occurred while processing your order. Please try again."
            if "duplicate key error" in str(e).lower():
                error_message = "This order appears to have already been processed. Please check your orders."
            elif "validation" in str(e).lower():
                error_message = "There was a problem with the order data. Please check your cart and try again."
                
            return jsonify({
                "status": "error",
                "message": error_message,
                "error_type": type(e).__name__,
                "error_details": str(e)
            }), 500
            
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        
        # Log the full error with all details
        print("\n=== CHECKOUT ERROR ===")
        print(f"Error type: {type(e).__name__}")
        print(f"Error message: {str(e)}")
        print(f"Traceback:\n{error_details}")
        
        # Log the current cart and user data
        print("\n=== DEBUG INFO ===")
        print(f"User ID: {session.get('user', {}).get('id', 'Not available')}")
        print(f"User role: {session.get('user', {}).get('role', 'Not available')}")
        print(f"Delivery address: {request.form.get('delivery_address', 'Not provided')}")
        
        try:
            cart = get_cart(session["user"]["id"])
            print(f"Cart items: {cart.get('items', []) if cart else 'No cart found'}")
        except Exception as cart_error:
            print(f"Error getting cart: {cart_error}")
        
        # More specific error handling
        error_message = "An error occurred while processing your order. Please try again."
        
        if "duplicate key error" in str(e).lower():
            error_message = "This order appears to have already been processed. Please check your orders."
        elif "validation" in str(e).lower():
            error_message = "There was a problem with the order data. Please check your cart and try again."
        elif "timeout" in str(e).lower() or "timed out" in str(e).lower():
            error_message = "The request timed out. Please check your internet connection and try again."
        elif "connection" in str(e).lower():
            error_message = "Could not connect to the database. Please try again later."
            
        return jsonify({
            "status": "error",
            "message": error_message,
            "error_type": type(e).__name__,
            "error_details": str(e)
        }), 500
        return redirect(url_for("auth_bp.login"))
    
    try:
        from marketplace.models import _orders, _receipts
        
        # Get the order
        order = _orders.find_one({"_id": ObjectId(order_id)})
        if not order:
            flash("Order not found.", "error")
            return redirect(url_for("product_bp.orders"))
            
        # Verify the order belongs to the current user
        if str(order.get("user_id")) != session["user"]["id"] and session["user"].get("role") != "admin":
            flash("You are not authorized to view this receipt.", "error")
            return redirect(url_for("product_bp.orders"))
        
        # Get the receipt
        receipt = _receipts.find_one({"order_id": order["_id"]})
        if not receipt:
            flash("Receipt not found.", "error")
            return redirect(url_for("product_bp.orders"))
        
        # Prepare order data for PDF
        order_data = {
            "order_number": str(order["_id"]),
            "order_date": order.get("created_at", datetime.utcnow()).strftime("%Y-%m-%d %H:%M:%S"),
            "customer_name": session["user"].get("name", "Customer"),
            "delivery_address": order.get("delivery_address", "N/A"),
            "items": order.get("items", []),
            "subtotal": order.get("total", 0),
            "total": order.get("total", 0)
        }
        
        # Get the path to the logo (adjust the path as needed)
        logo_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'img', 'logo.png')
        
        # Generate PDF
        pdf_bytes = get_receipt_as_bytes(order_data, logo_path=logo_path if os.path.exists(logo_path) else None)
        
        # Create response
        response = make_response(pdf_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=receipt_{order_id}.pdf'
        
        return response
        
    except Exception as e:
        print(f"Error generating receipt: {str(e)}")
        flash("An error occurred while generating the receipt.", "error")
        return redirect(url_for("product_bp.orders"))

@product_bp.route("/profile")
def profile():
    if "user" not in session:
        return redirect(url_for("auth_bp.login"))
    
    try:
        from marketplace.models import _users, _orders
        
        # Get user details
        user = _users.find_one({"_id": ObjectId(session["user"]["id"])})
        if not user:
            flash("User not found", "error")
            return redirect(url_for("auth_bp.logout"))
        
        # Get recent orders (last 3)
        # Orders may store user_id as a string or an ObjectId. Query for both to be safe.
        try:
            user_obj_id = ObjectId(session["user"]["id"]) if session["user"]["id"] else None
        except Exception:
            user_obj_id = None

        query = {"$or": [{"user_id": session["user"]["id"]}]}
        if user_obj_id:
            query["$or"].append({"user_id": user_obj_id})

        recent_orders_cursor = _orders.find(query)\
                                    .sort("created_at", -1)\
                                    .limit(3)
        
        # Convert cursor to list and format each order
        recent_orders = []
        for order in recent_orders_cursor:
            order['_id'] = str(order['_id'])  # Convert ObjectId to string
            # Ensure order_items exists in each order
            if 'items' in order and 'order_items' not in order:
                order['order_items'] = order.pop('items')
            recent_orders.append(order)
        
        # Prepare user data for the template
        user_data = {
            "name": user.get("name", "User"),
            "email": user.get("email", ""),
            "role": user.get("role", "user"),
            "created_at": user.get("created_at"),
            "budget": user.get("budget")
        }
        
        return render_template("profile.html", 
                             user=user_data,
                             recent_orders=recent_orders)
        
    except Exception as e:
        print(f"Error loading profile: {e}")
        flash("Failed to load your profile. Please try again.", "error")
        return redirect(url_for("product_bp.store"))

def setup_logging():
    import logging
    from pathlib import Path
    
    # Create logs directory if it doesn't exist
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("logs/orders.log"),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

@product_bp.route("/orders")
def orders():
    # Set up logging
    logger = setup_logging()
    
    # Check if user is logged in
    if "user" not in session:
        flash("Please log in to view your orders.", "warning")
        return redirect(url_for("auth_bp.login"))
    
    # Redirect to retailer orders if user is a retailer
    if session["user"].get("role") == "retailer":
        return redirect(url_for("product_bp.retailer_orders"))
    
    try:
        # Import required modules
        from marketplace.models import _orders, _users, _products
        from bson import ObjectId
        from datetime import datetime
        
        # Get user ID from session
        user_id = session["user"]["id"]
        logger.info("Fetching orders for user ID: %s", user_id)
        
        # Get user details
        user = _users.find_one({"_id": ObjectId(user_id)})
        if not user:
            logger.error("User %s not found in database", user_id)
            flash("User not found. Please log in again.", "error")
            return redirect(url_for("auth_bp.logout"))
        
        logger.info("Found user: %s", user.get('email'))
        
        # Get user's orders — user_id in orders can be stored as a string or ObjectId
        query = {"$or": [{"user_id": str(user_id)}]}
        # If user_id looks like an ObjectId, also query by ObjectId type
        try:
            if ObjectId.is_valid(user_id):
                query["$or"].append({"user_id": ObjectId(user_id)})
        except Exception:
            # If conversion fails, ignore and proceed with string-only query
            pass

        user_orders = list(_orders.find(query).sort("created_at", -1))
        logger.info("Found %d orders for user %s", len(user_orders), user_id)
        
        if not user_orders:
            logger.info("No orders found for user %s", user_id)
            flash("You haven't placed any orders yet.", "info")
            return render_template("orders.html", 
                                orders=[], 
                                user_name=user.get("name", "User"))
        
        # Prepare orders data for the template
        formatted_orders = []
        
        for order in user_orders:
            try:
                logger.debug("Processing order: %s", order.get('_id'))
                items_list = []
                
                # Process each item in the order
                for item in order.get("items", []):
                    try:
                        product_id = item.get("product_id")
                        if not product_id:
                            logger.warning("Item missing product_id: %s", item)
                            continue
                            
                        # Get product details
                        product = _products.find_one({"_id": ObjectId(product_id)})
                        if product:
                            items_list.append({
                                "product_id": str(product["_id"]),
                                "name": product.get("name", "Unknown Product"),
                                "price": float(product.get("price", 0)),
                                "qty": int(item.get("qty", 1)),
                                "image_url": product.get("image_url", "")
                            })
                        else:
                            logger.warning("Product not found: %s", product_id)
                            items_list.append({
                                "product_id": str(product_id),
                                "name": "Product not available",
                                "price": 0.0,
                                "qty": int(item.get("qty", 1)),
                                "image_url": ""
                            })
                    except Exception as item_error:
                        logger.error("Error processing item: %s", str(item_error))
                        continue
                
                # Format order date
                created_at = order.get("created_at")
                if isinstance(created_at, str):
                    try:
                        created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    except (ValueError, TypeError):
                        created_at = datetime.utcnow()
                elif not isinstance(created_at, datetime):
                    created_at = datetime.utcnow()
                
                # Calculate total if not present
                total = order.get("total")
                if total is None:
                    total = sum(item.get("price", 0) * item.get("qty", 1) for item in items_list)
                
                # Create formatted order
                formatted_order = {
                    "_id": str(order.get("_id", "")),
                    "created_at": created_at,
                    "status": order.get("status", "processing"),
                    "total": float(total),
                    "order_items": items_list
                }
                
                formatted_orders.append(formatted_order)
                logger.debug("Added order: %s", formatted_order['_id'])
                
            except Exception as order_error:
                logger.error("Error processing order: %s", str(order_error), exc_info=True)
                continue
        
        # Debug: Log the structure of the first order
        if formatted_orders:
            # Create a copy of the order to avoid modifying the original
            debug_order = dict(formatted_orders[0])
            # Ensure we're using the correct key for items
            if 'order_items' in debug_order:
                debug_order['items'] = debug_order.pop('order_items')
            logger.debug("First order structure: %s", debug_order)
        
        # Return the rendered template with orders
        return render_template("orders.html",
                            orders=formatted_orders,
                            user_name=user.get("name", "User"),
                            is_retailer=False)
            
    except Exception as e:
        logger.error("Error in orders route: %s", str(e), exc_info=True)
        flash("An error occurred while loading your orders. Please try again.", "error")
        return redirect(url_for("product_bp.store"))

@product_bp.route("/retailer/orders")
def retailer_orders():
    # Set up logging
    logger = setup_logging()
    
    try:
        # Check if user is logged in and is a retailer
        if "user" not in session:
            logger.warning("Unauthorized access attempt to retailer orders - no session")
            flash("Please log in to view your orders.", "warning")
            return redirect(url_for("auth_bp.login")
                          )
            
        if session["user"].get("role") != "retailer":
            logger.warning("Unauthorized access attempt to retailer orders by non-retailer user")
            flash("Access denied. Retailer access required.", "error")
            return redirect(url_for("product_bp.store"))
        
        # Import required modules
        from marketplace.models import _orders, _users, _products
        from bson import ObjectId, errors
        from datetime import datetime
        
        # Get retailer ID from session
        retailer_id = str(session["user"].get("retailer_id") or session["user"].get("id"))
        if not retailer_id:
            logger.error("No retailer ID found in session")
            flash("Error: Could not identify retailer account.", "error")
            return redirect(url_for("product_bp.retailer_dashboard"))
            
        logger.info("Fetching orders for retailer ID: %s", retailer_id)
        
        try:
            # Get retailer's products
            retailer_products = list(_products.find({"retailer_id": retailer_id}))
            logger.debug("Found %d products for retailer %s", len(retailer_products), retailer_id)
            
            if not retailer_products:
                logger.info("No products found for retailer %s", retailer_id)
                return render_template("orders.html", 
                                    orders=[], 
                                    user_name=session["user"].get("name", "Retailer"),
                                    is_retailer=True,
                                    message="No products found. You haven't added any products yet.")
            
            product_ids = [str(p["_id"]) for p in retailer_products]
            
            # Find all orders that contain retailer's products
            retailer_orders = []
            try:
                all_orders = _orders.find({"items.product_id": {"$in": product_ids}}).sort("created_at", -1)
            except Exception as e:
                logger.error("Error querying orders: %s", str(e))
                flash("Error retrieving orders. Please try again.", "error")
                return redirect(url_for("product_bp.retailer_dashboard"))
            
            for order in all_orders:
                try:
                    if not order.get("items"):
                        continue
                        
                    # Filter items to only include those from this retailer
                    retailer_items = [
                        item for item in order.get("items", []) 
                        if item and "product_id" in item and str(item["product_id"]) in product_ids
                    ]
                    
                    if not retailer_items:
                        continue
                    
                    # Get customer details
                    customer = {}
                    try:
                        customer = _users.find_one({"_id": ObjectId(order.get("user_id"))}) or {}
                    except (errors.InvalidId, TypeError) as e:
                        logger.warning("Invalid user_id in order %s: %s", order.get("_id"), str(e))
                    
                    # Process order items
                    items_list = []
                    for item in retailer_items:
                        try:
                            product_id = str(item.get("product_id"))
                            product = next((p for p in retailer_products 
                                         if str(p.get("_id")) == product_id), None)
                            if product:
                                items_list.append({
                                    "product_id": str(product.get("_id", "")),
                                    "name": product.get("name", "Unknown Product"),
                                    "price": float(product.get("price", 0)),
                                    "qty": int(item.get("qty", 1)),
                                    "image_url": product.get("image_url", "")
                                })
                        except Exception as item_error:
                            logger.error("Error processing order item: %s", str(item_error))
                            continue
                    
                    if not items_list:  # Skip if no valid items
                        continue
                    
                    # Calculate total for retailer's items
                    total = sum(item.get("price", 0) * item.get("qty", 0) for item in items_list)
                    
                    # Format order date
                    created_at = order.get("created_at")
                    if isinstance(created_at, str):
                        try:
                            created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                        except (ValueError, TypeError):
                            created_at = datetime.utcnow()
                    elif not isinstance(created_at, datetime):
                        created_at = datetime.utcnow()
                    
                    # Add formatted order
                    retailer_orders.append({
                        "_id": str(order.get("_id", "")),
                        "created_at": created_at,
                        "status": order.get("status", "processing"),
                        "total": total,
                        "order_items": items_list,
                        "customer_name": (
                            f"{customer.get('first_name', '')} {customer.get('last_name', '')}"
                        ).strip() or "Customer",
                        "customer_email": customer.get("email", "")
                    })
                    
                except Exception as order_error:
                    logger.error("Error processing order %s: %s", order.get("_id"), str(order_error))
                    continue
            
            logger.info("Successfully processed %d orders for retailer %s", 
                       len(retailer_orders), retailer_id)
            
            # Return the rendered template with retailer's orders
            return render_template("orders.html",
                                orders=retailer_orders,
                                user_name=session["user"].get("name", "Retailer"),
                                is_retailer=True,
                                message=f"Found {len(retailer_orders)} orders" if retailer_orders else "No orders found")
            
        except Exception as db_error:
            logger.error("Database error in retailer_orders: %s", str(db_error), exc_info=True)
            flash("An error occurred while retrieving your orders. Please try again.", "error")
            return redirect(url_for("product_bp.retailer_dashboard"))
            
    except Exception as e:
        logger.critical("Unexpected error in retailer_orders: %s", str(e), exc_info=True)
        flash("An unexpected error occurred. Our team has been notified.", "error")
        return redirect(url_for("product_bp.retailer_dashboard"))