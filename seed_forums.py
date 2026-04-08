import os
import bcrypt
import uuid
from datetime import datetime, timedelta
from pymongo import MongoClient
from dotenv import load_dotenv
from bson import ObjectId

# Load environment variables
load_dotenv()

# MongoDB Connection
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://127.0.0.1:27017/edu_link_hub')
client = MongoClient(MONGO_URI)
db = client.get_database()

def make_hash(pw):
    return bcrypt.hashpw(pw.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def seed_forums():
    print("🚀 Starting Forums Seeding...")
    
    # ─── 1. DEMO USERS (10 users) ───
    demo_users = [
        {"name": "Arjun Kumar", "email": "arjun@demo.com", "college": "Anna University", "department": "Computer Science", "role": "student", "phone": "+919876543201"},
        {"name": "Priya Sharma", "email": "priya@demo.com", "college": "Anna University", "department": "Electronics", "role": "student", "phone": "+919876543202"},
        {"name": "Rahul Verma", "email": "rahul@demo.com", "college": "IIT Madras", "department": "Mechanical Engineering", "role": "student", "phone": "+919876543203"},
        {"name": "Ananya Iyer", "email": "ananya@demo.com", "college": "IIT Madras", "department": "Data Science", "role": "student", "phone": "+919876543204"},
        {"name": "Sneha Patel", "email": "sneha@demo.com", "college": "SRM Institute", "department": "Bio-Technology", "role": "student", "phone": "+919876543205"},
        {"name": "Vikram Singh", "email": "vikram@demo.com", "college": "SRM Institute", "department": "Civil Engineering", "role": "student", "phone": "+919876543206"},
        {"name": "Karthik Raja", "email": "karthik@demo.com", "college": "VIT Vellore", "department": "Information Technology", "role": "student", "phone": "+919876543207"},
        {"name": "Meera Reddy", "email": "meera@demo.com", "college": "VIT Vellore", "department": "Artificial Intelligence", "role": "student", "phone": "+919876543208"},
        {"name": "Rohan Das", "email": "rohan@demo.com", "college": "BITS Pilani", "department": "Electrical Engineering", "role": "student", "phone": "+919876543209"},
        {"name": "Sanya Malhotra", "email": "sanya@demo.com", "college": "BITS Pilani", "department": "Computer Science", "role": "student", "phone": "+919876543210"}
    ]

    user_map = {}
    password_hash = make_hash("Demo@1234")

    for u in demo_users:
        existing = db.users.find_one({"email": u["email"]})
        if not existing:
            u_data = {
                **u,
                "password": password_hash,
                "keywords": ["placement", "internship", "python", "mongodb"] if "Computer" in u["department"] else ["workshop"],
                "created_at": datetime.utcnow()
            }
            user_id = db.users.insert_one(u_data).inserted_id
            user_map[u["name"]] = user_id
            print(f"✅ User Created: {u['name']}")
        else:
            user_map[u["name"]] = existing["_id"]
            print(f"ℹ️ User Exists: {u['name']}")

    # ─── 2. FORUM POSTS (Community Posts) ───
    forum_posts = [
        {
            "title": "Best resources to learn MongoDB for beginners?",
            "content": "I'm starting with NoSQL and want to know where to find the best tutorials for MongoDB. Any recommendations?",
            "tags": ["mongodb", "database", "learning"],
            "author_name": "Arjun Kumar",
            "image": "https://images.unsplash.com/photo-1544383835-bda2bc66a55d?q=80&w=600",
            "created_at": datetime.utcnow() - timedelta(days=2)
        },
        {
            "title": "Top Tech Internships for Summer 2024",
            "content": "Let's compile a list of companies that have opened their summer internship applications. I'll start: Google, Microsoft, and Amazon are live!",
            "tags": ["internships", "career", "placement"],
            "author_name": "Priya Sharma",
            "image": "https://images.unsplash.com/photo-1521737711867-e3b97375f902?q=80&w=600",
            "created_at": datetime.utcnow() - timedelta(days=1)
        },
        {
            "title": "How to handle burn-out during exams?",
            "content": "Finals are coming up and I'm feeling overwhelmed. How do you guys stay productive without losing your mind?",
            "tags": ["mentalhealth", "exams", "studentlife"],
            "author_name": "Rahul Verma",
            "created_at": datetime.utcnow() - timedelta(hours=5)
        },
        {
            "title": "Poll: What is your favorite programming language?",
            "content": "Curious to see what most students are using these days for their projects.",
            "tags": ["programming", "coding", "poll"],
            "author_name": "Sanya Malhotra",
            "poll": {
                "question": "Which language do you prefer?",
                "options": [
                    {"id": str(uuid.uuid4())[:8], "text": "Python", "votes": [user_map["Arjun Kumar"], user_map["Ananya Iyer"]]},
                    {"id": str(uuid.uuid4())[:8], "text": "JavaScript", "votes": [user_map["Karthik Raja"]]},
                    {"id": str(uuid.uuid4())[:8], "text": "Java", "votes": []},
                    {"id": str(uuid.uuid4())[:8], "text": "C++", "votes": [user_map["Rohan Das"]]}
                ],
                "ends_at": datetime.utcnow() + timedelta(days=7)
            },
            "created_at": datetime.utcnow() - timedelta(hours=2)
        }
    ]

    for p in forum_posts:
        author_id = user_map.get(p.pop("author_name"))
        post_data = {
            **p,
            "author": author_id,
            "reactions": {"👍": [user_map["Meera Reddy"], user_map["Sneha Patel"]], "💡": [user_map["Vikram Singh"]], "❤️": [], "🔥": []},
            "replies": []
        }
        
        # Add a sample reply to the MongoDB post
        if "MongoDB" in p["title"]:
            post_data["replies"].append({
                "_id": ObjectId(),
                "content": "Check out MongoDB University! Their free courses are excellent for starting out.",
                "author": user_map["Ananya Iyer"],
                "upvotes": [user_map["Arjun Kumar"]],
                "created_at": datetime.utcnow() - timedelta(days=1, hours=2)
            })

        db.community_posts.insert_one(post_data)
        print(f"📝 Post Created: {p['title']}")

    print("\n✨ Seeding Complete! Enjoy your realistic Forum data.")

if __name__ == '__main__':
    seed_forums()
