from flask import Blueprint, jsonify, session
from bson import ObjectId
from pymongo import MongoClient

# Set up MongoDB connection
client = MongoClient('mongodb://localhost:27017/')
db = client['marketplace']

debug_bp = Blueprint('debug', __name__)

@debug_bp.route('/debug/cart')
def debug_cart():
    if 'user' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    user_id = session['user'].get('_id') or session['user'].get('id')
    if not user_id:
        return jsonify({'error': 'User ID not found in session'}), 400
    
    # Try to find cart with user_id as string
    cart = db.carts.find_one({'user_id': user_id})
    
    # If not found, try with ObjectId
    if not cart and ObjectId.is_valid(user_id):
        cart = db.carts.find_one({'user_id': ObjectId(user_id)})
    
    if not cart:
        return jsonify({
            'message': 'No cart found for user',
            'user_id': user_id,
            'user_id_type': type(user_id).__name__
        })
    
    # Get product details for items in cart
    product_ids = []
    for item in cart.get('items', []):
        try:
            product_ids.append(ObjectId(item['product_id']))
        except:
            continue
    
    products = list(db.products.find({'_id': {'$in': product_ids}}))
    
    # Prepare response
    response = {
        'cart': cart,
        'products_found': len(products),
        'products': products,
        'user_id': str(user_id),
        'user_id_type': type(user_id).__name__
    }
    
    return jsonify(response)
