#!/usr/bin/env python3
"""
Usage: python remove_from_carts.py <product_id>
Removes all occurrences of product_id from carts.items across the database.
"""
import sys
from pymongo import MongoClient

if len(sys.argv) < 2:
    print('Usage: remove_from_carts.py <product_id>')
    sys.exit(1)

pid = sys.argv[1]
client = MongoClient('mongodb://localhost:27017')
db = client['marketplace']

res = db.carts.update_many({}, {'$pull': {'items': {'product_id': pid}}})
print(f'Modified carts: {res.modified_count}')
