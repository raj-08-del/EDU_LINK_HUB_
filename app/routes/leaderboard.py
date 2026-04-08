from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from datetime import datetime
from app import mongo

# Prefix is /api/leaderboard from __init__.py
leaderboard_bp = Blueprint('leaderboard', __name__)

def award_points(user_id, points, action_type=None):
    """
    Generic point award function.
    Awards specific points to a user for an action (e.g. post, reply).
    Updates both users and leaderboard collections, including breakdown counts.
    """
    try:
        from bson import ObjectId
        from datetime import datetime
        uid = ObjectId(str(user_id))
        
        # 1. Update points in users collection (for general profile)
        mongo.db.users.update_one(
            {"_id": uid},
            {
                "$inc": {"points": points, "total_points": points},
                "$set": {"last_active": datetime.utcnow()}
            },
            upsert=False
        )
        
        # 2. Update leaderboard collection (for rankings & breakdown)
        inc_query = {"points": points}
        if action_type:
            # Increment the specific action count in the breakdown object
            inc_query[f"breakdown.{action_type}"] = 1
            
        mongo.db.leaderboard.update_one(
            {"user_id": uid},
            {
                "$inc": inc_query,
                "$set": {"last_updated": datetime.utcnow()}
            },
            upsert=True
        )
        
        print(f">>> [Leaderboard] Awarded {points} pts to {uid} (Type: {action_type})")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("award_points ERROR:", str(e))

@leaderboard_bp.route('/api/leaderboard/seed-all', methods=['POST'])
@jwt_required()
def seed_all():
    from bson import ObjectId
    from datetime import datetime
    jwt_identity = get_jwt_identity()
    user = mongo.db.users.find_one({"_id": ObjectId(str(jwt_identity))})
    if not user or user.get('role') != 'admin':
        return jsonify({"error": "Admin only"}), 403
        
    users = list(mongo.db.users.find({}))
    count = 0
    for u in users:
        existing = mongo.db.leaderboard.find_one({"user_id": u['_id']})
        if not existing:
            mongo.db.leaderboard.insert_one({
                "user_id": u['_id'],
                "points": u.get('points', 0),
                "created_at": datetime.utcnow(),
                "last_updated": datetime.utcnow()
            })
            count += 1
    return jsonify({"message": f"Seeded {count} users"}), 200

@leaderboard_bp.route('/seed', methods=['POST'])
@jwt_required()
def seed_leaderboard():
    from datetime import datetime
    user_id = get_jwt_identity()
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not user or user.get('role') != 'admin':
        return jsonify({"error": "Admin only"}), 403
    
    users = list(mongo.db.users.find({}))
    count = 0
    for u in users:
        existing = mongo.db.leaderboard.find_one({"user_id": u['_id']})
        if not existing:
            mongo.db.leaderboard.insert_one({
                "user_id": u['_id'],
                "points": 0,
                "created_at": datetime.utcnow(),
                "last_updated": datetime.utcnow()
            })
            count += 1
    return jsonify({"message": f"Seeded {count} new leaderboard entries (Total: {len(users)})"}), 200

@leaderboard_bp.route('/api/test-points', methods=['GET'])
@jwt_required()
def test_points():
    from bson import ObjectId
    from datetime import datetime
    from flask_jwt_extended import get_jwt_identity
    try:
        uid = get_jwt_identity()
        print("Testing points for user:", uid)
        
        # Try inserting/updating leaderboard directly
        result = mongo.db.leaderboard.update_one(
            {"user_id": ObjectId(str(uid))},
            {
                "$inc": {"points": 1},
                "$set": {"last_updated": datetime.utcnow()},
                "$setOnInsert": {"created_at": datetime.utcnow()}
            },
            upsert=True
        )
        print("Matched:", result.matched_count)
        print("Modified:", result.modified_count)
        print("Upserted:", result.upserted_id)
        
        # Read back
        entry = mongo.db.leaderboard.find_one({"user_id": ObjectId(str(uid))})
        print("Current entry:", entry)
        
        return jsonify({
            "uid": uid,
            "matched": result.matched_count,
            "modified": result.modified_count,
            "upserted": str(result.upserted_id),
            "current_points": entry.get('points', 0) if entry else 0
        }), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@leaderboard_bp.route('/', methods=['GET'])
@jwt_required(optional=True)
def get_leaderboard():
    """Main API endpoint for leaderboard rankings."""
    try:
        current_user_id = get_jwt_identity()
        period = request.args.get('period', 'all')
        
        # Get top 50 users by points from 'leaderboard' collection
        lb_entries = list(
            mongo.db.leaderboard
            .find({})
            .sort('points', -1)
            .limit(50)
        )
        
        rankings = []
        for i, entry in enumerate(lb_entries):
            try:
                user = mongo.db.users.find_one(
                    {'_id': entry['user_id']},
                    {'name': 1, 'college': 1, 'avatar': 1, 'role': 1}
                )
                if not user:
                    continue
                
                is_current = (
                    current_user_id and 
                    str(entry['user_id']) == current_user_id
                )
                
                rankings.append({
                    'rank': i + 1,
                    'user_id': str(entry['user_id']),
                    'name': user.get('name', 'Student'),
                    'college': user.get('college', 'Pioneer'),
                    'avatar': user.get('avatar', ''),
                    'role': user.get('role', 'student'),
                    'total_points': entry.get('points', 0),
                    'breakdown': entry.get('breakdown', {}), # Keep for frontend dropdown
                    'is_current_user': is_current,
                    'last_updated': str(entry.get('last_updated', ''))
                })
            except Exception as ue:
                print(f'User rank error: {ue}')
                continue
        
        # Find current user rank even if outside top 50
        current_user_rank = None
        current_user_points = None
        
        if current_user_id:
            user_lb = mongo.db.leaderboard.find_one(
                {'user_id': ObjectId(current_user_id)}
            )
            
            if user_lb:
                current_user_points = user_lb.get('points', 0)
                # Count users with more points
                rank = mongo.db.leaderboard.count_documents({
                    'points': {'$gt': current_user_points}
                }) + 1
                current_user_rank = rank
            else:
                # No entry yet
                current_user_rank = "Unranked"
                current_user_points = 0
        
        return jsonify({
            'rankings': rankings,
            'current_user_rank': current_user_rank,
            'current_user_points': current_user_points,
            'period': period,
            'success': True
        }), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'success': False}), 500

@leaderboard_bp.route('/api/leaderboard/sync', methods=['POST'])
@jwt_required()
def sync_leaderboard():
    """Admin-only endpoint to force a full recalculation of all user points and breakdowns."""
    try:
        user_id = get_jwt_identity()
        admin = mongo.db.users.find_one({'_id': ObjectId(user_id), 'role': {'$in': ['admin', 'moderator']}})
        if not admin:
            return jsonify({'message': 'Admin access required'}), 403
        
        # Run the backfill logic
        backfill_all_user_points()
        
        return jsonify({
            'message': 'Leaderboard synchronized successfully',
            'success': True
        }), 200
    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500

def backfill_all_user_points():
    """Calculate points for all existing users by counting past activities with high precision."""
    print('>>> Starting intensive points backfill...')
    users = list(mongo.db.users.find({}, {'_id': 1}))
    
    for user in users:
        user_id = user['_id']
        
        # 1. Activities counting
        posts = mongo.db.community_posts.count_documents({
            '$or': [{'author': user_id}, {'author': str(user_id)}]
        })
        polls = mongo.db.community_posts.count_documents({
            'post_type': 'poll',
            '$or': [{'author': user_id}, {'author': str(user_id)}]
        })
        events = mongo.db.events.count_documents({
            '$or': [{'created_by': user_id}, {'created_by': str(user_id)}]
        })
        opps_approved = mongo.db.opportunities.count_documents({
            '$or': [{'created_by': user_id}, {'created_by': str(user_id)}],
            'status': 'approved'
        })
        
        # 2. Replies counting (using the dedicated collection)
        replies = mongo.db.community_replies.count_documents({
            '$or': [{'author': user_id}, {'author': str(user_id)}]
        })
        
        # 3. Reactions received (Upvotes)
        upvotes_received = 0
        user_posts = list(mongo.db.community_posts.find({
            '$or': [{'author': user_id}, {'author': str(user_id)}]
        }))
        for p in user_posts:
            # We now use total_reactions field if available, or fall back to reactions map
            if 'total_reactions' in p:
                upvotes_received += p.get('total_reactions', 0)
            else:
                reactions = p.get('reactions', {})
                for emoji, users_list in reactions.items():
                    upvotes_received += len(users_list)
        
        # 3b. Reactions received on OPPORTUNITIES
        user_opps = list(mongo.db.opportunities.find({
            '$or': [{'created_by': user_id}, {'created_by': str(user_id)}]
        }))
        for o in user_opps:
            upvotes_received += o.get('total_reactions', 0)
        
        # 4. Reaction points (Like points)
        # Count how many likes THIS user has given to others
        post_likes = mongo.db.reactions.count_documents({
            'user_id': user_id
        })
        
        # 5. Calculation Logic (Matching leaderboard.html weights)
        total = (
            posts * 5 +
            polls * 4 +
            events * 3 +
            opps_approved * 10 +
            replies * 2 + 
            upvotes_received * 1 +
            post_likes * 1
        )
        
        # 6. Update Leaderboard Entry
        mongo.db.leaderboard.update_one(
            {'user_id': user_id},
            {
                '$set': {
                    'points': total,
                    'last_updated': datetime.utcnow(),
                    'breakdown': {
                        'posts_created': posts,
                        'polls_created': polls,
                        'events_created': events,
                        'opportunities_approved': opps_approved,
                        'replies_posted': replies,
                        'upvotes_received': upvotes_received,
                        'post_likes': post_likes 
                    }
                }
            },
            upsert=True
        )
        
        # 7. Synchronize User Points
        mongo.db.user_points.update_one(
            {'user_id': user_id},
            {
                '$set': {
                    'total_points': total,
                    'breakdown': {
                        'posts_created': posts,
                        'polls_created': polls,
                        'events_created': events,
                        'opportunities_approved': opps_approved,
                        'replies_posted': replies,
                        'upvotes_received': upvotes_received,
                        'post_likes': post_likes
                    },
                    'updated_at': datetime.utcnow()
                }
            },
            upsert=True
        )
        print(f'✔ [Backfill] User {user_id} -> {total} pts')
    
    print(f'>>> Global Backfill Complete: {len(users)} users synchronized.')

@leaderboard_bp.route('/<user_id>', methods=['DELETE'])
@jwt_required()
def remove_from_leaderboard(user_id):
    """Admin endpoint to hide a user from the leaderboard."""
    try:
        current_user_id = get_jwt_identity()
        admin = mongo.db.users.find_one({'_id': ObjectId(current_user_id), 'role': {'$in': ['admin', 'moderator']}})
        if not admin:
            return jsonify({'message': 'Admin access required'}), 403
        
        mongo.db.users.update_one({'_id': ObjectId(user_id)}, {'$set': {'hidden_from_leaderboard': True}})
        # Also remove point record if needed or just filter it in GET
        return jsonify({'message': 'User removed from leaderboard', 'success': True}), 200
    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500

