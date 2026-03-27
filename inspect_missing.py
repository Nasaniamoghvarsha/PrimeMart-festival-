from pymongo import MongoClient
from bson import ObjectId

client = MongoClient('mongodb://localhost:27017')
db = client['marketplace']

pid = '68f51cd6af2a571201f0acc6'
print('Inspecting product', pid)
prod = None
if ObjectId.is_valid(pid):
    prod = db.products.find_one({'_id': ObjectId(pid)})
print('Product:', prod)

print('\nSearching carts containing this product_id (string)...')
carts = list(db.carts.find({'items.product_id': pid}))
print(f'Found {len(carts)} cart(s) with product_id as string')
for c in carts:
    print('Cart _id:', c.get('_id'), 'user_id:', c.get('user_id'), 'items:', c.get('items'))

print('\nSearching carts containing this product_id (ObjectId)...')
try:
    prod_oid = ObjectId(pid)
    carts_oid = list(db.carts.find({'items.product_id': prod_oid}))
    print(f'Found {len(carts_oid)} cart(s) with product_id as ObjectId')
    for c in carts_oid:
        print('Cart _id:', c.get('_id'), 'user_id:', c.get('user_id'), 'items:', c.get('items'))
except Exception as e:
    print('Could not parse pid as ObjectId', e)

# Also print owner of the product if exists
if prod:
    owner = prod.get('retailer_id')
    print('\nProduct retailer_id:', owner)
else:
    print('\nProduct not found in products collection')
