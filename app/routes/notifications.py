from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from bson import ObjectId
from app import mongo
from app.utils import serialize_doc, get_current_user

notifications_bp = Blueprint('notifications', __name__)


@notifications_bp.route('/', methods=['GET'])
@jwt_required()
def get_notifications():
    user = get_current_user()
    notifications = list(
        mongo.db.notifications.find({'user_id': user['_id']})
        .sort('created_at', -1)
        .limit(50)
    )
    return jsonify(serialize_doc(notifications))


@notifications_bp.route('/unread-count', methods=['GET'])
@jwt_required()
def unread_count():
    user = get_current_user()
    count = mongo.db.notifications.count_documents({'user_id': user['_id'], 'read': False})
    return jsonify({'count': count})


@notifications_bp.route('/<notif_id>/read', methods=['PATCH'])
@jwt_required()
def mark_read(notif_id):
    user = get_current_user()
    try:
        result = mongo.db.notifications.update_one(
            {'_id': ObjectId(notif_id), 'user_id': user['_id']},
            {'$set': {'read': True}}
        )
    except Exception:
        return jsonify({'message': 'Invalid notification ID'}), 400

    if result.modified_count == 0:
        return jsonify({'message': 'Notification not found'}), 404

    return jsonify({'message': 'Marked as read'})


@notifications_bp.route('/read-all', methods=['PATCH'])
@jwt_required()
def mark_all_read():
    user = get_current_user()
    mongo.db.notifications.update_many(
        {'user_id': user['_id'], 'read': False},
        {'$set': {'read': True}}
    )
    return jsonify({'message': 'All notifications marked as read'})
