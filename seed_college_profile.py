import os
import random
import bcrypt
from pymongo import MongoClient
from datetime import datetime, timedelta
from dotenv import load_dotenv
from bson import ObjectId

# Load environment variables
load_dotenv()

# MongoDB Configuration
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://127.0.0.1:27017/edu_link_hub')
client = MongoClient(MONGO_URI)
db = client.get_database()

def get_or_create_seed_user():
    user = db.users.find_one({"email": "demo_seed@edulink.com"})
    if not user:
        password = "password123"
        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        res = db.users.insert_one({
            "name": "Seed Administrator",
            "email": "demo_seed@edulink.com",
            "password": hashed,
            "role": "admin",
            "is_verified": True,
            "created_at": datetime.utcnow()
        })
        print("[+] Created seed user: demo_seed@edulink.com")
        return res.inserted_id
    return user["_id"]

def run_seed():
    print("════════════════════════════════════════")
    print("   🚀 STARTING COLLEGE PROFILE SEED")
    print("════════════════════════════════════════")
    
    author_id = get_or_create_seed_user()
    
    # 1. Update existing colleges with new fields
    colleges = list(db.colleges.find({}))
    for c in colleges:
        updates = {
            "naac_grade": random.choice(["A++", "A+", "A", "B++", "B+"]),
            "nirf_rank": random.randint(10, 150),
            "total_students": c.get('stats', {}).get('total_students', random.randint(3000, 15000)),
            "total_faculty": random.randint(200, 800),
            "total_departments": c.get('stats', {}).get('total_departments', random.randint(8, 20)),
            "hero_image": "https://images.unsplash.com/photo-1541339907198-e08756dedf3f?w=1920&q=80",
            "logo": "https://images.unsplash.com/photo-1599305445671-ac291c95aaa9?w=200&q=80",
            "facilities": ["Library", "Sports Complex", "Hostels", "WiFi Campus", "Labs", "Cafeteria"],
            "social_links": {"linkedin": "#", "instagram": "#", "twitter": "#"},
            "mou_partners": ["TCS", "Infosys", "Google", "Microsoft", "Amazon"],
            "accreditations": ["NAAC A++", "NBA Accredited", "ISO 9001:2015"]
        }
        db.colleges.update_one({"_id": c["_id"]}, {"$set": updates})

    # 2. Add sample reviews, placements, alumni, events to the first college
    if not colleges:
        print("No colleges found to seed. Run seed_colleges.py first.")
        return

    main_college = colleges[0]
    cid = main_college["_id"]
    
    print(f"Seeding details for {main_college['name']}...")

    # Clear old new-schema collections for this college
    db.college_reviews.delete_many({"college_id": cid})
    db.placements.delete_many({"college_id": cid})
    db.alumni.delete_many({"college_id": cid})
    db.college_events.delete_many({"college_id": cid})

    # Add Reviews
    reviews = []
    for _ in range(5):
        reviews.append({
            "college_id": cid,
            "user_id": author_id,
            "user_name": "Anonymous Student",
            "is_verified_student": True,
            "batch_year": random.choice([2023, 2024, 2025, 2026]),
            "department": random.choice(["CSE", "ECE", "MECH", "IT"]),
            "overall_rating": random.uniform(3.5, 5.0),
            "faculty_rating": random.uniform(3.5, 5.0),
            "infrastructure_rating": random.uniform(3.5, 5.0),
            "placement_rating": random.uniform(3.5, 5.0),
            "campus_rating": random.uniform(3.5, 5.0),
            "title": random.choice(["Great college for tech students", "Excellent campus life", "Good placements, strict faculty", "Top notch infrastructure"]),
            "review_text": "The college provides excellent opportunities for growth. The curriculum is regularly updated to match industry standards.",
            "pros": ["Good placements", "Active clubs", "Great infrastructure"],
            "cons": ["Less parking", "Strict attendance", "Mess food could be better"],
            "photos": [],
            "upvotes": random.randint(5, 50),
            "created_at": datetime.utcnow() - timedelta(days=random.randint(1, 100))
        })
    db.college_reviews.insert_many(reviews)

    # Add Placements
    placements = []
    companies = ["Google", "Microsoft", "Amazon", "TCS", "Infosys", "Wipro", "Zoho"]
    for i in range(15):
        year = random.choice([2023, 2024])
        placements.append({
            "college_id": cid,
            "student_name": f"Student {i+1}",
            "student_photo": f"https://api.dicebear.com/7.x/avataaars/svg?seed=Student{i+1}",
            "department": random.choice(["CSE", "IT", "ECE"]),
            "batch_year": year,
            "company": random.choice(companies),
            "company_logo": f"https://logo.clearbit.com/{random.choice(['google.com', 'microsoft.com', 'amazon.com', 'tcs.com'])}",
            "role": random.choice(["Software Engineer", "Data Analyst", "Product Manager", "Consultant"]),
            "package_lpa": round(random.uniform(5.0, 45.0), 1),
            "location": random.choice(["Bangalore", "Chennai", "Hyderabad", "Pune"]),
            "offer_type": "On-Campus",
            "testimonial": "The placement cell was very helpful throughout the process.",
            "created_at": datetime.utcnow()
        })
    db.placements.insert_many(placements)

    # Add Alumni
    alumni = []
    for i in range(6):
        alumni.append({
            "college_id": cid,
            "name": f"Alumnus {i+1}",
            "photo": f"https://api.dicebear.com/7.x/avataaars/svg?seed=Alum{i+1}",
            "graduation_year": random.choice([2015, 2018, 2020, 2021]),
            "department": random.choice(["CSE", "MECH", "ECE"]),
            "current_company": random.choice(["Google", "Microsoft", "Meta", "Netflix", "Startup"]),
            "current_role": random.choice(["Senior Engineer", "Staff Engineer", "Founder", "Tech Lead"]),
            "current_location": random.choice(["Seattle, USA", "London, UK", "Bangalore, India", "San Francisco, CA"]),
            "package": random.randint(20, 150),
            "linkedin": "https://linkedin.com/in/#",
            "quote": "This college gave me the right platform to launch my career.",
            "is_wall_of_fame": True if i < 3 else False,
            "created_at": datetime.utcnow()
        })
    db.alumni.insert_many(alumni)

    # Add Events Gallery
    events = []
    for i in range(8):
        events.append({
            "college_id": cid,
            "event_name": f"TechFest {2024 - i%3}",
            "event_type": random.choice(["Festival", "Technical", "Cultural", "Sports"]),
            "date": (datetime.utcnow() - timedelta(days=random.randint(10, 300))).strftime("%Y-%m-%d"),
            "photos": ["https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=800&q=80"],
            "video_url": "",
            "description": "Annual festival bringing together students from across the country.",
            "participants": random.randint(500, 5000),
            "created_at": datetime.utcnow()
        })
    db.college_events.insert_many(events)

    print("✅ Successfully seeded college profile data.")

if __name__ == "__main__":
    run_seed()
