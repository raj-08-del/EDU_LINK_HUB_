from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from app import mongo
from app.utils import serialize_doc, get_current_user, role_required
from bson import ObjectId
from datetime import datetime, timedelta

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/stats', methods=['GET'])
@jwt_required()
@role_required('admin', 'moderator')
def get_stats():
    now = datetime.utcnow()
    last_week = now - timedelta(days=7)
    
    # ── Report Title Resolver Helper ──
    def get_item_title(item_type, item_id):
        try:
            if item_type == 'community_post':
                doc = mongo.db.community_posts.find_one({'_id': ObjectId(item_id)}, {'title': 1})
                return doc.get('title') if doc else 'Post Deleted'
            elif item_type == 'opportunity':
                doc = mongo.db.opportunities.find_one({'_id': ObjectId(item_id)}, {'company': 1, 'role': 1})
                return f"{doc.get('company')} - {doc.get('role')}" if doc else 'Opportunity Deleted'
            elif item_type == 'event':
                doc = mongo.db.events.find_one({'_id': ObjectId(item_id)}, {'title': 1})
                return doc.get('title') if doc else 'Event Deleted'
            elif item_type == 'chat_message':
                doc = mongo.db.chat_messages.find_one({'_id': ObjectId(item_id)}, {'content': 1})
                return doc.get('content')[:30] + "..." if doc else 'Message Deleted'
            elif item_type == 'study_group':
                doc = mongo.db.study_groups.find_one({'_id': ObjectId(item_id)}, {'name': 1})
                return doc.get('name') if doc else 'Group Deleted'
            return 'Unknown Content'
        except:
            return 'Resolution Error'

    # ── Basic Stats ──
    stats = {
        'users': mongo.db.users.count_documents({}),
        'new_users_this_week': mongo.db.users.count_documents({'created_at': {'$gte': last_week}}),
        'reports': mongo.db.reports.count_documents({}),
        'pending_reports': mongo.db.reports.count_documents({'status': 'pending'}),
        'pending_opportunities': mongo.db.opportunities.count_documents({'status': 'pending'}),
        'events': mongo.db.events.count_documents({}),
        'opportunities': mongo.db.opportunities.count_documents({}),
        'auto_events': mongo.db.events.count_documents({'is_auto_collected': True}),
        'auto_opps': mongo.db.opportunities.count_documents({'is_auto_collected': True}),
        'community_posts': mongo.db.community_posts.count_documents({}),
        'chat_messages': mongo.db.chat_messages.count_documents({}),
    }

    # ── Role Counts ──
    pipeline = [{'$group': {'_id': '$role', 'count': {'$sum': 1}}}]
    role_counts = {r['_id']: r['count'] for r in mongo.db.users.aggregate(pipeline)}
    stats['role_counts'] = {
        'admin': role_counts.get('admin', 0),
        'student': role_counts.get('student', 0),
        'moderator': role_counts.get('moderator', 0)
    }

    # ── Recent Users ──
    recent_users = list(mongo.db.users.find({}, {'name': 1, 'avatar': 1, 'role': 1})
                        .sort('created_at', -1).limit(4))
    stats['recent_users'] = serialize_doc(recent_users)

    # ── Pending Reports Logs ──
    pending_reports = list(mongo.db.reports.find({'status': 'pending'}).sort('createdAt', -1).limit(20))
    stats['pending_report_logs'] = serialize_doc(pending_reports)

    return jsonify(stats)


@admin_bp.route('/users', methods=['GET'])
@jwt_required()
@role_required('admin', 'moderator')
def get_users():
    search = request.args.get('search')
    role = request.args.get('role')
    limit = int(request.args.get('limit', 100))

    query = {}
    if role:
        query['role'] = role
    if search:
        query['$or'] = [
            {'name': {'$regex': search, '$options': 'i'}},
            {'email': {'$regex': search, '$options': 'i'}},
        ]

    users = list(mongo.db.users.find(query, {'password': 0}).sort('created_at', -1).limit(limit))
    return jsonify(serialize_doc(users))


@admin_bp.route('/users/<user_id>/role', methods=['PATCH'])
@jwt_required()
@role_required('admin', 'moderator')
def change_role(user_id):
    data = request.get_json()
    role = data.get('role')

    if role not in ['student', 'moderator', 'admin']:
        return jsonify({'message': 'Invalid role'}), 400

    try:
        result = mongo.db.users.update_one(
            {'_id': ObjectId(user_id)},
            {'$set': {'role': role}}
        )
    except Exception:
        return jsonify({'message': 'Invalid user ID'}), 400

    if result.modified_count == 0:
        return jsonify({'message': 'User not found or role unchanged'}), 404

    user = mongo.db.users.find_one({'_id': ObjectId(user_id)}, {'password': 0})
    return jsonify(serialize_doc(user))


@admin_bp.route('/users/<user_id>', methods=['DELETE'])
@jwt_required()
@role_required('admin', 'moderator')
def delete_user(user_id):
    try:
        result = mongo.db.users.delete_one({'_id': ObjectId(user_id)})
    except Exception:
        return jsonify({'message': 'Invalid user ID'}), 400

    if result.deleted_count == 0:
        return jsonify({'message': 'User not found'}), 404

    return jsonify({'message': 'User deleted'})


# ── F8: Verified Organizer Badge ──────────────────────────────────────────────
@admin_bp.route('/users/<user_id>/verify-organizer', methods=['PATCH'])
@jwt_required()
@role_required('admin', 'moderator')
def verify_organizer(user_id):
    reviewer = get_current_user()
    try:
        target = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    except Exception:
        return jsonify({'message': 'Invalid user ID'}), 400

    if not target:
        return jsonify({'message': 'User not found'}), 404

    currently_verified = target.get('is_verified_organizer', False)

    if currently_verified:
        # Un-verify
        mongo.db.users.update_one(
            {'_id': ObjectId(user_id)},
            {'$set': {
                'is_verified_organizer': False,
                'verified_organizer_at': None,
                'verified_by': None,
            }}
        )
        action = 'unverified'
    else:
        # Verify
        mongo.db.users.update_one(
            {'_id': ObjectId(user_id)},
            {'$set': {
                'is_verified_organizer': True,
                'verified_organizer_at': datetime.utcnow(),
                'verified_by': reviewer['_id'],
            }}
        )
        action = 'verified'

    updated = mongo.db.users.find_one({'_id': ObjectId(user_id)}, {'password': 0})
    return jsonify({'action': action, 'user': serialize_doc(updated)})



# NEW: GET /api/admin/hidden-content (Fix 3)
@admin_bp.route('/hidden-content', methods=['GET'])
@jwt_required()
@role_required('admin', 'moderator')
def get_hidden_content():
    # Fetch hidden items from all 3 collections
    hidden_events = list(mongo.db.events.find({'is_hidden': True}))
    hidden_opps = list(mongo.db.opportunities.find({'is_hidden': True}))
    hidden_posts = list(mongo.db.community_posts.find({'is_hidden': True}))
    
    combined = []
    
    for e in hidden_events:
        item = serialize_doc(e)
        item['type'] = 'event'
        creator = mongo.db.users.find_one({'_id': e.get('created_by')}, {'name': 1})
        item['creator_name'] = creator['name'] if creator else 'Unknown'
        combined.append(item)
        
    for o in hidden_opps:
        item = serialize_doc(o)
        item['type'] = 'opportunity'
        item['title'] = f"{o.get('company')} - {o.get('role')}"
        creator = mongo.db.users.find_one({'_id': o.get('created_by')}, {'name': 1})
        item['creator_name'] = creator['name'] if creator else 'Unknown'
        combined.append(item)
        
    for p in hidden_posts:
        item = serialize_doc(p)
        item['type'] = 'post'
        creator = mongo.db.users.find_one({'_id': p.get('author')}, {'name': 1})
        item['creator_name'] = creator['name'] if creator else 'Unknown'
        combined.append(item)
        
    # Sort by hidden_at desc
    combined.sort(key=lambda x: x.get('hidden_at', ''), reverse=True)
    
    return jsonify(combined)


@admin_bp.route('/reports/counts', methods=['GET'])
@jwt_required()
@role_required('admin')
def get_report_counts():
    """Return counts for report filtering tabs."""
    try:
        pending = mongo.db.reports.count_documents({'status': 'pending'})
        resolved = mongo.db.reports.count_documents({'status': 'resolved'})
        total = mongo.db.reports.count_documents({})
        return jsonify({
            'pending': pending,
            'resolved': resolved,
            'total': total
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@admin_bp.route('/collect-now', methods=['POST'])
@jwt_required()
@role_required('admin')
def trigger_collection():
    from app.services.auto_collector import run_all_collectors
    import os
    import threading

    config = {
        "ADZUNA_APP_ID": os.getenv("ADZUNA_APP_ID", ""),
        "ADZUNA_APP_KEY": os.getenv("ADZUNA_APP_KEY", "")
    }

    def run_in_background():
        try:
            run_all_collectors(mongo, config)
            print("[AutoCollector] Manual collection completed.")
        except Exception as e:
            print(f"[AutoCollector] Manual collection error: {e}")

    t = threading.Thread(target=run_in_background, daemon=True)
    t.start()

    return jsonify({"message": "✅ Auto Collector started in background. Check logs for progress."}), 202
