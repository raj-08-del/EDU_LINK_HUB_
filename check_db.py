from pymongo import MongoClient
import os
from dotenv import load_dotenv
from bson import ObjectId

load_dotenv()
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://127.0.0.1:27017/edu_link_hub')
client = MongoClient(MONGO_URI)
db = client.get_database()

print("--- Opportunities ---")
opps = list(db.opportunities.find())
print(f"Total: {len(opps)}")
for o in opps:
    print(f"ID: {o.get('_id')}, Company: {o.get('company')}, Status: {o.get('status')}, Archived: {o.get('is_archived')}, Created By: {o.get('created_by')}")

print("\n--- Events ---")
events = list(db.events.find())
print(f"Total: {len(events)}")
for e in events:
    print(f"ID: {e.get('_id')}, Title: {e.get('title')}, Created By: {e.get('created_by')}")
