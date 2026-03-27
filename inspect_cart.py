from pymongo import MongoClient
from bson import ObjectId

# Connect to MongoDB
client = MongoClient('mongodb://localhost:27017/')
db = client['marketplace']

def inspect_user_cart(user_id_str):
    print(f"\nInspecting cart for user ID: {user_id_str}")
    print(f"Type of user_id: {type(user_id_str)}")
    
    # Try to find cart with user_id as string
    cart = db.carts.find_one({'user_id': user_id_str})
    print("\nCart found with string user_id:", cart is not None)
    
    # If not found, try with ObjectId
    if not cart and ObjectId.is_valid(user_id_str):
        user_id_obj = ObjectId(user_id_str)
        print(f"\nTrying with ObjectId: {user_id_obj}")
        cart = db.carts.find_one({'user_id': user_id_obj})
        print("Cart found with ObjectId user_id:", cart is not None)
    
    if not cart:
        print("\nNo cart found with either string or ObjectId user_id")
        return
    
    print("\nCart found:")
    print(f"Cart ID: {cart.get('_id')}")
    print(f"User ID: {cart.get('user_id')} (type: {type(cart.get('user_id'))})")
    print(f"Items: {len(cart.get('items', []))}")
    
    # Get product details for items in cart
    if 'items' in cart and cart['items']:
        print("\nItems in cart:")
        for i, item in enumerate(cart['items'], 1):
            product_id = item.get('product_id')
            qty = item.get('qty', 1)
            print(f"\nItem {i}:")
            print(f"  Product ID: {product_id} (type: {type(product_id)})")
            print(f"  Quantity: {qty}")
            
            # Try to find the product
            product = None
            if ObjectId.is_valid(str(product_id)):
                product = db.products.find_one({'_id': ObjectId(str(product_id))})
            
            if product:
                print(f"  Product found: {product.get('name')}")
                print(f"  Price: {product.get('price')}")
                print(f"  Image URL: {product.get('image_url', 'N/A')}")
            else:
                print("  Product not found in database!")
    else:
        print("\nNo items in cart")

if __name__ == "__main__":
    # Get the user ID from the session or input
    user_id = input("Enter the user ID to inspect cart (or leave empty to check all carts): ").strip()
    
    if user_id:
        inspect_user_cart(user_id)
    else:
        # List all carts
        print("\nAll carts in the database:")
        for cart in db.carts.find():
            print(f"\nCart ID: {cart.get('_id')}")
            print(f"User ID: {cart.get('user_id')} (type: {type(cart.get('user_id'))})")
            print(f"Items: {len(cart.get('items', []))}")
            if cart.get('items'):
                print("Sample item product IDs:", [item.get('product_id') for item in cart.get('items', [])[:3]])
                if len(cart.get('items', [])) > 3:
                    print(f"... and {len(cart.get('items', [])) - 3} more")
