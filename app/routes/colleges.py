import os
import uuid
import re
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request
from werkzeug.utils import secure_filename
from bson import ObjectId
from datetime import datetime
from app import mongo
from app.utils import serialize_doc, get_current_user

colleges_bp = Blueprint('colleges', __name__)

def recalculate_college_ratings(college_id):
    """Aggregates all review posts for a college to update ratings."""
    try:
        pipeline = [
            {'$match': {'college_id': ObjectId(college_id), 'post_type': 'review', 'is_hidden': {'$ne': True}}},
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
        result = list(mongo.db.college_posts.aggregate(pipeline))
        if result:
            stats = result[0]
            mongo.db.colleges.update_one(
                {'_id': ObjectId(college_id)},
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
    except Exception as e:
        print(f"Error recalculating ratings: {e}")

def get_slug(name):
    slug = name.lower()
    slug = re.sub(r'[^a-z0-9]', '-', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug

# ── College Routes ──

@colleges_bp.route('/', methods=['GET'])
def get_colleges():
    try:
        search = request.args.get('search', '').strip()
        ctype = request.args.get('type', '').strip()
        city = request.args.get('city', '').strip()
        state = request.args.get('state', '').strip()
        sort = request.args.get('sort', 'newest') # Default to newest for modern feed
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 12))
        skip = (page - 1) * limit

        # Base query with hidden check
        query = {'is_hidden': {'$ne': True}}
        
        if search:
            query['$or'] = [
                {'name': {'$regex': search, '$options': 'i'}},
                {'short_name': {'$regex': search, '$options': 'i'}},
                {'city': {'$regex': search, '$options': 'i'}}
            ]
        
        if ctype and ctype.lower() != 'all': 
            query['type'] = ctype.lower()
        if city and city.lower() != 'all cities': 
            query['city'] = re.compile(f'^{city}$', re.I)
        if state and state.lower() != 'all states': 
            query['state'] = re.compile(f'^{state}$', re.I)

        # Sort Logic
        sort_stage = [('created_at', -1)]
        if sort == 'most_active': 
            sort_stage = [('stats.total_posts', -1)]
        elif sort == 'rating':
            sort_stage = [('ratings.overall', -1)]

        total = mongo.db.colleges.count_documents(query)
        
        # Optimized Projection: Only fetch what the card needs
        projection = {
            '_id': 1, 'name': 1, 'short_name': 1, 'type': 1, 
            'city': 1, 'state': 1, 'is_verified': 1, 'created_by': 1
        }
        
        colleges = list(mongo.db.colleges.find(query, projection).sort(sort_stage).skip(skip).limit(limit))

        # Serialize IDs
        result = []
        for c in colleges:
            c['_id'] = str(c['_id'])
            if c.get('created_by'):
                c['created_by'] = str(c['created_by'])
            result.append(c)

        return jsonify({
            'colleges': result,
            'total': total,
            'page': page,
            'total_pages': (total + limit - 1) // limit
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/search', methods=['GET'])
def search_colleges():
    try:
        q = request.args.get('q', '').strip()
        if len(q) < 2:
            return jsonify([])
        
        query = {
            'is_hidden': {'$ne': True},
            '$or': [
                {'name': {'$regex': q, '$options': 'i'}},
                {'short_name': {'$regex': q, '$options': 'i'}},
                {'city': {'$regex': q, '$options': 'i'}}
            ]
        }
        
        colleges = list(mongo.db.colleges.find(
            query,
            {'_id': 1, 'name': 1, 'short_name': 1, 'city': 1, 'is_verified': 1, 'type': 1}
        ).limit(8))
        
        return jsonify(serialize_doc(colleges)), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/compare', methods=['GET'])
def compare_colleges():
    try:
        ids = request.args.get('ids', '').split(',')
        if len(ids) < 2:
            return jsonify({'error': 'Two college IDs required'}), 400
        
        obj_ids = []
        for i in ids:
            if i.strip(): obj_ids.append(ObjectId(i.strip()))
            
        colleges = list(mongo.db.colleges.find({'_id': {'$in': obj_ids}}))
        return jsonify(serialize_doc(colleges)), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>', methods=['GET'])
def get_college(college_id):
    try:
        college = mongo.db.colleges.find_one({'_id': ObjectId(college_id)})
        if not college:
            return jsonify({'error': 'College not found'}), 404
        
        departments = list(mongo.db.departments.find({'college_id': ObjectId(college_id)}))
        # Deduplicate departments
        seen_short = set()
        unique_depts = []
        for d in departments:
            short = (d.get('short_name') or d.get('name', '')).upper().strip()
            if short not in seen_short:
                seen_short.add(short)
                unique_depts.append(d)
        departments = unique_depts

        recent_posts = list(mongo.db.college_posts.find(
            {'college_id': ObjectId(college_id), 'is_hidden': {'$ne': True}}
        ).sort('created_at', -1).limit(5))

        is_member = False
        try:
            verify_jwt_in_request(optional=True)
            user_id = get_jwt_identity()
            if user_id:
                member = mongo.db.college_members.find_one({
                    'user_id': ObjectId(user_id),
                    'college_id': ObjectId(college_id)
                })
                is_member = bool(member)
        except: pass

        college['departments'] = departments
        college['recent_posts'] = recent_posts
        college['is_member'] = is_member

        return jsonify(serialize_doc(college)), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>', methods=['PUT'])
@jwt_required()
def update_college(college_id):
    try:
        user_id = get_jwt_identity()
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        
        college = mongo.db.colleges.find_one({'_id': ObjectId(college_id)})
        if not college:
            return jsonify({'error': 'College not found'}), 404

        is_owner = str(college.get('created_by')) == str(user_id)
        is_admin = user and user.get('role') in ('admin', 'moderator')

        if not (is_owner or is_admin):
            return jsonify({'error': 'Forbidden: You cannot edit this college'}), 403

        data = request.get_json(silent=True) or {}
        
        update_fields = {}
        if 'name' in data:
            name = data['name'].strip()
            if not name:
                return jsonify({'error': 'Name is required'}), 400
            update_fields['name'] = name
            update_fields['slug'] = get_slug(name)
        if 'short_name' in data:
            update_fields['short_name'] = data['short_name'].strip()
        if 'city' in data:
            city = data['city'].strip()
            if not city:
                return jsonify({'error': 'City is required'}), 400
            update_fields['city'] = city
        if 'state' in data:
            update_fields['state'] = data['state'].strip()
        if 'type' in data:
            update_fields['type'] = data['type'].lower()
        if 'established' in data:
            try:
                update_fields['established'] = int(data['established']) if data['established'] else None
            except (ValueError, TypeError):
                pass
        if 'description' in data:
            update_fields['description'] = data['description'].strip()
        if 'website' in data:
            update_fields['website'] = data['website'].strip()
        if 'email' in data:
            update_fields['email'] = data['email'].strip()
        if 'phone' in data:
            update_fields['phone'] = data['phone'].strip()
        
        # Social Links Handling
        if 'social_links' in data:
            update_fields['social_links'] = data['social_links']

        if 'facilities' in data:
            fac_list = [f.strip() for f in data['facilities'].split(',') if f.strip()]
            update_fields['facilities'] = fac_list

        if 'logo_url' in data:
            update_fields['logo_url'] = data['logo_url'].strip()
            update_fields['logo'] = data['logo_url'].strip() # compatibility with college_profile.html
        if 'hero_image' in data:
            update_fields['hero_image'] = data['hero_image'].strip()

        if update_fields:
            update_fields['updated_at'] = datetime.utcnow()
            mongo.db.colleges.update_one(
                {'_id': ObjectId(college_id)},
                {'$set': update_fields}
            )

        return jsonify({'message': 'College updated successfully'}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>', methods=['DELETE'])
@jwt_required()
def delete_college(college_id):
    try:
        user_id = get_jwt_identity()
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        
        college = mongo.db.colleges.find_one({'_id': ObjectId(college_id)})
        if not college:
            return jsonify({'error': 'College not found'}), 404

        is_owner = str(college.get('created_by')) == str(user_id)
        is_admin = user and user.get('role') in ('admin', 'moderator')

        if not (is_owner or is_admin):
            return jsonify({'error': 'Forbidden: You cannot delete this college'}), 403

        mongo.db.colleges.delete_one({'_id': ObjectId(college_id)})
        
        # Clean up related records
        mongo.db.college_posts.delete_many({'college_id': ObjectId(college_id)})
        mongo.db.departments.delete_many({'college_id': ObjectId(college_id)})
        mongo.db.college_members.delete_many({'college_id': ObjectId(college_id)})
        
        return jsonify({'message': 'College deleted successfully'}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/', methods=['POST'])
@jwt_required()
def create_college():
    try:
        data = request.get_json(silent=True) or {}
        user_id = get_jwt_identity()
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not user or user.get('role') not in ('admin', 'moderator'):
            return jsonify({'error': 'Admin or moderator only'}), 403

        name = data.get('name', '').strip()
        city = data.get('city', '').strip()
        if not name or not city:
            return jsonify({'error': 'Name and city are required'}), 400

        est_raw = data.get('established')
        try:
            established = int(est_raw) if est_raw else None
        except (ValueError, TypeError):
            established = None

        college = {
            'name': name,
            'slug': get_slug(name),
            'short_name': data.get('short_name', '').strip(),
            'city': city,
            'state': data.get('state', '').strip(),
            'type': data.get('type', 'private').lower(),
            'established': established,
            'website': data.get('website', '').strip(),
            'logo_url': data.get('logo_url', ''),
            'description': data.get('description', '').strip(),
            'ratings': {
                'overall': 0.0, 'academics': 0.0, 'placements': 0.0,
                'infrastructure': 0.0, 'faculty': 0.0, 'campus_life': 0.0,
                'total_reviews': 0
            },
            'stats': {
                'total_students': 0, 'total_departments': 0, 'total_posts': 0,
                'avg_package': '', 'top_recruiters': []
            },
            'is_verified': False,
            'is_hidden': False,
            'created_by': ObjectId(user_id),
            'created_at': datetime.utcnow()
        }
        res = mongo.db.colleges.insert_one(college)
        college['_id'] = str(res.inserted_id)
        college['created_by'] = str(user_id)
        return jsonify(serialize_doc(college)), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/admin/seed-department-stats')
def seed_department_stats():
    """One-time route to add demo stats to departments"""
    import random
    colleges = mongo.db.colleges.find({})
    updated = 0
    for college in colleges:
        # Update departments in the dedicated collection
        departments = list(mongo.db.departments.find({'college_id': college['_id']}))
        if not departments:
            continue
        for dept in departments:
            update_data = {}
            if not dept.get('faculty_count'):
                update_data['faculty_count'] = random.randint(15, 80)
            if not dept.get('student_count'):
                update_data['student_count'] = random.randint(200, 1500)
            if not dept.get('established'):
                update_data['established'] = random.randint(1985, 2010)
            
            if update_data:
                mongo.db.departments.update_one(
                    {'_id': dept['_id']},
                    {'$set': update_data}
                )
        updated += 1
    return f'Updated {updated} colleges with demo department stats'

@colleges_bp.route('/admin/seed-college-demo-data')
def seed_college_demo_data():
    """Seed placements, departments, alumni, and gallery data for colleges"""
    colleges_list = list(mongo.db.colleges.find({}))
    
    placements_demo = [
        {"student_name": "Rohan Gupta", "student_photo": "https://i.pravatar.cc/150?img=11", "batch_year": "2023", "company": "Amazon", "role": "SDE 1", "package_lpa": "24", "department": "CSE", "company_logo": "https://upload.wikimedia.org/wikipedia/commons/a/a9/Amazon_logo.svg"},
        {"student_name": "Ayesha Khan", "student_photo": "https://i.pravatar.cc/150?img=5", "batch_year": "2023", "company": "Microsoft", "role": "Software Engineer", "package_lpa": "42", "department": "IT", "company_logo": "https://upload.wikimedia.org/wikipedia/commons/4/44/Microsoft_logo.svg"}
    ]
    
    departments_demo = [
        {"name": "Computer Science and Engineering", "short_name": "CSE", "head_of_dept": "Dr. Smith", "faculty_count": 45, "student_count": 800, "established": 1995, "description": "Core computer science program."},
        {"name": "Information Technology", "short_name": "IT", "head_of_dept": "Dr. Jane", "faculty_count": 30, "student_count": 600, "established": 1998, "description": "Focuses on IT and software."}
    ]

    alumni_demo = [
        {"name": "Vikram Singh", "batch": "2015", "photo": "https://i.pravatar.cc/150?img=12", "company": "Google", "role": "Senior Engineer", "package": "60", "is_wall_of_fame": True, "achievement": "Promoted to Tech Lead"},
        {"name": "Priya Sharma", "batch": "2018", "photo": "https://i.pravatar.cc/150?img=9", "company": "Meta", "role": "Product Manager", "package": "45", "is_wall_of_fame": False}
    ]
    
    gallery_demo = [
        {"title": "Campus Academic Block", "image_url": "https://images.unsplash.com/photo-1541339907198-e08756dedf3f?w=800", "date": "2023-01-01", "description": "The main academic building."},
        {"title": "Annual Tech Fest", "image_url": "https://images.unsplash.com/photo-1511512578047-dfb367046420?w=800", "date": "2023-05-15", "description": "Students presenting innovative projects."}
    ]
    
    updated = 0
    for college in colleges_list:
        cid = college['_id']
        has_new_data = False
        
        # Placements
        if mongo.db.college_placements.count_documents({'college_id': cid}) == 0:
            for p in placements_demo:
                p_copy = p.copy()
                p_copy['college_id'] = cid
                mongo.db.college_placements.insert_one(p_copy)
            has_new_data = True
            
        # Departments
        if mongo.db.departments.count_documents({'college_id': cid}) == 0:
            for d in departments_demo:
                d_copy = d.copy()
                d_copy['college_id'] = cid
                mongo.db.departments.insert_one(d_copy)
            has_new_data = True
            
        # Alumni
        if mongo.db.college_alumni.count_documents({'college_id': cid}) == 0:
            for a in alumni_demo:
                a_copy = a.copy()
                a_copy['college_id'] = cid
                mongo.db.college_alumni.insert_one(a_copy)
            has_new_data = True
            
        # Gallery
        if mongo.db.college_events.count_documents({'college_id': cid}) == 0:
            for g in gallery_demo:
                g_copy = g.copy()
                g_copy['college_id'] = cid
                mongo.db.college_events.insert_one(g_copy)
            has_new_data = True
            
        if has_new_data:
            updated += 1
    
    return f'Seeded demo data for {updated} colleges'

@colleges_bp.route('/<college_id>/departments', methods=['GET'])
def get_departments(college_id):
    try:
        depts = list(mongo.db.departments.find({'college_id': ObjectId(college_id)}))
        # Deduplicate by short_name
        seen_short = set()
        unique = []
        for d in depts:
            short = (d.get('short_name') or d.get('name', '')).upper().strip()
            if short not in seen_short:
                seen_short.add(short)
                unique.append(d)
        return jsonify(serialize_doc(unique)), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>', methods=['GET'])
def get_department(college_id, dept_id):
    try:
        dept = mongo.db.departments.find_one({'_id': ObjectId(dept_id), 'college_id': ObjectId(college_id)})
        if not dept:
            return jsonify({'error': 'Department not found'}), 404
        
        recent_posts = list(mongo.db.college_posts.find(
            {'department_id': ObjectId(dept_id), 'is_hidden': {'$ne': True}}
        ).sort('created_at', -1).limit(5))

        is_member = False
        try:
            verify_jwt_in_request(optional=True)
            user_id = get_jwt_identity()
            if user_id:
                member = mongo.db.college_members.find_one({
                    'user_id': ObjectId(user_id),
                    'department_id': ObjectId(dept_id)
                })
                is_member = bool(member)
        except: pass

        dept['recent_posts'] = recent_posts
        dept['is_member'] = is_member

        return jsonify(serialize_doc(dept)), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>/students', methods=['GET'])
def get_dept_students(college_id, dept_id):
    try:
        year = request.args.get('year')
        query = {'dept_id': ObjectId(dept_id), 'college_id': ObjectId(college_id)}
        if year and str(year).isdigit():
            query['year'] = int(year)
        
        students = list(mongo.db.dept_top_students.find(query).sort('cgpa', -1))
        return jsonify({'students': serialize_doc(students)}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>/students', methods=['POST'])
@jwt_required()
def add_dept_student(college_id, dept_id):
    try:
        user_id = get_jwt_identity()
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not user or user.get('role') not in ('admin', 'moderator'):
            return jsonify({'error': 'Unauthorized'}), 403
            
        data = request.get_json()
        student = {
            'dept_id': ObjectId(dept_id),
            'college_id': ObjectId(college_id),
            'name': data.get('name'),
            'photo_url': data.get('photo_url', ''),
            'year': int(data.get('year', 1)),
            'cgpa': float(data.get('cgpa', 0)),
            'rank': int(data.get('rank', 0)),
            'department_name': data.get('department_name', ''),
            'achievements': data.get('achievements', []),
            'skills': data.get('skills', []),
            'social_links': data.get('social_links', {}),
            'is_anonymous': bool(data.get('is_anonymous', False)),
            'added_by': ObjectId(user_id),
            'created_at': datetime.utcnow()
        }
        mongo.db.dept_top_students.insert_one(student)
        return jsonify({'message': 'Student added'}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>/students/<student_id>', methods=['GET'])
def get_single_dept_student(college_id, dept_id, student_id):
    try:
        if not ObjectId.is_valid(student_id):
            return jsonify({'error': 'Invalid ID format'}), 404
        s = mongo.db.dept_top_students.find_one({'_id': ObjectId(student_id), 'dept_id': ObjectId(dept_id)})
        if not s: return jsonify({'error': 'Not found'}), 404
        return jsonify(serialize_doc(s)), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>/students/<student_id>', methods=['PUT'])
@jwt_required()
def update_dept_student(college_id, dept_id, student_id):
    try:
        user_id = get_jwt_identity()
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not user or user.get('role') not in ('admin', 'moderator'):
            return jsonify({'error': 'Unauthorized'}), 403
            
        data = request.get_json()
        update_fields = {}
        if 'name' in data: update_fields['name'] = data['name']
        if 'photo_url' in data: update_fields['photo_url'] = data['photo_url']
        if 'year' in data: update_fields['year'] = int(data['year'])
        if 'cgpa' in data: update_fields['cgpa'] = float(data['cgpa'])
        if 'rank' in data: update_fields['rank'] = int(data['rank'])
        if 'social_links' in data: update_fields['social_links'] = data['social_links']
        if 'is_anonymous' in data: update_fields['is_anonymous'] = bool(data['is_anonymous'])
        
        mongo.db.dept_top_students.update_one(
            {'_id': ObjectId(student_id), 'dept_id': ObjectId(dept_id)},
            {'$set': update_fields}
        )
        return jsonify({'message': 'Student updated'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>/students/<student_id>', methods=['DELETE'])
@jwt_required()
def delete_dept_student(college_id, dept_id, student_id):
    try:
        user_id = get_jwt_identity()
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not user or user.get('role') not in ('admin', 'moderator'):
            return jsonify({'error': 'Unauthorized'}), 403
            
        mongo.db.dept_top_students.delete_one({
            '_id': ObjectId(student_id), 
            'dept_id': ObjectId(dept_id),
            'college_id': ObjectId(college_id)
        })
        return jsonify({'message': 'Student deleted'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>/placements', methods=['GET'])
def get_dept_placements(college_id, dept_id):
    try:
        year = request.args.get('year')
        sort = request.args.get('sort', 'package')
        
        query = {'dept_id': ObjectId(dept_id)}
        if year and year != 'all': query['batch_year'] = int(year)
        
        sort_stage = [('package_lpa', -1)]
        if sort == 'newest': sort_stage = [('created_at', -1)]
        
        placements = list(mongo.db.dept_placements.find(query).sort(sort_stage).limit(50))
        return jsonify({'placements': serialize_doc(placements)}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>/placements', methods=['POST'])
@jwt_required()
def submit_dept_placement(college_id, dept_id):
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        placement = {
            'dept_id': ObjectId(dept_id),
            'college_id': ObjectId(college_id),
            'student_name': data.get('student_name'),
            'photo_url': data.get('photo_url', ''),
            'batch_year': int(data.get('batch_year')),
            'company': data.get('company'),
            'role': data.get('role'),
            'package_lpa': float(data.get('package_lpa')),
            'location': data.get('location', ''),
            'quote': data.get('quote', ''),
            'skills_used': data.get('skills_used', []),
            'is_anonymous': bool(data.get('is_anonymous', False)),
            'linkedin_url': data.get('linkedin_url', ''),
            'twitter_url': data.get('twitter_url', ''),
            'instagram_url': data.get('instagram_url', ''),
            'other_social_name': data.get('other_social_name', ''),
            'other_social_url': data.get('other_social_url', ''),
            'verified': False,
            'added_by': ObjectId(user_id),
            'created_at': datetime.utcnow()
        }
        mongo.db.dept_placements.insert_one(placement)
        return jsonify({'message': 'Placement submitted'}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>/placements/<placement_id>', methods=['GET'])
def get_single_dept_placement(college_id, dept_id, placement_id):
    try:
        p = mongo.db.dept_placements.find_one({'_id': ObjectId(placement_id), 'dept_id': ObjectId(dept_id)})
        if not p: return jsonify({'error': 'Not found'}), 404
        p['_id'] = str(p['_id'])
        p['dept_id'] = str(p['dept_id'])
        p['college_id'] = str(p['college_id'])
        return jsonify(p), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>/placements/<placement_id>', methods=['PUT'])
@jwt_required()
def update_dept_placement(college_id, dept_id, placement_id):
    try:
        user_id = get_jwt_identity()
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not user or user.get('role') not in ('admin', 'moderator'):
            return jsonify({'error': 'Unauthorized'}), 403
            
        data = request.get_json()
        update_fields = {}
        if 'student_name' in data: update_fields['student_name'] = data['student_name']
        if 'photo_url' in data: update_fields['photo_url'] = data['photo_url']
        if 'batch_year' in data: update_fields['batch_year'] = int(data['batch_year'])
        if 'company' in data: update_fields['company'] = data['company']
        if 'role' in data: update_fields['role'] = data['role']
        if 'package_lpa' in data: update_fields['package_lpa'] = float(data['package_lpa'])
        if 'quote' in data: update_fields['quote'] = data['quote']
        if 'linkedin_url' in data: update_fields['linkedin_url'] = data['linkedin_url']
        if 'twitter_url' in data: update_fields['twitter_url'] = data['twitter_url']
        if 'instagram_url' in data: update_fields['instagram_url'] = data['instagram_url']
        if 'other_social_name' in data: update_fields['other_social_name'] = data['other_social_name']
        if 'other_social_url' in data: update_fields['other_social_url'] = data['other_social_url']
        
        mongo.db.dept_placements.update_one(
            {'_id': ObjectId(placement_id), 'dept_id': ObjectId(dept_id)},
            {'$set': update_fields}
        )
        return jsonify({'message': 'Placement updated'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>/placements/<placement_id>', methods=['DELETE'])
@jwt_required()
def delete_dept_placement(college_id, dept_id, placement_id):
    try:
        user_id = get_jwt_identity()
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not user or user.get('role') not in ('admin', 'moderator'):
            return jsonify({'error': 'Unauthorized'}), 403
            
        mongo.db.dept_placements.delete_one({
            '_id': ObjectId(placement_id), 
            'dept_id': ObjectId(dept_id)
        })
        return jsonify({'message': 'Placement deleted'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>/features', methods=['GET'])
def get_dept_features(college_id, dept_id):
    try:
        features = list(mongo.db.dept_features.find({'dept_id': ObjectId(dept_id)}).sort('order', 1))
        return jsonify({'features': serialize_doc(features)}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>/features', methods=['POST'])
@jwt_required()
def add_dept_feature(college_id, dept_id):
    try:
        user_id = get_jwt_identity()
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not user or user.get('role') not in ('admin', 'moderator'):
            return jsonify({'error': 'Unauthorized'}), 403
            
        data = request.get_json()
        feature = {
            'dept_id': ObjectId(dept_id),
            'college_id': ObjectId(college_id),
            'title': data.get('title'),
            'icon': data.get('icon', '✨'),
            'description': data.get('description'),
            'stat_value': data.get('stat_value', ''),
            'order': data.get('order', 0),
            'added_by': ObjectId(user_id),
            'created_at': datetime.utcnow()
        }
        mongo.db.dept_features.insert_one(feature)
        return jsonify({'message': 'Feature added'}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>/features/<feature_id>', methods=['GET'])
def get_single_dept_feature(college_id, dept_id, feature_id):
    try:
        f = mongo.db.dept_features.find_one({'_id': ObjectId(feature_id), 'dept_id': ObjectId(dept_id)})
        if not f: return jsonify({'error': 'Not found'}), 404
        f['_id'] = str(f['_id'])
        f['dept_id'] = str(f['dept_id'])
        f['college_id'] = str(f['college_id'])
        return jsonify(f), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>/features/<feature_id>', methods=['PUT'])
@jwt_required()
def update_dept_feature(college_id, dept_id, feature_id):
    try:
        user_id = get_jwt_identity()
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not user or user.get('role') not in ('admin', 'moderator'):
            return jsonify({'error': 'Unauthorized'}), 403
            
        data = request.get_json()
        update_fields = {}
        if 'title' in data: update_fields['title'] = data['title']
        if 'description' in data: update_fields['description'] = data['description']
        if 'icon' in data: update_fields['icon'] = data['icon']
        if 'stat_value' in data: update_fields['stat_value'] = data['stat_value']
        
        mongo.db.dept_features.update_one(
            {'_id': ObjectId(feature_id), 'dept_id': ObjectId(dept_id)},
            {'$set': update_fields}
        )
        return jsonify({'message': 'Feature updated'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>/features/<feature_id>', methods=['DELETE'])
@jwt_required()
def delete_dept_feature(college_id, dept_id, feature_id):
    try:
        user_id = get_jwt_identity()
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not user or user.get('role') not in ('admin', 'moderator'):
            return jsonify({'error': 'Unauthorized'}), 403
            
        mongo.db.dept_features.delete_one({
            '_id': ObjectId(feature_id), 
            'dept_id': ObjectId(dept_id)
        })
        return jsonify({'message': 'Feature deleted'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>/gallery', methods=['POST'])
@jwt_required()
def add_dept_gallery(college_id, dept_id):
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        photo = {
            'college_id': ObjectId(college_id),
            'dept_id': ObjectId(dept_id),
            'user_id': ObjectId(user_id),
            'photo_url': data['photo_url'],
            'caption': data.get('caption', ''),
            'category': data.get('category', 'General'),
            'created_at': datetime.utcnow()
        }
        mongo.db.dept_gallery.insert_one(photo)
        return jsonify({'message': 'Photo added'}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>/gallery/<photo_id>', methods=['GET'])
def get_single_dept_gallery(college_id, dept_id, photo_id):
    try:
        p = mongo.db.dept_gallery.find_one({'_id': ObjectId(photo_id), 'dept_id': ObjectId(dept_id)})
        if not p: return jsonify({'error': 'Not found'}), 404
        p['_id'] = str(p['_id'])
        p['dept_id'] = str(p['dept_id'])
        p['college_id'] = str(p['college_id'])
        return jsonify(p), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>/gallery/<photo_id>', methods=['PUT'])
@jwt_required()
def update_dept_gallery(college_id, dept_id, photo_id):
    try:
        user_id = get_jwt_identity()
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not user or user.get('role') not in ('admin', 'moderator'):
            return jsonify({'error': 'Unauthorized'}), 403
            
        data = request.get_json()
        update_fields = {}
        if 'photo_url' in data: update_fields['photo_url'] = data['photo_url']
        if 'caption' in data: update_fields['caption'] = data['caption']
        if 'category' in data: update_fields['category'] = data['category']
        
        mongo.db.dept_gallery.update_one(
            {'_id': ObjectId(photo_id), 'dept_id': ObjectId(dept_id)},
            {'$set': update_fields}
        )
        return jsonify({'message': 'Gallery item updated'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>/gallery/<photo_id>', methods=['DELETE'])
@jwt_required()
def delete_dept_gallery(college_id, dept_id, photo_id):
    try:
        user_id = get_jwt_identity()
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not user or user.get('role') not in ('admin', 'moderator'):
            return jsonify({'error': 'Unauthorized'}), 403
            
        mongo.db.dept_gallery.delete_one({
            '_id': ObjectId(photo_id), 
            'dept_id': ObjectId(dept_id)
        })
        return jsonify({'message': 'Gallery item deleted'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>/gallery', methods=['GET'])
def get_dept_gallery(college_id, dept_id):
    try:
        cat = request.args.get('category')
        query = {'dept_id': ObjectId(dept_id)}
        if cat and cat != 'All': query['category'] = cat.lower()
        
        photos = list(mongo.db.dept_gallery.find(query).sort('created_at', -1))
        return jsonify({'photos': serialize_doc(photos)}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>/gallery', methods=['POST'])
@jwt_required()
def upload_dept_photo(college_id, dept_id):
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        photo = {
            'dept_id': ObjectId(dept_id),
            'photo_url': data.get('photo_url'),
            'caption': data.get('caption', ''),
            'category': data.get('category', 'events').lower(),
            'uploaded_by': ObjectId(user_id),
            'created_at': datetime.utcnow()
        }
        mongo.db.dept_gallery.insert_one(photo)
        return jsonify({'message': 'Photo uploaded'}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>/alumni', methods=['GET'])
def get_dept_alumni(college_id, dept_id):
    try:
        year = request.args.get('year')
        query = {'dept_id': ObjectId(dept_id), 'college_id': ObjectId(college_id)}
        if year and str(year).isdigit():
            query['batch_year'] = int(year)
            
        alumni = list(mongo.db.dept_alumni.find(query).sort('package_lpa', -1))
        return jsonify({'alumni': serialize_doc(alumni)}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>/alumni', methods=['POST'])
@jwt_required()
def add_dept_alumni(college_id, dept_id):
    try:
        user_id = get_jwt_identity()
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not user or user.get('role') not in ('admin', 'moderator'):
            return jsonify({'error': 'Unauthorized'}), 403
            
        data = request.get_json()
        
        # Handle optional package_lpa safely
        try:
            package_lpa = float(data.get('package_lpa')) if data.get('package_lpa') else None
        except (ValueError, TypeError):
            package_lpa = None
            
        alumni = {
            'dept_id': ObjectId(dept_id),
            'college_id': ObjectId(college_id),
            'name': data.get('name'),
            'photo_url': data.get('photo_url', ''),
            'batch_year': int(data.get('batch_year', 0)),
            'company': data.get('company', ''),
            'role': data.get('role', ''),
            'package_lpa': package_lpa,
            'location': data.get('location', ''),
            'quote': data.get('quote', ''),
            'skills_used': data.get('skills_used', []),
            'social_links': data.get('social_links', {}),
            'is_anonymous': bool(data.get('is_anonymous', False)),
            'added_by': ObjectId(user_id),
            'created_at': datetime.utcnow()
        }
        mongo.db.dept_alumni.insert_one(alumni)
        return jsonify({'message': 'Alumni added'}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>/alumni/<alumni_id>', methods=['GET'])
def get_single_dept_alumni(college_id, dept_id, alumni_id):
    try:
        if not ObjectId.is_valid(alumni_id):
            return jsonify({'error': 'Invalid ID format'}), 404
        a = mongo.db.dept_alumni.find_one({'_id': ObjectId(alumni_id), 'dept_id': ObjectId(dept_id)})
        if not a: return jsonify({'error': 'Not found'}), 404
        return jsonify(serialize_doc(a)), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>/alumni/<alumni_id>', methods=['PUT'])
@jwt_required()
def update_dept_alumni(college_id, dept_id, alumni_id):
    try:
        user_id = get_jwt_identity()
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not user or user.get('role') not in ('admin', 'moderator'):
            return jsonify({'error': 'Unauthorized'}), 403
            
        data = request.get_json()
        update_fields = {}
        if 'name' in data: update_fields['name'] = data['name']
        if 'photo_url' in data: update_fields['photo_url'] = data['photo_url']
        if 'batch_year' in data: update_fields['batch_year'] = int(data['batch_year'])
        if 'company' in data: update_fields['company'] = data['company']
        if 'role' in data: update_fields['role'] = data['role']
        if 'package_lpa' in data: update_fields['package_lpa'] = float(data['package_lpa']) if data['package_lpa'] else None
        if 'quote' in data: update_fields['quote'] = data['quote']
        if 'social_links' in data: update_fields['social_links'] = data['social_links']
        
        mongo.db.dept_alumni.update_one(
            {'_id': ObjectId(alumni_id), 'dept_id': ObjectId(dept_id)},
            {'$set': update_fields}
        )
        return jsonify({'message': 'Alumni updated'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>/alumni/<alumni_id>', methods=['DELETE'])
@jwt_required()
def delete_dept_alumni(college_id, dept_id, alumni_id):
    try:
        user_id = get_jwt_identity()
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not user or user.get('role') not in ('admin', 'moderator'):
            return jsonify({'error': 'Unauthorized'}), 403
            
        mongo.db.dept_alumni.delete_one({
            '_id': ObjectId(alumni_id), 
            'dept_id': ObjectId(dept_id),
            'college_id': ObjectId(college_id)
        })
        return jsonify({'message': 'Alumni deleted'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/join', methods=['POST'])
@jwt_required()
def join_college(college_id):
    try:
        data = request.get_json(silent=True) or {}
        user_id = get_jwt_identity()
        dept_id = data.get('department_id')

        existing = mongo.db.college_members.find_one({'user_id': ObjectId(user_id), 'college_id': ObjectId(college_id)})
        if existing:
            return jsonify({'message': 'Already joined'}), 200

        member = {
            'user_id': ObjectId(user_id),
            'college_id': ObjectId(college_id),
            'department_id': ObjectId(dept_id) if dept_id else None,
            'year': data.get('year', 1),
            'role': data.get('role', 'student'),
            'joined_at': datetime.utcnow()
        }
        mongo.db.college_members.insert_one(member)
        mongo.db.users.update_one({'_id': ObjectId(user_id)}, {'$set': {'college_id': ObjectId(college_id)}})
        
        mongo.db.colleges.update_one({'_id': ObjectId(college_id)}, {'$inc': {'stats.total_students': 1}})
        if dept_id:
            mongo.db.departments.update_one({'_id': ObjectId(dept_id)}, {'$inc': {'stats.total_members': 1}})

        return jsonify({'message': 'Joined successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/posts/', methods=['GET'])
def get_posts(college_id):
    try:
        dept_id = request.args.get('dept_id')
        post_type = request.args.get('type')
        sort = request.args.get('sort', 'newest')
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 10))
        skip = (page - 1) * limit

        query = {'college_id': ObjectId(college_id), 'is_hidden': {'$ne': True}}
        if dept_id and dept_id != 'all': 
            query['department_id'] = ObjectId(dept_id)
        if post_type and post_type != 'all': query['post_type'] = post_type

        sort_stage = [('created_at', -1)]
        if sort == 'popular': sort_stage = [('views', -1), ('upvotes', -1)]
        elif sort == 'pinned': sort_stage = [('is_pinned', -1), ('created_at', -1)]

        posts = list(mongo.db.college_posts.find(query).sort(sort_stage).skip(skip).limit(limit))
        
        for p in posts:
            p['author_info'] = None
            if not p.get('is_anonymous') and p.get('author'):
                user = mongo.db.users.find_one({'_id': p['author']}, {'name': 1, 'avatar_url': 1})
                if user:
                    p['author_info'] = user

        return jsonify(serialize_doc(posts)), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/posts/', methods=['POST'])
@jwt_required()
def create_post(college_id):
    try:
        data = request.get_json(silent=True) or {}
        user_id = get_jwt_identity()

        member = mongo.db.college_members.find_one({'user_id': ObjectId(user_id), 'college_id': ObjectId(college_id)})
        if not member:
            return jsonify({'error': 'Must join college first'}), 403

        dept_id = data.get('department_id')
        post_type = data.get('post_type')
        
        post = {
            'college_id': ObjectId(college_id),
            'department_id': ObjectId(dept_id) if dept_id and dept_id != 'all' else None,
            'post_type': post_type,
            'title': data.get('title', ''),
            'content': data.get('content', ''),
            'media': data.get('media', []),
            'author': ObjectId(user_id),
            'is_anonymous': bool(data.get('is_anonymous', False)),
            'upvotes': [],
            'replies': [],
            'tags': data.get('tags', []),
            'views': 0,
            'is_hidden': False,
            'is_pinned': False,
            'created_at': datetime.utcnow()
        }

        if post_type == 'review': post['rating'] = data.get('rating', {})
        elif post_type == 'event': post['event_data'] = data.get('event_data', {})
        elif post_type == 'placement_info': post['placement_data'] = data.get('placement_data', {})

        res = mongo.db.college_posts.insert_one(post)
        post['_id'] = res.inserted_id

        mongo.db.colleges.update_one({'_id': ObjectId(college_id)}, {'$inc': {'stats.total_posts': 1}})
        if dept_id and dept_id != 'all':
            mongo.db.departments.update_one({'_id': ObjectId(dept_id)}, {'$inc': {'stats.total_posts': 1}})
        
        if post_type == 'review':
            recalculate_college_ratings(college_id)

        return jsonify(serialize_doc(post)), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/upload/', methods=['POST'])
@jwt_required()
def upload_media():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file part'}), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400

        filename = secure_filename(file.filename)
        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
        
        img_exts = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
        vid_exts = {'mp4', 'mov'}
        
        if ext in img_exts: type_cat = 'image'
        elif ext in vid_exts: type_cat = 'video'
        else: return jsonify({'error': 'File type not allowed'}), 400

        upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'college')
        os.makedirs(upload_folder, exist_ok=True)

        new_filename = f"{uuid.uuid4().hex}.{ext}"
        filepath = os.path.join(upload_folder, new_filename)
        file.save(filepath)

        return jsonify({
            'url': f"/static/uploads/college/{new_filename}",
            'type': type_cat,
            'filename': filename
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/stats', methods=['GET'])
def get_directory_stats():
    try:
        total = mongo.db.colleges.count_documents({})
        cities = len(mongo.db.colleges.distinct('city'))
        states = len(mongo.db.colleges.distinct('state'))
        return jsonify({
            'total': total,
            'cities': cities,
            'states': states
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─────────────────────────────────────────────────────────────────
# ── College Profile Tab CRUD Operations (Dept, Placement, Alumni, Gallery) ──
# ─────────────────────────────────────────────────────────────────

def check_admin_or_owner(college_id, user_id, user_role):
    college = mongo.db.colleges.find_one({'_id': ObjectId(college_id)})
    if not college: return False
    is_owner = str(college.get('created_by')) == str(user_id)
    is_admin = user_role in ('admin', 'moderator')
    return is_owner or is_admin

# --- Departments ---
@colleges_bp.route('/<college_id>/departments', methods=['POST'])
@jwt_required()
def create_department_college(college_id):
    try:
        user_id = get_jwt_identity()
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not check_admin_or_owner(college_id, user_id, user.get('role')):
            return jsonify({'error': 'Forbidden'}), 403

        data = request.get_json()
        dept = {
            'college_id': ObjectId(college_id),
            'name': data.get('name', ''),
            'short_name': data.get('short_name', ''),
            'head_of_dept': data.get('head_of_dept', ''),
            'faculty_count': int(data.get('faculty_count', 0) or 0),
            'student_count': int(data.get('student_count', 0) or 0),
            'established': int(data.get('established', 0) or 0),
            'description': data.get('description', ''),
            'created_at': datetime.utcnow()
        }
        res = mongo.db.departments.insert_one(dept)
        dept['_id'] = res.inserted_id
        return jsonify(serialize_doc(dept)), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/departments/<id>', methods=['PUT', 'DELETE'])
@jwt_required()
def manage_department_college(college_id, id):
    try:
        user_id = get_jwt_identity()
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not check_admin_or_owner(college_id, user_id, user.get('role')):
            return jsonify({'error': 'Forbidden'}), 403

        if request.method == 'DELETE':
            mongo.db.departments.delete_one({'_id': ObjectId(id), 'college_id': ObjectId(college_id)})
            return jsonify({'message': 'Deleted successfully'}), 200
        
        data = request.get_json()
        update_fields = {
            'name': data.get('name', ''),
            'short_name': data.get('short_name', ''),
            'head_of_dept': data.get('head_of_dept', ''),
            'faculty_count': int(data.get('faculty_count', 0) or 0),
            'student_count': int(data.get('student_count', 0) or 0),
            'established': int(data.get('established', 0) or 0),
            'description': data.get('description', '')
        }
        mongo.db.departments.update_one({'_id': ObjectId(id), 'college_id': ObjectId(college_id)}, {'$set': update_fields})
        return jsonify({'message': 'Updated successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- Placements ---
@colleges_bp.route('/<college_id>/placements', methods=['POST'])
@jwt_required()
def create_placement_college(college_id):
    try:
        user_id = get_jwt_identity()
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not check_admin_or_owner(college_id, user_id, user.get('role')):
            return jsonify({'error': 'Forbidden'}), 403

        data = request.get_json()
        dept_id = data.get('dept_id')
        
        placement = {
            'college_id': ObjectId(college_id),
            'student_name': data.get('student_name', ''),
            'student_photo': data.get('student_photo', ''),
            'photo_url': data.get('student_photo', ''), # sync field names
            'batch_year': int(data.get('batch_year', 0) or 0),
            'department': data.get('department', ''),
            'company': data.get('company', ''),
            'company_logo': data.get('company_logo', ''),
            'role': data.get('role', ''),
            'package_lpa': float(data.get('package_lpa', 0) or 0),
            'linkedin_url': data.get('linkedin_url', ''),
            'twitter_url': data.get('twitter_url', ''),
            'instagram_url': data.get('instagram_url', ''),
            'other_social_name': data.get('other_social_name', ''),
            'other_social_url': data.get('other_social_url', ''),
            'created_at': datetime.utcnow()
        }
        
        if dept_id:
            placement['dept_id'] = ObjectId(dept_id)
            # Also get dept name if missing
            dept = mongo.db.departments.find_one({'_id': ObjectId(dept_id)})
            if dept: placement['department'] = dept.get('name', '')
            res = mongo.db.dept_placements.insert_one(placement)
        else:
            res = mongo.db.placements.insert_one(placement)
            
        placement['_id'] = res.inserted_id
        return jsonify(serialize_doc(placement)), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/placements/<id>', methods=['PUT', 'DELETE'])
@jwt_required()
def manage_placement_college(college_id, id):
    try:
        user_id = get_jwt_identity()
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not check_admin_or_owner(college_id, user_id, user.get('role')):
            return jsonify({'error': 'Forbidden'}), 403

        if request.method == 'DELETE':
            mongo.db.placements.delete_one({'_id': ObjectId(id), 'college_id': ObjectId(college_id)})
            return jsonify({'message': 'Deleted successfully'}), 200
        
        data = request.get_json()
        update_fields = {
            'student_name': data.get('student_name', ''),
            'student_photo': data.get('student_photo', ''),
            'batch_year': int(data.get('batch_year', 0) or 0),
            'department': data.get('department', ''),
            'company': data.get('company', ''),
            'company_logo': data.get('company_logo', ''),
            'role': data.get('role', ''),
            'package_lpa': float(data.get('package_lpa', 0) or 0),
            'linkedin_url': data.get('linkedin_url', ''),
            'twitter_url': data.get('twitter_url', ''),
            'instagram_url': data.get('instagram_url', ''),
            'other_social_name': data.get('other_social_name', ''),
            'other_social_url': data.get('other_social_url', ''),
        }
        mongo.db.placements.update_one({'_id': ObjectId(id), 'college_id': ObjectId(college_id)}, {'$set': update_fields})
        return jsonify({'message': 'Updated successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- Alumni ---
@colleges_bp.route('/<college_id>/alumni', methods=['POST'])
@jwt_required()
def create_alumni_college(college_id):
    try:
        user_id = get_jwt_identity()
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not check_admin_or_owner(college_id, user_id, user.get('role')):
            return jsonify({'error': 'Forbidden'}), 403

        data = request.get_json()
        dept_id = data.get('dept_id')
        
        alumni = {
            'college_id': ObjectId(college_id),
            'name': data.get('name', ''),
            'photo': data.get('photo', ''),
            'photo_url': data.get('photo', ''), # sync field names
            'batch': data.get('batch', ''),
            'batch_year': int(data.get('batch', 0) or 0), # sync field names
            'department': data.get('department', ''),
            'company': data.get('company', ''),
            'role': data.get('role', ''),
            'package': float(data.get('package', 0) or 0),
            'package_lpa': float(data.get('package', 0) or 0), # sync field names
            'is_wall_of_fame': bool(data.get('is_wall_of_fame', False)),
            'linkedin': data.get('linkedin', ''),
            'created_at': datetime.utcnow()
        }
        
        if dept_id:
            alumni['dept_id'] = ObjectId(dept_id)
            dept = mongo.db.departments.find_one({'_id': ObjectId(dept_id)})
            if dept: alumni['department'] = dept.get('name', '')
            res = mongo.db.dept_alumni.insert_one(alumni)
        else:
            res = mongo.db.alumni.insert_one(alumni)
            
        alumni['_id'] = res.inserted_id
        return jsonify(serialize_doc(alumni)), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/alumni/<id>', methods=['PUT', 'DELETE'])
@jwt_required()
def manage_alumni_college(college_id, id):
    try:
        user_id = get_jwt_identity()
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not check_admin_or_owner(college_id, user_id, user.get('role')):
            return jsonify({'error': 'Forbidden'}), 403

        if request.method == 'DELETE':
            mongo.db.alumni.delete_one({'_id': ObjectId(id), 'college_id': ObjectId(college_id)})
            return jsonify({'message': 'Deleted successfully'}), 200
        
        data = request.get_json()
        update_fields = {
            'name': data.get('name', ''),
            'photo': data.get('photo', ''),
            'batch': data.get('batch', ''),
            'department': data.get('department', ''),
            'company': data.get('company', ''),
            'role': data.get('role', ''),
            'package': float(data.get('package', 0) or 0),
            'is_wall_of_fame': bool(data.get('is_wall_of_fame', False)),
            'linkedin': data.get('linkedin', '')
        }
        mongo.db.alumni.update_one({'_id': ObjectId(id), 'college_id': ObjectId(college_id)}, {'$set': update_fields})
        return jsonify({'message': 'Updated successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- Gallery (Events) ---
@colleges_bp.route('/<college_id>/gallery', methods=['POST'])
@jwt_required()
def create_gallery_event(college_id):
    try:
        user_id = get_jwt_identity()
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not check_admin_or_owner(college_id, user_id, user.get('role')):
            return jsonify({'error': 'Forbidden'}), 403

        data = request.get_json()
        event = {
            'college_id': ObjectId(college_id),
            'title': data.get('title', ''),
            'image_url': data.get('image_url', ''),
            'date': data.get('date', ''),
            'description': data.get('description', ''),
            'created_at': datetime.utcnow()
        }
        res = mongo.db.college_events.insert_one(event)
        event['_id'] = res.inserted_id
        return jsonify(serialize_doc(event)), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/gallery/<id>', methods=['PUT', 'DELETE'])
@jwt_required()
def manage_gallery_event(college_id, id):
    try:
        user_id = get_jwt_identity()
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not check_admin_or_owner(college_id, user_id, user.get('role')):
            return jsonify({'error': 'Forbidden'}), 403

        if request.method == 'DELETE':
            mongo.db.college_events.delete_one({'_id': ObjectId(id), 'college_id': ObjectId(college_id)})
            return jsonify({'message': 'Deleted successfully'}), 200
        
        data = request.get_json()
        update_fields = {
            'title': data.get('title', ''),
            'image_url': data.get('image_url', ''),
            'date': data.get('date', ''),
            'description': data.get('description', '')
        }
        mongo.db.college_events.update_one({'_id': ObjectId(id), 'college_id': ObjectId(college_id)}, {'$set': update_fields})
        return jsonify({'message': 'Updated successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

