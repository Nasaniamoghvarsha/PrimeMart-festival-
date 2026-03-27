from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash
from functools import wraps

from marketplace.models import validate_user, create_user

auth_bp = Blueprint("auth_bp", __name__, template_folder="../templates")

# ----------------------------
# Helpers / Decorators
# ----------------------------
def retailer_required(view):
    """
    Use this decorator on any route that should be accessible
    only by logged-in retailers.
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        u = session.get("user")
        if not u or u.get("role") != "retailer":
            flash("Retailer access only. Please login as a retailer.", "warning")
            return redirect(url_for("auth_bp.retailer_login"))
        return view(*args, **kwargs)
    return wrapped


# ----------------------------
# LOGIN (User)
# ----------------------------
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = validate_user(email, password)
        print("DEBUG: User returned from validate_user:", user)

        if user:
            # Base session payload for all users
            session["user"] = {
                "id": user.get("id"),
                "name": user.get("name", "User"),
                "email": user.get("email"),
                "role": user.get("role", "user"),
            }

            # If retailer, also store retailer_id (used for ownership checks)
            if session["user"]["role"] == "retailer":
                # In this app, we use the user id itself as the retailer_id
                session["user"]["retailer_id"] = session["user"]["id"]

            flash(f"Welcome back, {session['user']['name']}!", "success")

            # Redirect based on role
            if session["user"]["role"] == "retailer":
                return redirect(url_for("product_bp.retailer_dashboard"))
            else:
                return redirect(url_for("product_bp.store"))
        else:
            flash("Invalid email or password!", "danger")
            return redirect(url_for("auth_bp.login"))

    # Render login page on GET
    return render_template("login.html")


# ----------------------------
# SIGNUP (User)
# ----------------------------
@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm_password = request.form.get("confirm_password") or ""

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("auth_bp.signup"))
        if not name or not email or not password:
            flash("All fields are required.", "danger")
            return redirect(url_for("auth_bp.signup"))

        hashed_password = generate_password_hash(password)
        try:
            create_user(name, email, hashed_password, role="user")
            flash("Account created successfully! Please login.", "success")
            return redirect(url_for("auth_bp.login"))
        except Exception as e:
            print("DEBUG: Signup error:", e)
            flash("Email already exists or database error!", "danger")
            return redirect(url_for("auth_bp.signup"))

    return render_template("signup.html")


# ----------------------------
# LOGIN (Retailer)
# ----------------------------
@auth_bp.route("/retailer/login", methods=["GET", "POST"])
def retailer_login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = validate_user(email, password)

        if user and user.get("role") == "retailer":
            session["user"] = {
                "id": user.get("id"),
                "name": user.get("name", "Retailer"),
                "email": user.get("email"),
                "role": "retailer",
                # IMPORTANT: used to scope product ownership (update/delete)
                "retailer_id": user.get("id"),
            }
            flash(f"Welcome back, {session['user']['name']}!", "success")
            return redirect(url_for("product_bp.retailer_dashboard"))

        elif user and user.get("role") != "retailer":
            flash("This account is not a retailer. Please use the user login.", "danger")
            return redirect(url_for("auth_bp.login"))

        else:
            flash("Invalid email or password!", "danger")
            return redirect(url_for("auth_bp.retailer_login"))

    return render_template("retailer_login.html")


# ----------------------------
# SIGNUP (Retailer)
# ----------------------------
@auth_bp.route("/retailer/signup", methods=["GET", "POST"])
def retailer_signup():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm_password = request.form.get("confirm_password") or ""

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("auth_bp.retailer_signup"))
        if not name or not email or not password:
            flash("All fields are required.", "danger")
            return redirect(url_for("auth_bp.retailer_signup"))

        hashed_password = generate_password_hash(password)
        try:
            create_user(name, email, hashed_password, role="retailer")
            flash("Retailer account created! Please login.", "success")
            return redirect(url_for("auth_bp.retailer_login"))
        except Exception as e:
            print("DEBUG: Retailer signup error:", e)
            flash("Email already exists or database error!", "danger")
            return redirect(url_for("auth_bp.retailer_signup"))

    return render_template("retailer_signup.html")


# ----------------------------
# LOGOUT
# ----------------------------
@auth_bp.route("/logout")
def logout():
    session.pop("user", None)
    flash("Logged out successfully!", "success")
    return redirect(url_for("home"))
