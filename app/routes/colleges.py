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
        sort = request.args.get('sort', 'rating') # newest / most_active
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 12))
        skip = (page - 1) * limit

        query = {}
        if search:
            query['$or'] = [
                {'name': {'$regex': search, '$options': 'i'}},
                {'short_name': {'$regex': search, '$options': 'i'}},
                {'city': {'$regex': search, '$options': 'i'}}
            ]
        if ctype and ctype.lower() != 'all': query['type'] = ctype.lower()
        if city and city.lower() != 'all cities': query['city'] = re.compile(f'^{city}$', re.I)
        if state and state.lower() != 'all states': query['state'] = re.compile(f'^{state}$', re.I)

        sort_stage = [('ratings.overall', -1)]
        if sort == 'newest': sort_stage = [('created_at', -1)]
        elif sort == 'most_active': sort_stage = [('stats.total_posts', -1)]

        total = mongo.db.colleges.count_documents(query)
        colleges = list(mongo.db.colleges.find(query).sort(sort_stage).skip(skip).limit(limit))

        # Safe access and serialization
        result = []
        for c in colleges:
            try:
                c['_id'] = str(c['_id'])
                if c.get('created_by'):
                    c['created_by'] = str(c['created_by'])
                
                # Ensure ratings exists
                if 'ratings' not in c or not c['ratings']:
                    c['ratings'] = {
                        'overall': 0, 'academics': 0, 'placements': 0,
                        'infrastructure': 0, 'faculty': 0, 'campus_life': 0, 'total_reviews': 0
                    }
                # Ensure stats exists
                if 'stats' not in c or not c['stats']:
                    c['stats'] = {
                        'total_students': 0, 'total_departments': 0, 'total_posts': 0,
                        'avg_package': 'N/A', 'top_recruiters': []
                    }
                result.append(c)
            except Exception as ce:
                print(f'College serialize error: {ce}')
                continue

        print(f"GET /colleges/ fetched {len(result)} colleges")
        return jsonify({
            'colleges': result,
            'total': total,
            'page': page,
            'total_pages': (total + limit - 1) // limit
        }), 200
    except Exception as e:
        import traceback
        print(f'GET COLLEGES ERROR: {e}')
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/search', methods=['GET'])
def search_colleges():
    try:
        q = request.args.get('q', '').strip()
        if len(q) < 2:
            return jsonify([])
        
        query = {'$or': [
            {'name': {'$regex': q, '$options': 'i'}},
            {'short_name': {'$regex': q, '$options': 'i'}},
            {'city': {'$regex': q, '$options': 'i'}}
        ]}
        colleges = list(mongo.db.colleges.find(
            query,
            {'_id': 1, 'name': 1, 'short_name': 1, 'city': 1, 'ratings.overall': 1, 'is_verified': 1, 'type': 1, 'state': 1, 'stats.avg_package': 1, 'ratings.academics': 1, 'ratings.placements': 1, 'ratings.infrastructure': 1, 'ratings.faculty': 1, 'ratings.total_reviews': 1}
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

@colleges_bp.route('/', methods=['POST'])
@jwt_required()
def create_college():
    try:
        data = request.get_json(silent=True) or {}
        user_id = get_jwt_identity()
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not user or user.get('role') != 'admin':
            return jsonify({'error': 'Admin only'}), 403

        name = data.get('name')
        if not name:
            return jsonify({'error': 'Name required'}), 400

        college = {
            'name': name,
            'slug': get_slug(name),
            'short_name': data.get('short_name', ''),
            'city': data.get('city', ''),
            'state': data.get('state', ''),
            'type': data.get('type', 'private'),
            'established': int(data.get('established', 0)),
            'website': data.get('website', ''),
            'logo_url': data.get('logo_url', ''),
            'description': data.get('description', ''),
            'ratings': {
                'overall': 0.0, 'academics': 0.0, 'placements': 0.0,
                'infrastructure': 0.0, 'faculty': 0.0, 'campus_life': 0.0, 'total_reviews': 0
            },
            'stats': {
                'total_students': 0, 'total_departments': 0, 'total_posts': 0,
                'avg_package': data.get('avg_package', ''), 'top_recruiters': data.get('top_recruiters', [])
            },
            'is_verified': data.get('is_verified', False),
            'created_at': datetime.utcnow()
        }
        res = mongo.db.colleges.insert_one(college)
        college['_id'] = res.inserted_id
        return jsonify(serialize_doc(college)), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/departments', methods=['GET'])
def get_departments(college_id):
    try:
        depts = list(mongo.db.departments.find({'college_id': ObjectId(college_id)}))
        return jsonify(serialize_doc(depts)), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/departments/', methods=['POST'])
@jwt_required()
def create_department(college_id):
    try:
        data = request.get_json(silent=True) or {}
        user_id = get_jwt_identity()
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not user or user.get('role') != 'admin':
            return jsonify({'error': 'Admin only'}), 403

        dept = {
            'college_id': ObjectId(college_id),
            'name': data.get('name'),
            'short_name': data.get('short_name', ''),
            'description': data.get('description', ''),
            'stats': {'total_members': 0, 'total_posts': 0},
            'created_at': datetime.utcnow()
        }
        res = mongo.db.departments.insert_one(dept)
        mongo.db.colleges.update_one({'_id': ObjectId(college_id)}, {'$inc': {'stats.total_departments': 1}})
        dept['_id'] = res.inserted_id
        return jsonify(serialize_doc(dept)), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/<college_id>/dept/<dept_id>', methods=['GET'])
def get_department(college_id, dept_id):
    try:
        print(f"GET DEPT: college_id={college_id}, dept_id={dept_id}")
        if not college_id or college_id == 'all':
            return jsonify({'error': 'Invalid college ID'}), 404
        if not dept_id or dept_id == 'all':
            return jsonify({'error': 'Invalid dept ID'}), 404
        
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

        # Serialize IDs safely
        dept['_id'] = str(dept['_id'])
        dept['college_id'] = str(dept['college_id'])

        return jsonify(serialize_doc(dept)), 200
    except Exception as e:
        print(f'GET DEPT ERROR: {e}')
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

# ── Post Routes ──

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
            # Award points for college review
            try:
                from app.routes.leaderboard import award_points
                award_points(str(user_id), 'college_review')
            except Exception as e:
                print(f"Points award error: {e}")

        return jsonify(serialize_doc(post)), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/posts/<post_id>/upvote', methods=['PATCH'])
@jwt_required()
def toggle_upvote(post_id):
    try:
        user_id = get_jwt_identity()
        post = mongo.db.college_posts.find_one({'_id': ObjectId(post_id)})
        if not post:
            return jsonify({'error': 'Not found'}), 404

        upvotes = post.get('upvotes', [])
        uid_obj = ObjectId(user_id)
        if uid_obj in upvotes:
            mongo.db.college_posts.update_one({'_id': ObjectId(post_id)}, {'$pull': {'upvotes': uid_obj}})
            status = 'removed'
            pts = -2
        else:
            mongo.db.college_posts.update_one({'_id': ObjectId(post_id)}, {'$push': {'upvotes': uid_obj}})
            status = 'added'
            pts = 2

        # Award/remove points for the author of the post
        try:
            from app.routes.leaderboard import award_points
            award_points(str(post['author']), 'receive_upvote', points=pts)
        except Exception as e:
            print(f"Points award error: {e}")

        return jsonify({'status': status}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/posts/<post_id>/reply', methods=['POST'])
@jwt_required()
def add_reply(post_id):
    try:
        data = request.get_json(silent=True) or {}
        user_id = get_jwt_identity()
        
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        
        reply = {
            '_id': ObjectId(), 
            'author': ObjectId(user_id),
            'author_name': user.get('name', 'User') if not data.get('is_anonymous') else 'Anonymous',
            'content': data.get('content', ''),
            'is_anonymous': bool(data.get('is_anonymous', False)),
            'created_at': datetime.utcnow()
        }

        mongo.db.college_posts.update_one({'_id': ObjectId(post_id)}, {'$push': {'replies': reply}})
        return jsonify(serialize_doc(reply)), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/posts/<post_id>', methods=['DELETE'])
@jwt_required()
def delete_post(post_id):
    try:
        user_id = get_jwt_identity()
        post = mongo.db.college_posts.find_one({'_id': ObjectId(post_id)})
        if not post:
            return jsonify({'error': 'Not found'}), 404

        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if post.get('author') != ObjectId(user_id) and user.get('role') != 'admin':
            return jsonify({'error': 'Unauthorized'}), 403

        mongo.db.college_posts.delete_one({'_id': ObjectId(post_id)})
        
        mongo.db.colleges.update_one({'_id': post['college_id']}, {'$inc': {'stats.total_posts': -1}})
        if post.get('department_id'):
            mongo.db.departments.update_one({'_id': post['department_id']}, {'$inc': {'stats.total_posts': -1}})
        if post.get('post_type') == 'review':
            recalculate_college_ratings(post['college_id'])

        return jsonify({'message': 'Deleted'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@colleges_bp.route('/posts/<post_id>/rsvp', methods=['POST'])
@jwt_required()
def rsvp_event(post_id):
    try:
        user_id = get_jwt_identity()
        post = mongo.db.college_posts.find_one({'_id': ObjectId(post_id)})
        if not post or post.get('post_type') != 'event':
            return jsonify({'error': 'Not an event'}), 400

        rsvps = post.get('event_data', {}).get('rsvp_users', [])
        uid_obj = ObjectId(user_id)
        if uid_obj in rsvps:
            mongo.db.college_posts.update_one({'_id': ObjectId(post_id)}, {'$pull': {'event_data.rsvp_users': uid_obj}})
            status = 'removed'
            pts = -1
        else:
            mongo.db.college_posts.update_one({'_id': ObjectId(post_id)}, {'$push': {'event_data.rsvp_users': uid_obj}})
            status = 'added'
            pts = 1

        # Award points for event RSVP
        try:
            from app.routes.leaderboard import award_points
            award_points(str(user_id), 'event_rsvp', points=pts)
        except Exception as e:
            print(f"Points award error: {e}")

        return jsonify({'status': status}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── Media Upload ──

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
        aud_exts = {'mp3', 'wav', 'ogg'}
        doc_exts = {'pdf', 'doc', 'docx', 'ppt', 'pptx'}

        if ext in img_exts: type_cat = 'image'
        elif ext in vid_exts: type_cat = 'video'
        elif ext in aud_exts: type_cat = 'audio'
        elif ext in doc_exts: type_cat = 'document'
        else: return jsonify({'error': 'File type not allowed'}), 400

        upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'college')
        os.makedirs(upload_folder, exist_ok=True)

        new_filename = f"{uuid.uuid4().hex}.{ext}"
        filepath = os.path.join(upload_folder, new_filename)
        file.save(filepath)

        size_bytes = os.path.getsize(filepath)

        return jsonify({
            'url': f"/static/uploads/college/{new_filename}",
            'type': type_cat,
            'filename': filename,
            'size_bytes': size_bytes
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500
