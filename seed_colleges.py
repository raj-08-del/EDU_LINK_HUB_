import os
import random
import bcrypt
import uuid
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

# Seed Data Configuration
COLLEGES_DATA = [
    {
        "name": "Anna University",
        "short_name": "AU",
        "city": "Chennai",
        "state": "Tamil Nadu",
        "type": "government",
        "established": 1978,
        "website": "https://www.annauniv.edu",
        "description": "Anna University is a premier public technical university in Tamil Nadu. It is renowned for its Engineering and Technology programs and has a massive campus in Guindy, Chennai.",
        "avg_package": "6.5 LPA",
        "top_recruiters": ["TCS", "Infosys", "Wipro", "Cognizant", "HCL"],
        "is_verified": True,
        "depts": [
            ("Computer Science Engineering", "CSE"),
            ("Electronics & Communication", "ECE"),
            ("Mechanical Engineering", "MECH"),
            ("Information Technology", "IT")
        ]
    },
    {
        "name": "SRM Institute of Science and Technology",
        "short_name": "SRM",
        "city": "Chennai",
        "state": "Tamil Nadu",
        "type": "deemed",
        "established": 1985,
        "website": "https://www.srmist.edu.in",
        "description": "SRM is a multi-campus deemed university offering a vast range of programs. It's known for its state-of-the-art infrastructure and diverse student population from all over India.",
        "avg_package": "7.2 LPA",
        "top_recruiters": ["Amazon", "Microsoft", "Adobe", "Google", "Zoho"],
        "is_verified": True,
        "depts": [
            ("Computer Science Engineering", "CSE"),
            ("Electronics Engineering", "ECE"),
            ("Biotechnology", "BIOTECH"),
            ("Management Studies", "MBA")
        ]
    },
    {
        "name": "Vellore Institute of Technology",
        "short_name": "VIT",
        "city": "Vellore",
        "state": "Tamil Nadu",
        "type": "deemed",
        "established": 1984,
        "website": "https://vit.ac.in",
        "description": "VIT is consistently ranked among the top private engineering institutions in India. It is famous for its FFCS system and excellent research facilities.",
        "avg_package": "8.1 LPA",
        "top_recruiters": ["Microsoft", "Intel", "Cisco", "JP Morgan", "Goldman Sachs"],
        "is_verified": True,
        "depts": [
            ("Computer Science Engineering", "CSE"),
            ("Software Engineering", "SE"),
            ("Electronics & Electricals", "EEE"),
            ("Mechanical Engineering", "MECH")
        ]
    },
    {
        "name": "PSG College of Technology",
        "short_name": "PSG",
        "city": "Coimbatore",
        "state": "Tamil Nadu",
        "type": "private",
        "established": 1951,
        "website": "https://www.psgtech.edu",
        "description": "PSG Tech in Coimbatore is one of the oldest and most prestigious private engineering colleges in India, known for its strong industry-academia collaborations.",
        "avg_package": "5.5 LPA",
        "top_recruiters": ["L&T", "Bosch", "Caterpillar", "TVS", "Hyundai"],
        "is_verified": True,
        "depts": [
            ("Computer Science Engineering", "CSE"),
            ("Mechanical Engineering", "MECH"),
            ("Production Engineering", "PE"),
            ("Robotics & Automation", "RA")
        ]
    },
    {
        "name": "NIT Trichy",
        "short_name": "NITT",
        "city": "Tiruchirappalli",
        "state": "Tamil Nadu",
        "type": "government",
        "established": 1964,
        "website": "https://www.nitt.edu",
        "description": "National Institute of Technology, Tiruchirappalli is a public technical and research university. It is the top-ranked NIT in India and is an Institute of National Importance.",
        "avg_package": "10.5 LPA",
        "top_recruiters": ["Google", "Microsoft", "Samsung", "Qualcomm", "Oracle"],
        "is_verified": True,
        "depts": [
            ("Computer Science Engineering", "CSE"),
            ("Electronics & Communication", "ECE"),
            ("Chemical Engineering", "CHEM"),
            ("Civil Engineering", "CIVIL")
        ]
    }
]

def recalculate_college_ratings(college_id):
    """Aggregates all review posts for a college to update ratings."""
    pipeline = [
        {'$match': {'college_id': college_id, 'post_type': 'review', 'is_hidden': {'$ne': True}}},
        {'$group': {
            '_id': None,
            'overall': {'$avg': '$rating.overall'},
            'academics': {'$avg': '$rating.academics'},
            'placements': {'$avg': '$rating.placements'},
            'infrastructure': {'$avg': '$rating.infrastructure'},
            'faculty': {'$avg': '$rating.faculty'},
            'campus_life': {'$avg': '$rating.campus_life'},
            'total_reviews': {'$sum': 1}
        }}
    ]
    result = list(db.college_posts.aggregate(pipeline))
    if result:
        stats = result[0]
        db.colleges.update_one(
            {'_id': college_id},
            {'$set': {
                'ratings.overall': round(stats['overall'], 1),
                'ratings.academics': round(stats['academics'], 1),
                'ratings.placements': round(stats['placements'], 1),
                'ratings.infrastructure': round(stats['infrastructure'], 1),
                'ratings.faculty': round(stats['faculty'], 1),
                'ratings.campus_life': round(stats['campus_life'], 1),
                'ratings.total_reviews': stats['total_reviews']
            }}
        )

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
    print("   🚀 STARTING COLLEGE SEED PROCESS")
    print("════════════════════════════════════════")
    
    author_id = get_or_create_seed_user()
    
    counts = {"colleges": 0, "depts": 0, "posts": 0}

    for cdata in COLLEGES_DATA:
        # 1. Check if college exists
        college = db.colleges.find_one({"name": cdata["name"]})
        if not college:
            college_doc = {
                "name": cdata["name"],
                "short_name": cdata["short_name"],
                "city": cdata["city"],
                "state": cdata["state"],
                "type": cdata["type"],
                "established": cdata["established"],
                "website": cdata["website"],
                "logo_url": f"/static/images/colleges/{cdata['short_name'].lower()}.png",
                "description": cdata["description"],
                "ratings": {
                    "overall": 0.0, "academics": 0.0, "placements": 0.0,
                    "infrastructure": 0.0, "faculty": 0.0, "campus_life": 0.0, "total_reviews": 0
                },
                "stats": {
                    "total_students": random.randint(2000, 15000),
                    "total_departments": len(cdata["depts"]),
                    "total_posts": 0,
                    "avg_package": cdata["avg_package"],
                    "top_recruiters": cdata["top_recruiters"]
                },
                "is_verified": cdata["is_verified"],
                "created_at": datetime.utcnow()
            }
            res = db.colleges.insert_one(college_doc)
            college_id = res.inserted_id
            print(f"[+] SEEDING: {cdata['name']}")
            counts["colleges"] += 1
        else:
            college_id = college["_id"]
            print(f"[*] SKIPPING: {cdata['name']} (exists)")

        # 2. Seed Departments
        for d_name, d_short in cdata["depts"]:
            dept = db.departments.find_one({"college_id": college_id, "name": d_name})
            if not dept:
                dept_doc = {
                    "college_id": college_id,
                    "name": d_name,
                    "short_name": d_short,
                    "description": f"Official community hub for the Department of {d_name} at {cdata['short_name']}.",
                    "stats": {"total_members": random.randint(50, 500), "total_posts": 0},
                    "created_at": datetime.utcnow()
                }
                res = db.departments.insert_one(dept_doc)
                dept_id = res.inserted_id
                counts["depts"] += 1
            else:
                dept_id = dept["_id"]

            # 3. Seed Posts (Idempotency check: only if dept has no posts)
            if db.college_posts.count_documents({"department_id": dept_id}) == 0:
                demo_posts = [
                    {
                        "post_type": "review",
                        "title": f"Review: My journey in {d_short}",
                        "content": "Overall the experience has been great. The labs are equipped with high-end workstations and the library access is excellent. Placements for our branch were top-tier this year.",
                        "rating": {
                            "overall": random.randint(3, 5), "academics": random.randint(3, 5),
                            "placements": random.randint(3, 5), "infrastructure": random.randint(3, 5),
                            "faculty": random.randint(3, 5), "campus_life": random.randint(3, 5),
                            "would_recommend": True
                        },
                        "tags": ["review", "campus_life"]
                    },
                    {
                        "post_type": "event",
                        "title": f"Upcoming: {d_short} Technical Symposium",
                        "content": "Join us for the annual technical fest. Workshops on AI/ML, Paper Presentations, and more! Refreshments provided for all participants.",
                        "event_data": {
                            "event_date": (datetime.utcnow() + timedelta(days=15)).strftime("%Y-%m-%d"),
                            "venue": "Main Auditorium, Block C",
                            "registration_link": "https://forms.gle/demo",
                            "rsvp_users": []
                        },
                        "tags": ["event", "techfest"]
                    },
                    {
                        "post_type": "placement_info",
                        "title": f"{random.choice(cdata['top_recruiters'])} visit for 2026 Batch",
                        "content": "A campus drive is scheduled next week. Eligibility: CGPA > 7.5. Role: Software Engineer. Please upload your latest resume by tomorrow.",
                        "placement_data": {
                            "company": random.choice(cdata['top_recruiters']),
                            "package": f"{random.randint(4, 15)} LPA",
                            "visit_date": (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%d")
                        },
                        "tags": ["career", "placement"]
                    },
                    {
                        "post_type": "fresher_tip",
                        "title": f"5 Things for Freshers in {d_short}",
                        "content": "1. Focus on Data Structures early. 2. Join the official discord. 3. Visit the digital library. 4. Campus canteen has best dosa. 5. Senior-Junior interaction is key!",
                        "tags": ["fresher", "help", "guide"]
                    },
                    {
                        "post_type": "resource",
                        "title": "Semester 3 Lecture Notes Bundle",
                        "content": "I've uploaded the complete set of notes for the core subjects. Really helpful for end-semester preparation.",
                        "media": [{
                            "url": "https://example.com/notes.pdf",
                            "type": "document",
                            "filename": f"{d_short}_Sem3_Notes.pdf",
                            "size_bytes": 4500000
                        }],
                        "tags": ["notes", "resource", "academic"]
                    }
                ]

                # Common fields for all posts
                for p in demo_posts:
                    p.update({
                        "college_id": college_id,
                        "department_id": dept_id,
                        "author": author_id,
                        "is_anonymous": random.choice([True, False]),
                        "upvotes": [], "replies": [], "views": random.randint(10, 500),
                        "is_hidden": False, "is_pinned": random.random() < 0.1,
                        "created_at": datetime.utcnow() - timedelta(days=random.randint(0, 30))
                    })
                
                db.college_posts.insert_many(demo_posts)
                db.colleges.update_one({'_id': college_id}, {'$inc': {'stats.total_posts': 5}})
                db.departments.update_one({'_id': dept_id}, {'$inc': {'stats.total_posts': 5}})
                counts["posts"] += 5

        # Recalculate ratings for the college after seeding posts
        recalculate_college_ratings(college_id)

    print("════════════════════════════════════════")
    print("   ✅ SEEDING COMPLETE")
    print(f"   Colleges:    {counts['colleges']}")
    print(f"   Departments: {counts['depts']}")
    print(f"   Demo Posts:  {counts['posts']}")
    print("════════════════════════════════════════")

if __name__ == "__main__":
    run_seed()
