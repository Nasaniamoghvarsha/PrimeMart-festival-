from pymongo import MongoClient

def check_cart():
    try:
        # Connect to MongoDB
        client = MongoClient('mongodb://localhost:27017')
        db = client['marketplace']
        
        # List all collections
        print("Collections in database:", db.list_collection_names())
        
        # Check if carts collection exists
        if 'carts' in db.list_collection_names():
            # Get all carts
            carts = list(db.carts.find())
            print(f"\nFound {len(carts)} carts in the database")
            
            if carts:
                print("\nFirst cart document:")
                print(carts[0])
                
                # Check if the cart has items
                if 'items' in carts[0]:
                    print(f"\nCart has {len(carts[0]['items'])} items")
                    for i, item in enumerate(carts[0]['items'], 1):
                        print(f"  {i}. {item}")
                else:
                    print("\nNo items found in the cart")
            else:
                print("\nNo cart documents found in the database")
        else:
            print("\n'carts' collection does not exist")
            
    except Exception as e:
        print(f"Error checking cart: {e}")

if __name__ == "__main__":
    check_cart()
