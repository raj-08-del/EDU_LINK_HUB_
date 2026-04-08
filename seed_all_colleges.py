import os
import random
from pymongo import MongoClient
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://127.0.0.1:27017/edu_link_hub')
client = MongoClient(MONGO_URI)
db = client.get_database()

def recalculate_college_ratings(college_id):
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

def seed_all_colleges():
    print("🚀 SEEDING DEMO DATA FOR ALL CUSTOM COLLEGES...")
    # Find a default author, or just grab the first admin 
    author = db.users.find_one({"role": "admin"})
    if not author:
        author = db.users.find_one()
    
    author_id = author["_id"] if author else None

    # Find all colleges
    colleges = list(db.colleges.find())
    counts = {"depts": 0, "posts": 0}

    generic_depts = [
        ("Computer Science", "CSE"),
        ("Electronics", "ECE"),
        ("Mechanical Engineering", "MECH"),
        ("Business Administration", "BBA")
    ]

    for college in colleges:
        college_id = college["_id"]
        
        # Check if they have departments
        dept_count = db.departments.count_documents({"college_id": college_id})
        updated = False

        if dept_count == 0:
            print(f"Adding departments for {college.get('name', 'Unknown')}")
            for d_name, d_short in generic_depts:
                dept_doc = {
                    "college_id": college_id,
                    "name": d_name,
                    "short_name": d_short,
                    "description": f"Official community for {d_name}.",
                    "stats": {"total_members": random.randint(10, 100), "total_posts": 0},
                    "created_at": datetime.utcnow()
                }
                res = db.departments.insert_one(dept_doc)
                dept_id = res.inserted_id
                counts["depts"] += 1
                
                # Seed some posts
                demo_posts = [
                    {
                        "post_type": "review",
                        "title": f"Review: Great experience at {d_short}",
                        "content": "Overall the experience has been great. The labs are well equipped and professors are supportive. Placements are also decent.",
                        "rating": {
                            "overall": random.randint(3, 5), "academics": random.randint(3, 5),
                            "placements": random.randint(3, 5), "infrastructure": random.randint(3, 5),
                            "faculty": random.randint(3, 5), "campus_life": random.randint(3, 5),
                            "would_recommend": True
                        },
                        "tags": ["review"]
                    },
                    {
                        "post_type": "event",
                        "title": f"Upcoming: {d_short} Seminar",
                        "content": "Join us for the departmental seminar. Technical talks and workshops included.",
                        "event_data": {
                            "event_date": (datetime.utcnow() + timedelta(days=15)).strftime("%Y-%m-%d"),
                            "venue": "Main Auditorium",
                            "registration_link": "",
                            "rsvp_users": []
                        },
                        "tags": ["event"]
                    },
                    {
                        "post_type": "discussion",
                        "title": "Welcome to the new semester!",
                        "content": "What are your goals for this term? Let's discuss studying strategies.",
                        "tags": ["discussion", "general"]
                    },
                    {
                        "post_type": "placement_info",
                        "title": "Placement Drive Announced",
                        "content": "A top company is coming for campus placements next week. Make sure to prepare your resumes.",
                        "placement_data": {
                            "company": "Tech Corp",
                            "package": f"{random.randint(5, 12)} LPA",
                            "visit_date": (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%d")
                        },
                        "tags": ["career"]
                    }
                ]
                
                for p in demo_posts:
                    p.update({
                        "college_id": college_id,
                        "department_id": dept_id,
                        "author": author_id,
                        "is_anonymous": random.choice([True, False]),
                        "upvotes": [], "replies": [], "views": random.randint(10, 150),
                        "is_hidden": False, "is_pinned": False,
                        "created_at": datetime.utcnow() - timedelta(days=random.randint(0, 30))
                    })
                
                db.college_posts.insert_many(demo_posts)
                db.colleges.update_one({'_id': college_id}, {'$inc': {'stats.total_posts': 4}})
                db.departments.update_one({'_id': dept_id}, {'$inc': {'stats.total_posts': 4}})
                counts["posts"] += 4
                updated = True

        if updated:
            db.colleges.update_one({'_id': college_id}, {'$set': {'stats.total_departments': 4}})
            recalculate_college_ratings(college_id)

    print("✅ COMPLETE!")
    print(f"Added {counts['depts']} departments and {counts['posts']} posts to empty colleges.")

if __name__ == "__main__":
    seed_all_colleges()
