from pymongo import MongoClient
import bcrypt
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

# Connect to MongoDB
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/edu_link_hub')
client = MongoClient(MONGO_URI)
db = client.get_database()

def clear_db():
    print("Clearing existing data...")
    db.users.drop()
    db.events.drop()
    db.opportunities.drop()
    db.community_posts.drop()
    db.notifications.drop()

def seed_db():
    print("Seeding database with sample data...")

    # 1. Create Users — each with its own easy password
    def make_hash(pw):
        return bcrypt.hashpw(pw.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    admin_id = db.users.insert_one({
        'name': 'Admin User',
        'email': 'admin@edu.com',
        'password': make_hash('admin123'),
        'college': 'University Admin',
        'department': 'IT Support',
        'phone': '+91 9999999999',
        'role': 'admin',
        'keywords': [],
        'created_at': datetime.utcnow()
    }).inserted_id

    mod_id = db.users.insert_one({
        'name': 'Moderator Student',
        'email': 'mod@edu.com',
        'password': make_hash('mod123'),
        'college': 'Engineering College',
        'department': 'Computer Science',
        'phone': '+91 8888888888',
        'role': 'moderator',
        'keywords': ['hackathon'],
        'created_at': datetime.utcnow()
    }).inserted_id

    student_id = db.users.insert_one({
        'name': 'Regular Student',
        'email': 'student@edu.com',
        'password': make_hash('student123'),
        'college': 'Engineering College',
        'department': 'Electronics',
        'phone': '+91 7777777777',
        'role': 'student',
        'keywords': ['workshop', 'placement'],
        'created_at': datetime.utcnow()
    }).inserted_id

    print("\n[OK] Test accounts created:")
    print("  [Admin]     email: admin@edu.com      | password: admin123")
    print("  [Moderator] email: mod@edu.com         | password: mod123")
    print("  [Student]   email: student@edu.com     | password: student123")

    # 2. Create Events
    db.events.insert_many([
        {
            'title': 'AI & Machine Learning Workshop',
            'organizer': 'Computer Science Dept',
            'category': 'workshop',
            'date': '2025-10-15T10:00',
            'image': 'https://images.unsplash.com/photo-1555949963-aa79dcee57d5?auto=format&fit=crop&q=80',
            'description': 'A hands-on workshop covering neural networks and practical AI applications.',
            'registration_link': 'https://example.com/register/ai',
            'created_by': admin_id,
            'created_at': datetime.utcnow()
        },
        {
            'title': 'Annual Tech Hackathon 2025',
            'organizer': 'Tech Club',
            'category': 'hackathon',
            'date': '2025-11-20T09:00',
            'image': 'https://images.unsplash.com/photo-1504384308090-c894fdcc538d?auto=format&fit=crop&q=80',
            'description': '48-hour coding marathon to solve real world problems.',
            'registration_link': 'https://example.com/hackathon',
            'created_by': mod_id,
            'created_at': datetime.utcnow()
        }
    ])
    print("Events created.")

    # 3. Create Opportunities
    db.opportunities.insert_many([
        {
            'company': 'Tech Solutions Inc',
            'role': 'Software Engineering Intern',
            'category': 'internship',
            'location': 'Remote',
            'eligibility': 'B.Tech CSE 2026 Batch',
            'deadline': '2025-05-30',
            'description': 'Looking for passionate students for a 6-month SWE internship.',
            'apply_link': 'https://example.com/apply/tech-inc',
            'status': 'approved',
            'created_by': mod_id,
            'created_at': datetime.utcnow()
        },
        {
            'company': 'Global Data Corp',
            'role': 'Data Analyst',
            'category': 'job',
            'location': 'Bangalore',
            'eligibility': 'Any degree with data skills',
            'deadline': '2025-06-15',
            'description': 'Full-time role for fresh graduates.',
            'apply_link': 'https://example.com/apply/data-corp',
            'status': 'pending', # Moderator needs to review this
            'created_by': student_id,
            'created_at': datetime.utcnow()
        }
    ])
    print("Opportunities created (1 approved, 1 pending review).")

    # 4. Create Community Posts
    post_id = db.community_posts.insert_one({
        'title': 'Tips for clearing technical interviews?',
        'content': 'I have my first technical interview next week. What should I focus on? Data structures or projects?',
        'tags': ['interview', 'placement', 'advice'],
        'author': student_id,
        'upvotes': [mod_id, admin_id],
        'upvote_count': 2,
        'reply_count': 1,
        'created_at': datetime.utcnow()
    }).inserted_id

    db.community_replies.insert_one({
        'post_id': post_id,
        'content': 'Focus heavily on problem-solving with Data Structures and Algorithms. Arrays, Strings, and Hash Maps are the most common.',
        'author': mod_id,
        'upvotes': [],
        'upvote_count': 0,
        'created_at': datetime.utcnow()
    })
    print("Community Q&A created.")

    print("\nDatabase seed complete! Check MongoDB Compass to see your new data.")

if __name__ == '__main__':
    clear_db()
    seed_db()
