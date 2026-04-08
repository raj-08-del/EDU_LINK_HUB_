from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app import mongo
from app.utils import serialize_doc
from bson import ObjectId
from datetime import datetime
import uuid

study_groups_bp = Blueprint('study_groups', __name__)

@study_groups_bp.route('/', methods=['POST'])
@jwt_required()
def create_group():
    user_id = ObjectId(get_jwt_identity())
    data = request.get_json()
    
    if not data or not data.get('name') or not data.get('subject'):
        return jsonify({'message': 'Group name and subject are required'}), 400
        
    group = {
        'name': data.get('name').strip(),
        'description': data.get('description', '').strip(),
        'subject': data.get('subject').strip(),
        'is_private': bool(data.get('is_private', False)),
        'created_by': user_id,
        'members': [user_id],
        'pinned_resources': [],
        'created_at': datetime.utcnow()
    }
    
    result = mongo.db.study_groups.insert_one(group)
    group['_id'] = result.inserted_id
    
    # Award points for group creation
    try:
        from app.routes.leaderboard import award_points
        award_points(str(user_id), 2) # +2 for creating a group
    except Exception as e:
        print(f"Points award error: {e}")
    
    return jsonify(serialize_doc(group)), 201


@study_groups_bp.route('/', methods=['GET'])
@jwt_required()
def list_groups():
    # Only list public groups
    groups = list(mongo.db.study_groups.find({'is_private': False}).sort('created_at', -1))
    return jsonify(serialize_doc(groups)), 200


@study_groups_bp.route('/my', methods=['GET'])
@jwt_required()
def list_my_groups():
    user_id = ObjectId(get_jwt_identity())
    groups = list(mongo.db.study_groups.find({'members': user_id}).sort('created_at', -1))
    return jsonify(serialize_doc(groups)), 200


@study_groups_bp.route('/<group_id>', methods=['GET'])
@jwt_required()
def get_group(group_id):
    try:
        user_id = ObjectId(get_jwt_identity())
        group = mongo.db.study_groups.find_one({'_id': ObjectId(group_id)})

        if not group:
            return jsonify({'error': 'Group not found'}), 404

        is_member = user_id in group.get('members', [])

        # Private group: non-members get limited info + is_private flag so FE can show join prompt
        if group.get('is_private') and not is_member:
            return jsonify({
                '_id': str(group['_id']),
                'name': group.get('name'),
                'subject': group.get('subject'),
                'description': group.get('description', ''),
                'is_private': True,
                'is_member': False,
                'member_count': len(group.get('members', [])),
                'created_by': str(group.get('created_by', '')),
                'created_at': group.get('created_at').isoformat() if group.get('created_at') else None
            }), 200

        # Full details for members / public groups
        member_docs = list(mongo.db.users.find(
            {'_id': {'$in': group.get('members', [])}},
            {'_id': 1, 'name': 1, 'avatar': 1, 'role': 1}
        ))
        
        # Fetch current user role for visibility check
        u_doc = mongo.db.users.find_one({'_id': user_id}, {'role': 1})
        is_page_admin = u_doc and (u_doc.get('role') or '').lower() == 'admin'

        # Add is_creator flag and hide names if not admin
        creator_id_str = str(group.get('created_by'))
        for m in member_docs:
            m_id_str = str(m['_id'])
            m['_id'] = m_id_str
            m['is_creator'] = m_id_str == creator_id_str
            
            # Anonymize if not admin and not self
            if not is_page_admin and m_id_str != str(user_id):
                m['name'] = 'Group Creator' if m['is_creator'] else 'Member'

        # Serialize properly as requested
        group['_id'] = str(group['_id'])
        group['created_by'] = creator_id_str
        group['members'] = [str(m) for m in group.get('members', [])]
        group['member_details'] = member_docs
        group['is_member'] = is_member
        
        if 'created_at' in group and group['created_at']:
            group['created_at'] = group['created_at'].isoformat()

        return jsonify(group), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@study_groups_bp.route('/<group_id>/join', methods=['POST'])
@jwt_required()
def join_group(group_id):
    user_id = ObjectId(get_jwt_identity())
    group = mongo.db.study_groups.find_one({'_id': ObjectId(group_id)})

    if not group:
        return jsonify({'error': 'Group not found'}), 404

    if user_id in group.get('members', []):
        return jsonify({'error': 'Already a member'}), 400

    mongo.db.study_groups.update_one(
        {'_id': ObjectId(group_id)},
        {'$push': {'members': user_id}}
    )
    
    # Award points for joining group
    try:
        from app.routes.leaderboard import award_points
        award_points(str(user_id), 1) # +1 for joining a group
    except Exception as e:
        print(f"Points award error: {e}")
        
    return jsonify({'message': 'Joined successfully'}), 200


@study_groups_bp.route('/<group_id>/privacy', methods=['PATCH'])
@jwt_required()
def toggle_privacy(group_id):
    """Admin-only: toggle private/public."""
    user_id = ObjectId(get_jwt_identity())
    group = mongo.db.study_groups.find_one({'_id': ObjectId(group_id)})

    if not group:
        return jsonify({'error': 'Group not found'}), 404

    if str(group.get('created_by')) != str(user_id):
        return jsonify({'error': 'Only the group admin can change privacy'}), 403

    new_val = not group.get('is_private', False)
    mongo.db.study_groups.update_one(
        {'_id': ObjectId(group_id)},
        {'$set': {'is_private': new_val}}
    )
    return jsonify({'is_private': new_val, 'message': f'Group is now {"private" if new_val else "public"}'}), 200


@study_groups_bp.route('/<group_id>/leave', methods=['POST'])
@jwt_required()
def leave_group(group_id):
    user_id = ObjectId(get_jwt_identity())
    group = mongo.db.study_groups.find_one({'_id': ObjectId(group_id)})
    
    if not group:
        return jsonify({'error': 'Group not found'}), 404
        
    if str(group.get('created_by')) == str(user_id):
        return jsonify({'error': 'Creator cannot leave. Delete the group instead.'}), 403
        
    if user_id not in group.get('members', []):
        return jsonify({'error': 'Not a member'}), 400
        
    mongo.db.study_groups.update_one(
        {'_id': ObjectId(group_id)},
        {'$pull': {'members': user_id}}
    )
    
    return jsonify({'message': 'Left group successfully'}), 200


@study_groups_bp.route('/<group_id>/members/<member_id>', methods=['DELETE'])
@jwt_required()
def remove_member(group_id, member_id):
    """Admin-only: remove a member from the group."""
    user_id = ObjectId(get_jwt_identity())
    group = mongo.db.study_groups.find_one({'_id': ObjectId(group_id)})

    if not group:
        return jsonify({'error': 'Group not found'}), 404

    if str(group.get('created_by')) != str(user_id):
        return jsonify({'error': 'Only group creator can remove members'}), 403

    target_id = ObjectId(member_id)
    if str(target_id) == str(group.get('created_by')):
        return jsonify({'error': 'Cannot remove group creator'}), 403

    if target_id not in group.get('members', []):
        return jsonify({'error': 'User is not a member'}), 400

    mongo.db.study_groups.update_one(
        {'_id': ObjectId(group_id)},
        {'$pull': {'members': target_id}}
    )
    return jsonify({'message': 'Member removed'}), 200

@study_groups_bp.route('/<group_id>/messages', methods=['GET'])
@jwt_required()
def get_messages(group_id):
    try:
        user_id = ObjectId(get_jwt_identity())
        group = mongo.db.study_groups.find_one({'_id': ObjectId(group_id)})
        
        if not group:
            return jsonify({'error': 'Group not found'}), 404
            
        if user_id not in group.get('members', []):
            return jsonify({'error': 'Must be a member to view messages'}), 403
            
        messages = list(
            mongo.db.study_group_messages
            .find({'group_id': ObjectId(group_id)})
            .sort('created_at', 1)
            .limit(50)
        )
        
        for m in messages:
            m['_id'] = str(m['_id'])
            m['group_id'] = str(m['group_id'])
            author_id = m.get('author')
            if author_id:
                u = mongo.db.users.find_one({'_id': ObjectId(str(author_id))}, {'name': 1})
                m['author_name'] = u.get('name', 'Anonymous') if u else 'Anonymous'
            else:
                m['author_name'] = 'Anonymous'

            if 'created_at' in m and m['created_at']:
                m['created_at'] = m['created_at'].isoformat()
                
        return jsonify(messages), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@study_groups_bp.route('/<group_id>/messages', methods=['POST'])
@jwt_required()
def send_message(group_id):
    try:
        user_id = ObjectId(get_jwt_identity())
        group = mongo.db.study_groups.find_one({'_id': ObjectId(group_id)})
        
        if not group:
            return jsonify({'error': 'Group not found'}), 404
            
        if user_id not in group.get('members', []):
            return jsonify({'error': 'Must be a member to send messages'}), 403
            
        data = request.get_json()
        content = str(data.get('content') or '').strip()
        
        if not content and not data.get('file_url'):
            return jsonify({'error': 'Message content or file is required'}), 400
            
        # Basic sanitization
        from app.utils_security import sanitize_input
        sanitized_content = sanitize_input(content)
        if sanitized_content is None:
             return jsonify({'error': 'Invalid characters detected'}), 400

        message = {
            'group_id': ObjectId(group_id),
            'author': user_id,
            'content': sanitized_content,
            'file_url': data.get('file_url'),
            'file_name': data.get('file_name'),
            'file_type': data.get('file_type'),
            'created_at': datetime.utcnow()
        }
        
        result = mongo.db.study_group_messages.insert_one(message)
        message['_id'] = str(result.inserted_id)
        message['group_id'] = str(message['group_id'])
        message['author'] = str(message['author'])
        
        # Award points for messaging
        try:
            from app.routes.leaderboard import award_points
            award_points(str(user_id), 1) # +1 point for participation
        except:
            pass
            
        return jsonify(message), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@study_groups_bp.route('/<group_id>/messages/<message_id>', methods=['PATCH'])
@jwt_required()
def edit_message(group_id, message_id):
    user_id = ObjectId(get_jwt_identity())
    data = request.get_json()
    new_content = str(data.get('content') or '').strip()

    if not new_content:
        return jsonify({'error': 'Message content cannot be empty'}), 400

    try:
        msg = mongo.db.study_group_messages.find_one({'_id': ObjectId(message_id)})
        if not msg:
            return jsonify({'error': 'Message not found'}), 404

        if str(msg['author']) != str(user_id):
            return jsonify({'error': 'Not authorized to edit this message'}), 403

        mongo.db.study_group_messages.update_one(
            {'_id': ObjectId(message_id)},
            {'$set': {
                'content': new_content,
                'is_edited': True,
                'updated_at': datetime.utcnow()
            }}
        )

        return jsonify({'message': 'Message updated'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@study_groups_bp.route('/<group_id>/messages/<message_id>', methods=['DELETE'])
@jwt_required()
def delete_message(group_id, message_id):
    user_id = ObjectId(get_jwt_identity())
    try:
        msg = mongo.db.study_group_messages.find_one({'_id': ObjectId(message_id)})
        if not msg:
            return jsonify({'error': 'Message not found'}), 404

        if str(msg['author']) != str(user_id):
            return jsonify({'error': 'Not authorized to delete this message'}), 403

        mongo.db.study_group_messages.update_one(
            {'_id': ObjectId(message_id)},
            {'$set': {
                'content': 'This message was deleted',
                'file_url': None,
                'file_name': None,
                'is_deleted': True,
                'deleted_at': datetime.utcnow()
            }}
        )

        return jsonify({'message': 'Message deleted'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@study_groups_bp.route('/<group_id>', methods=['DELETE'])
@jwt_required()
def delete_group(group_id):
    """Delete a study group (Creator or Admin only)."""
    try:
        from app.utils import get_current_user
        user = get_current_user()
        if not user:
             return jsonify({"error": "User session not found"}), 401

        group = mongo.db.study_groups.find_one({"_id": ObjectId(group_id)})
        if not group:
            return jsonify({"error": "Group not found"}), 404

        # Check permissions: Creator or User with role admin
        is_owner = str(group.get('created_by')) == str(user['_id'])
        is_admin = user.get('role') == 'admin'

        if not is_owner and not is_admin:
            return jsonify({"error": "Not authorized. Only the creator or an administrator can delete groups."}), 403

        # Delete messages associated with this group
        mongo.db.study_group_messages.delete_many({'group_id': ObjectId(group_id)})
        
        # Delete the group itself
        mongo.db.study_groups.delete_one({'_id': ObjectId(group_id)})
        
        return jsonify({"message": "Group deleted successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@study_groups_bp.route('/<group_id>/pin', methods=['POST'])
@jwt_required()
def pin_resource(group_id):
    user_id = ObjectId(get_jwt_identity())
    group = mongo.db.study_groups.find_one({'_id': ObjectId(group_id)})
    
    if not group:
        return jsonify({'error': 'Group not found'}), 404
        
    # Only admin (created_by) can pin
    if str(group.get('created_by')) != str(user_id):
        return jsonify({'error': 'Only group admin can pin resources'}), 403
        
    data = request.get_json()
    title = data.get('title', '').strip()
    url = data.get('url', '').strip()
    res_type = data.get('type', 'link').strip()  # link, image, video, document

    if not title or not url:
        return jsonify({'error': 'Title and URL are required'}), 400

    resource = {
        'id': str(uuid.uuid4()),
        'title': title,
        'url': url,
        'type': res_type,
        'added_by': user_id,
        'added_at': datetime.utcnow()
    }
    
    mongo.db.study_groups.update_one(
        {'_id': ObjectId(group_id)},
        {'$push': {'pinned_resources': resource}}
    )
    
    return jsonify({'resource': serialize_doc(resource)}), 200


@study_groups_bp.route('/<group_id>/pin/<pin_id>', methods=['DELETE'])
@jwt_required()
def unpin_resource(group_id, pin_id):
    user_id = ObjectId(get_jwt_identity())
    group = mongo.db.study_groups.find_one({'_id': ObjectId(group_id)})
    
    if not group:
        return jsonify({'error': 'Group not found'}), 404
        
    if str(group.get('created_by')) != str(user_id):
        return jsonify({'error': 'Only group admin can remove pinned resources'}), 403
        
    mongo.db.study_groups.update_one(
        {'_id': ObjectId(group_id)},
        {'$pull': {'pinned_resources': {'id': pin_id}}}
    )
    
    return jsonify({'message': 'Pinned resource removed'}), 200


@study_groups_bp.route('/<group_id>/privacy', methods=['POST'])
@jwt_required()
def toggle_group_privacy(group_id):
    try:
        from app.utils import get_current_user
        user = get_current_user()
        if not user:
            return jsonify({"error": "Unauthorized"}), 401
            
        group = mongo.db.study_groups.find_one({"_id": ObjectId(group_id)})
        if not group:
            return jsonify({"error": "Group not found"}), 404
            
        # Permission check: Creator or Admin
        if str(group.get('created_by')) != str(user['_id']) and user.get('role') != 'admin':
            return jsonify({"error": "Not authorized to change privacy for this group"}), 403
            
        is_private = request.json.get('is_private', False)
        mongo.db.study_groups.update_one(
            {"_id": ObjectId(group_id)},
            {"$set": {"is_private": is_private}}
        )
        
        return jsonify({
            "message": "Privacy updated",
            "is_private": is_private
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

