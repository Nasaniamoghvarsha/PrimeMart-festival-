"""
Marketplace Flask Application Package
This package contains the core logic for the PrimeMart electronics marketplace.
"""

import os
from flask import Flask, send_from_directory
from marketplace.config import Config
from marketplace.models import init_db

def create_app():
    """
    Application Factory for the Flask app.
    Returns:
        app: The initialized Flask application instance.
    """
    app = Flask(__name__, static_folder='static', template_folder='templates')
    
    # Load configuration from Config class
    app.config.from_object(Config)
    
    # Ensure necessary directories exist
    os.makedirs(os.path.join(app.root_path, 'static', 'receipts'), exist_ok=True)
    os.makedirs(os.path.join(app.root_path, 'static', 'img'), exist_ok=True)
    
    # Configure logging
    import logging
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)

    @app.before_request
    def log_request_info():
        from flask import session, request
        from marketplace.models import _carts
        from bson import ObjectId
        logger.debug(f"Request: {request.method} {request.path}")
        if 'user' in session:
            user_id = session['user'].get('id') or session['user'].get('_id')
            if user_id:
                cart = _carts.find_one({'user_id': user_id}) or \
                       (_carts.find_one({'user_id': ObjectId(user_id)}) if ObjectId.is_valid(user_id) else None)
                if cart:
                    logger.debug(f"Cart found for user {user_id}")
        else:
            logger.debug("No user in session")

    # Register blueprints
    from marketplace.routes.auth import auth_bp
    from marketplace.routes.product import product_bp
    from marketplace.routes.payment import payment_bp
    from marketplace.routes.debug import debug_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(product_bp)
    app.register_blueprint(payment_bp, url_prefix='/payment')
    app.register_blueprint(debug_bp, url_prefix='/debug')
    
    # Initialize the database
    with app.app_context():
        init_db()
    
    # Core Routes
    @app.route("/")
    def home():
        from flask import render_template
        return render_template("index.html")

    @app.route("/dashboard")
    def dashboard():
        from flask import render_template, session, flash, redirect, url_for
        if "user" not in session:
            flash("Please login first.", "warning")
            return redirect(url_for("auth_bp.login"))
        user_name = session.get("user", {}).get("name", "User")
        return render_template("dashboard.html", user=user_name)

    @app.route("/favicon.ico")
    def favicon():
        """Handle favicon requests."""
        try:
            return send_from_directory(
                os.path.join(app.root_path, 'static', 'img'),
                'favicon.ico',
                mimetype='image/vnd.microsoft.icon'
            )
        except Exception:
            return ('', 204)

    # Error Handlers
    @app.errorhandler(404)
    def page_not_found(e):
        from flask import render_template
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        from flask import render_template
        return render_template('errors/500.html'), 500

    return app
