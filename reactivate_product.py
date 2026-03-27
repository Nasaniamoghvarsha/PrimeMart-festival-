#!/usr/bin/env python3
"""
Usage: python reactivate_product.py <product_id> [--stock N]
Sets is_active=True and optional stock value for the given product id.
"""
import sys
from pymongo import MongoClient
from bson import ObjectId
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('product_id')
parser.add_argument('--stock', type=int, default=None)
args = parser.parse_args()

client = MongoClient('mongodb://localhost:27017')
db = client['marketplace']
pid = args.product_id
if ObjectId.is_valid(pid):
    query = {'_id': ObjectId(pid)}
else:
    query = {'_id': pid}
update = {'$set': {'is_active': True}}
if args.stock is not None:
    update['$set']['stock'] = int(args.stock)

res = db.products.update_one(query, update)
if res.matched_count:
    print(f"Updated product {pid}. Modified: {res.modified_count}")
else:
    print(f"Product {pid} not found.")
