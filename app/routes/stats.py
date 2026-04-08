from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app import mongo
from bson import ObjectId

stats_bp = Blueprint('stats', __name__)

@stats_bp.route('/summary', methods=['GET'])
@jwt_required(optional=True)
def get_stats_summary():
    """Returns global and user-specific counts for the dashboard stats grid."""
    try:
        # Global counts
        campus_events_count = mongo.db.events.count_documents({"is_hidden": {"$ne": True}})
        opportunities_count = mongo.db.opportunities.count_documents({"status": "approved", "is_archived": {"$ne": True}})
        community_posts_count = mongo.db.community_posts.count_documents({"is_hidden": {"$ne": True}, "status": {"$ne": "archived"}})
        communities_count = mongo.db.colleges.count_documents({})

        # Initialize user-specific counts
        notifications_count = 0
        study_groups_count = 0
        saved_items_count = 0
        leaderboard_rank = "Unranked"

        user_id_str = get_jwt_identity()

        if user_id_str:
            user_id = ObjectId(user_id_str)
            user = mongo.db.users.find_one({"_id": user_id})

            # Notifications
            notifications_count = mongo.db.notifications.count_documents({'user_id': user_id, 'read': False})
            
            # Study Groups
            study_groups_count = mongo.db.study_groups.count_documents({'members': user_id})

            # Saved Items (using the composite logic from dashboard_page)
            if user:
                bookmarks_in_user = len(user.get('bookmarks', []))
                saved_items_field = len(user.get('saved_items', []))
                
                # Check counts in bookmarks collection
                count_userId_oid = mongo.db.bookmarks.count_documents({"userId": user_id})
                count_userId_str = mongo.db.bookmarks.count_documents({"userId": user_id_str})
                count_user_id_oid = mongo.db.bookmarks.count_documents({"user_id": user_id})
                count_user_id_str = mongo.db.bookmarks.count_documents({"user_id": user_id_str})
                
                bookmarks_in_collection = max(count_userId_oid, count_userId_str, count_user_id_oid, count_user_id_str)
                saved_items_count = max(bookmarks_in_user, bookmarks_in_collection, saved_items_field)

            # Leaderboard Rank
            user_lb = mongo.db.leaderboard.find_one({'user_id': user_id})
            if user_lb:
                pts = user_lb.get('points', 0)
                higher_count = mongo.db.leaderboard.count_documents({'points': {'$gt': pts}})
                leaderboard_rank = f"#{higher_count + 1}"

        return jsonify({
            "campus_events_count": campus_events_count,
            "opportunities_count": opportunities_count,
            "community_posts_count": community_posts_count,
            "communities_count": communities_count,
            "notifications_count": notifications_count,
            "study_groups_count": study_groups_count,
            "saved_items_count": saved_items_count,
            "leaderboard_rank": leaderboard_rank
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
