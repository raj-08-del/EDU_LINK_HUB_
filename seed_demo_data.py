from pymongo import MongoClient
from bson.objectid import ObjectId

client = MongoClient('mongodb://localhost:27017/')
# Check .env or config for db name, usually it's edulinkhub or similar.
# Wait, let's see what the app uses. In run.py or config, it's probably 'edulinkhub'.
# I'll just check what databases exist or try connecting to what the app uses.
import os
from dotenv import load_dotenv

load_dotenv()
mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/edulinkhub")

client = MongoClient(mongo_uri)
db = client.get_default_database()

colleges = list(db.colleges.find())

placements = [
    {"student_name": "Rohan Gupta", "student_photo": "https://i.pravatar.cc/150?img=11", "batch_year": "2023", "company": "Amazon", "role": "SDE 1", "package_lpa": "24", "department": "CSE", "company_logo": "https://upload.wikimedia.org/wikipedia/commons/a/a9/Amazon_logo.svg"},
    {"student_name": "Ayesha Khan", "student_photo": "https://i.pravatar.cc/150?img=5", "batch_year": "2023", "company": "Microsoft", "role": "Software Engineer", "package_lpa": "42", "department": "IT", "company_logo": "https://upload.wikimedia.org/wikipedia/commons/4/44/Microsoft_logo.svg"}
]

departments = [
    {"name": "Computer Science and Engineering", "short_name": "CSE", "head_of_dept": "Dr. Smith", "faculty_count": 45, "student_count": 800, "established": 1995, "description": "Core computer science program focusing on software development and AI."},
    {"name": "Information Technology", "short_name": "IT", "head_of_dept": "Dr. Jane Doe", "faculty_count": 30, "student_count": 600, "established": 1998, "description": "Focuses on IT infrastructure, networking, and software engineering."}
]

alumni = [
    {"name": "Vikram Singh", "batch": "2015", "photo": "https://i.pravatar.cc/150?img=12", "company": "Google", "role": "Senior Engineer", "package": "60", "is_wall_of_fame": True, "achievement": "Promoted to Tech Lead"},
    {"name": "Priya Sharma", "batch": "2018", "photo": "https://i.pravatar.cc/150?img=9", "company": "Meta", "role": "Product Manager", "package": "45", "is_wall_of_fame": False}
]

gallery = [
    {"title": "Campus Academic Block", "image_url": "https://images.unsplash.com/photo-1541339907198-e08756dedf3f?w=800", "date": "2023-01-01", "description": "The main academic building of the college."},
    {"title": "Annual Tech Fest 2023", "image_url": "https://images.unsplash.com/photo-1511512578047-dfb367046420?w=800", "date": "2023-05-15", "description": "Students presenting innovative projects at the annual technology festival."}
]

for college in colleges:
    cid = college['_id']
    
    # Check if data already exists to avoid duplication
    if db.college_placements.count_documents({'college_id': cid}) == 0:
        for p in placements:
            p_copy = p.copy()
            p_copy['college_id'] = cid
            db.college_placements.insert_one(p_copy)
            
    if db.departments.count_documents({'college_id': cid}) == 0:
        for d in departments:
            d_copy = d.copy()
            d_copy['college_id'] = cid
            db.departments.insert_one(d_copy)
            
    if db.college_alumni.count_documents({'college_id': cid}) == 0:
        for a in alumni:
            a_copy = a.copy()
            a_copy['college_id'] = cid
            db.college_alumni.insert_one(a_copy)
            
    if db.college_events.count_documents({'college_id': cid}) == 0:
        for g in gallery:
            g_copy = g.copy()
            g_copy['college_id'] = cid
            db.college_events.insert_one(g_copy)

print(f"Seeding complete for {len(colleges)} colleges.")
