import os
from pymongo import MongoClient
from datetime import datetime, timedelta
from bson import ObjectId

# Database configuration
client = MongoClient('mongodb://localhost:27017/')
db = client.edu_link_hub

# Admin User ID (from research)
ADMIN_ID = ObjectId('69cd2156132d956c01266418')

# Image paths (already moved to app/static/uploads/)
IMAGES = {
    'hackathon': '/static/uploads/tech_hackathon.png',
    'workshop': '/static/uploads/coding_workshop.png',
    'festival': '/static/uploads/college_festival.png',
    'career': '/static/uploads/career_fair.png'
}

def seed_events():
    """Seed 20 events."""
    print("Seeding 20 events...")
    event_titles = [
        "Global AI Hackathon 2026", "Next-Gen Web Workshop", "Campus Music Fest",
        "Cybersecurity Summit", "Data Science Bootcamp", "Robotics Competition",
        "Entrepreneurship Talk", "Cloud Computing Seminar", "AI Art Exhibition",
        "Blockchain Developers Meetup", "Gaming Tournament", "Literary Fest",
        "Open Source Contribution Day", "Design Thinking Workshop", "Sports Gala",
        "Tech Innovation Hub Launch", "Mobile App Development Contest", "Networking Night",
        "Sustainability Hackathon", "Creative Writing Workshop"
    ]
    
    categories = ['hackathon', 'workshop', 'festival', 'technical', 'workshop', 'technical',
                  'non-technical', 'technical', 'non-technical', 'technical', 'non-technical', 'festival',
                  'workshop', 'workshop', 'non-technical', 'technical', 'hackathon', 'non-technical',
                  'hackathon', 'workshop']
                  
    for i in range(20):
        # Determine image based on title or category
        img = IMAGES['hackathon']
        if 'Workshop' in event_titles[i]: img = IMAGES['workshop']
        elif 'Fest' in event_titles[i]: img = IMAGES['festival']
        elif 'Cybersecurity' in event_titles[i] or 'Tech' in event_titles[i]: img = IMAGES['hackathon']
        
        event = {
            'title': event_titles[i],
            'college_name': "EDU Link University",
            'category': categories[i],
            'date': (datetime.utcnow() + timedelta(days=i + 5)).strftime('%Y-%m-%d'),
            'image': img,
            'description': f"Join us for the {event_titles[i]}! A great opportunity to learn, network, and grow.",
            'registration_link': "https://example.com/register",
            'tags': [categories[i], 'tech', 'student'],
            'created_by': ADMIN_ID,
            'created_at': datetime.utcnow()
        }
        db.events.insert_one(event)

def seed_opportunities():
    """Seed 10 opportunities."""
    print("Seeding 10 opportunities...")
    opps = [
        ("Google", "SDE Intern", "internship", "Mountain View (Remote)"),
        ("Microsoft", "Program Manager", "job", "Seattle"),
        ("Amazon", "Applied Scientist", "job", "Bangalore"),
        ("Meta", "Product Designer", "internship", "London"),
        ("TCS", "Graduate Trainee", "campus-placement", "Chennai"),
        ("Reliance", "Management Intern", "internship", "Mumbai"),
        ("Zoho", "Frontend Developer", "job", "Coimbatore"),
        ("Adobe", "Research Intern", "internship", "Noida"),
        ("SpaceX", "Aerospace Engineer", "job", "Hawthorne"),
        ("Tesla", "Data Analyst", "job", "Austin")
    ]
    
    for i, (comp, role, cat, loc) in enumerate(opps):
        opp = {
            'company': comp,
            'role': role,
            'category': cat,
            'location': loc,
            'eligibility': "B.Tech/M.Tech Final Year Students",
            'deadline': (datetime.utcnow() + timedelta(days=15 + i)).strftime('%Y-%m-%d'),
            'description': f"Exciting {role} opening at {comp}. Apply now to join a world-class team.",
            'image': IMAGES['career'],
            'apply_link': "https://careers.example.com",
            'tags': [cat, comp],
            'status': 'approved',
            'created_by': ADMIN_ID,
            'created_at': datetime.utcnow()
        }
        db.opportunities.insert_one(opp)

def seed_community():
    """Seed 10 community posts."""
    print("Seeding 10 community posts...")
    posts = [
        "How to start with Open Source?",
        "Best resources for Learning React 2026",
        "Tips for Cracked coding Interviews",
        "My Experience at the Tech Hackathon",
        "Is AI going to replace junior developers?",
        "How to manage studies and projects?",
        "Recommendation for local study groups",
        "Upcoming Tech Events in April",
        "Favorite VS Code extensions in 2026",
        "What are you building this weekend?"
    ]
    
    for i, title in enumerate(posts):
        post = {
            'title': title,
            'content': f"Hello Community! I wanted to share some thoughts on {title}. Let's discuss!",
            'tags': ['discussion', 'tech', 'student'],
            'image': IMAGES['workshop'] if i % 2 == 0 else '',
            'author': ADMIN_ID,
            'reactions': {'👍': [], '💡': [], '❤️': [], '🔥': []},
            'created_at': datetime.utcnow()
        }
        db.community_posts.insert_one(post)

if __name__ == "__main__":
    # Clear existing data to avoid duplicates if needed, but here we just append
    # db.events.delete_many({})
    # db.opportunities.delete_many({})
    # db.community_posts.delete_many({})
    
    seed_events()
    seed_opportunities()
    seed_community()
    print("Seeding complete!")
