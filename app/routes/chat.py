from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from datetime import datetime
from app import mongo
from app.utils import serialize_doc, get_current_user

chat_bp = Blueprint('chat', __name__)

DEFAULT_CHANNELS = [
    {'name': 'General', 'slug': 'general', 'description': 'General discussion for all students', 'order': 1},
    {'name': 'Career & Internships', 'slug': 'career-internships', 'description': 'Discuss placements, internships, and career tips', 'order': 3},
]


def _seed_channels():
    """Auto-seed default channels and remove those not in DEFAULT_CHANNELS."""
    # 1. Ensure defaults exist
    for ch in DEFAULT_CHANNELS:
        ch_copy = ch.copy()
        ch_copy['created_at'] = datetime.utcnow()
        mongo.db.chat_channels.update_one(
            {'slug': ch['slug']},
            {'$setOnInsert': ch_copy},
            upsert=True
        )
    
    # 2. Cleanup: Delete any channel NOT in DEFAULT_CHANNELS
    valid_slugs = [ch['slug'] for ch in DEFAULT_CHANNELS]
    mongo.db.chat_channels.delete_many({'slug': {'$nin': valid_slugs}})


@chat_bp.route('/channels', methods=['GET'])
@jwt_required()
def get_channels():
    _seed_channels()
    channels = list(mongo.db.chat_channels.find().sort('order', 1))
    return jsonify(serialize_doc(channels))


@chat_bp.route('/channels/<slug>/messages', methods=['GET'])
@jwt_required()
def get_messages(slug):
    _seed_channels()
    channel = mongo.db.chat_channels.find_one({'slug': slug})
    if not channel:
        return jsonify({'message': 'Channel not found'}), 404

    # Get last 50 messages
    messages = list(
        mongo.db.chat_messages
        .find({'channel_id': channel['_id']})
        .sort('created_at', 1)
        .limit(50)
    )
    return jsonify(serialize_doc(messages))


@chat_bp.route('/channels/<slug>/messages', methods=['POST'])
@jwt_required()
def send_message(slug):
    user = get_current_user()
    _seed_channels()
    channel = mongo.db.chat_channels.find_one({'slug': slug})
    if not channel:
        return jsonify({'message': 'Channel not found'}), 404

    data = request.get_json()
    content = data.get('content', '').strip()
    reply_to_id = data.get('reply_to_id')
    q_reply_id = data.get('q_reply_id')
    if not content:
        return jsonify({'message': 'Message content is required'}), 400

    message = {
        'channel_id': channel['_id'],
        'author': user['_id'],
        'author_name': user.get('name', 'Student'),
        'author_avatar': user.get('avatar'),
        'content': content,
        'created_at': datetime.utcnow(),
    }

    if reply_to_id:
        try:
            parent = mongo.db.chat_messages.find_one({'_id': ObjectId(reply_to_id)})
            if parent:
                message['reply_to'] = parent['_id']
                message['reply_author'] = parent.get('author_name', 'Student')
                # Store a snippet for context
                message['reply_content'] = (parent.get('content', '')[:100] + '...') if len(parent.get('content', '')) > 100 else parent.get('content', '')
        except Exception:
            pass

    if q_reply_id:
        try:
            # Check both community posts AND opportunities
            post = mongo.db.community_posts.find_one({'_id': ObjectId(q_reply_id)})
            model = 'community_posts'
            
            if not post:
                post = mongo.db.opportunities.find_one({'_id': ObjectId(q_reply_id)})
                model = 'opportunities'
                
            if post:
                # Add context to message
                message['q_reply_id'] = post['_id']
                message['q_reply_title'] = post.get('title') or f"{post.get('role')} at {post.get('company')}"

                # Notify uploader
                from app.services.notification_service import create_notification
                if str(post.get('author') or post.get('created_by')) != str(user['_id']):
                    author_id = post.get('author') or post.get('created_by')
                    if author_id:
                        create_notification(
                            user_id=author_id,
                            notif_type='chat_reply',
                            message=f'Students are discussing your post "{message["q_reply_title"]}" in Chat!',
                            post_ref=post['_id'],
                            post_model=model,
                            extra_data={'channel_slug': slug}
                        )
        except Exception:
            pass

    result = mongo.db.chat_messages.insert_one(message)
    message['_id'] = result.inserted_id
    return jsonify(serialize_doc(message)), 201


@chat_bp.route('/messages/<message_id>', methods=['DELETE'])
@jwt_required()
def delete_message(message_id):
    try:
        user_id = get_jwt_identity()
        user_doc = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        user_role = (user_doc.get('role') or '').lower() if user_doc else 'student'
        
        msg = mongo.db.chat_messages.find_one({'_id': ObjectId(message_id)})
        if not msg:
            return jsonify({'message': 'Message not found'}), 404
        
        # Identity check: owner or admin
        if str(msg['author']) != str(user_id) and user_role not in ['admin', 'moderator']:
            return jsonify({'message': 'Unauthorized'}), 403
        
        mongo.db.chat_messages.delete_one({'_id': ObjectId(message_id)})
        return jsonify({'message': 'Message deleted successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
