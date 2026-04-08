from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from bson import ObjectId
from datetime import datetime
from app import mongo
from app.utils import serialize_doc, get_current_user
from app.services.notification_service import notify_keyword_matches
import os
from werkzeug.utils import secure_filename
import traceback
from flask import current_app

events_bp = Blueprint('events', __name__)

CATEGORIES = ['workshop', 'technical', 'non-technical', 'hackathon', 'festival']


@events_bp.route('/', methods=['GET'])
@jwt_required(optional=True)
def get_events():
    try:
        category = request.args.get('category')
        search = request.args.get('search')
        sort = request.args.get('sort', 'newest')
        
        user_id = get_jwt_identity()
        user_role = None
        if user_id:
            u_doc = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if u_doc:
                user_role = (u_doc.get('role') or '').lower()

        # Default view: hide hidden items for everyone except admins/owners
        query = {'is_hidden': {'$ne': True}}

        if category and category in CATEGORIES:
            query['category'] = category
            
        if search:
            query['$or'] = [
                {'title': {'$regex': search, '$options': 'i'}},
                {'description': {'$regex': search, '$options': 'i'}},
            ]

        sort_order = [('date', 1)] if sort == 'oldest' else [('date', -1)]
        events = list(mongo.db.events.find(query).sort(sort_order))

        # Reactions fetch
        user_likes = []
        if user_id:
            try:
                like_docs = mongo.db.reactions.find({
                    'user_id': ObjectId(user_id),
                    'event_id': {'$in': [o['_id'] for o in events]}
                })
                user_likes = [str(d['event_id']) for d in like_docs]
            except Exception as e:
                print(f"Error fetching event likes: {e}")

        # Populate creator info & ownership
        is_admin_requester = user_role == 'admin'
        for event in events:
            creator = mongo.db.users.find_one({'_id': event.get('created_by')}, {'name': 1, 'college': 1})
            event['creator'] = serialize_doc(creator) if creator else None
            # Only expose real creator name to admin
            if is_admin_requester and creator:
                event['creator_name'] = creator.get('name', '')
            
            is_owner = str(event.get('created_by', '')) == str(user_id)
            is_admin = user_role in ['admin', 'moderator']
            event['is_owner'] = is_owner or is_admin
            
            # Add reaction data
            event['has_liked'] = str(event['_id']) in user_likes
            event['total_reactions'] = event.get('total_reactions', 0)

        return jsonify(serialize_doc(events))
    except Exception as e:
        print(f"ERROR in get_events: {str(e)}")
        return jsonify({'error': str(e)}), 500


@events_bp.route('/hidden', methods=['GET'])
@jwt_required()
def get_hidden_events():
    """
    Fetch hidden events for the Archive tab.
    Admins see ALL hidden events.
    Regular users see only their own hidden events.
    """
    try:
        current_user_id = get_jwt_identity()
        claims = get_jwt()
        user_role = (claims.get('role') or 'student').lower()
        is_admin = user_role in ['admin', 'moderator']
        
        if is_admin:
            # Admin/Mod sees all hidden events
            query = {'is_hidden': True}
        else:
            # Regular user sees only their own hidden items
            query = {
                'is_hidden': True,
                'created_by': ObjectId(current_user_id)
            }
        
        events = list(mongo.db.events.find(query).sort('hidden_at', -1))
        
        for e in events:
            e['_id'] = str(e['_id'])
            e['created_by'] = str(e.get('created_by', ''))
            if e.get('hidden_at'):
                e['hidden_at'] = e['hidden_at'].isoformat()
            e['is_owner'] = True # If they can see it in this route, they have manage permissions
            
        return jsonify(events), 200
    except Exception as e:
        print(f'Get hidden events error: {e}')
        return jsonify({'error': str(e)}), 500


@events_bp.route('/<event_id>', methods=['GET'])
@jwt_required(optional=True)
def get_event(event_id):
    try:
        event = mongo.db.events.find_one({'_id': ObjectId(event_id)})
    except Exception:
        return jsonify({'message': 'Invalid event ID'}), 400

    if not event:
        return jsonify({'message': 'Event not found'}), 404

    user_id = get_jwt_identity()
    user_role = None
    if user_id:
        u_doc = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if u_doc:
            user_role = (u_doc.get('role') or '').lower()
            
    is_owner = str(event.get('created_by', '')) == str(user_id)
    is_admin = user_role in ['admin', 'moderator']
    event['is_owner'] = is_owner or is_admin
    
    # Visibility check (Restricted access to hidden)
    if event.get('is_hidden') and not event['is_owner']:
        return jsonify({'message': 'This event has been hidden'}), 403

    # Add reaction data
    if user_id:
        has_liked = mongo.db.reactions.find_one({'user_id': ObjectId(user_id), 'event_id': ObjectId(event_id)})
        event['has_liked'] = bool(has_liked)
    else:
        event['has_liked'] = False
    event['total_reactions'] = event.get('total_reactions', 0)

    creator = mongo.db.users.find_one({'_id': event.get('created_by')}, {'name': 1, 'college': 1})
    event['creator'] = serialize_doc(creator) if creator else None

    return jsonify(serialize_doc(event))


@events_bp.route('/', methods=['POST'])
@jwt_required()
def create_event():
    try:
        current_user_id = get_jwt_identity()
        
        # 1. Determine if request is JSON or Form Data
        if request.is_json:
            data = request.get_json()
            title = data.get('title', '').strip()
            organizer = data.get('organizer', '').strip()
            description = data.get('description', '').strip()
            category = data.get('category', 'workshop')
            date = data.get('date', '').strip()
            location = data.get('location', '').strip()
            reg_link = data.get('registration_link', '').strip()
            media_link = data.get('media_link', '').strip()
            tags = data.get('tags', [])
            image_path = data.get('image', '').strip()
        else:
            # Handle multipart/form-data
            title = request.form.get('title', '').strip()
            organizer = request.form.get('organizer', '').strip()
            description = request.form.get('description', '').strip()
            category = request.form.get('category', 'workshop')
            date = request.form.get('date', '').strip()
            location = request.form.get('location', '').strip()
            reg_link = request.form.get('registration_link', '').strip()
            media_link = request.form.get('media_link', '').strip()
            
            # Parse tags (sent as JSON string in FormData)
            import json
            tags_raw = request.form.get('tags', '[]')
            try:
                tags = json.loads(tags_raw)
            except:
                tags = [t.strip() for t in tags_raw.split(',') if t.strip()]
            
            # Process File Upload
            image_path = ''
            if 'image' in request.files:
                file = request.files['image']
                if file and file.filename:
                    import uuid
                    filename = secure_filename(f"{uuid.uuid4().hex}_{file.filename}")
                    upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'events')
                    os.makedirs(upload_folder, exist_ok=True)
                    file.save(os.path.join(upload_folder, filename))
                    image_path = f'/static/uploads/events/{filename}'

        # 2. Validation
        if not title:
            return jsonify({'error': 'Title is required'}), 400
        if not date:
            return jsonify({'error': 'Date is required'}), 400
            
        if category not in CATEGORIES:
            category = 'workshop'
            
        # 3. Build Document
        event = {
            'title': title,
            'organizer': organizer,
            'description': description,
            'category': category,
            'date': date,
            'location': location,
            'registration_link': reg_link,
            'media_link': media_link,
            'image': image_path if image_path else media_link,
            'tags': tags if isinstance(tags, list) else [],
            'created_by': ObjectId(current_user_id),
            'created_at': datetime.utcnow(),
            'is_hidden': False,
            'status': 'active'
        }
        
        result = mongo.db.events.insert_one(event)
        event['_id'] = str(result.inserted_id)
        event['created_by'] = current_user_id
        
        # Award points for event creation
        try:
            from app.routes.leaderboard import award_points
            award_points(current_user_id, 3, action_type='events_created') # +3 for event creation
        except Exception as e:
            print(f"Points award error: {e}")
        
        print(f'Event successfully created: {event["_id"]}')
        
        # 4. Keyword Notifications
        try:
            notify_keyword_matches(
              title=title,
              description=description,
              post_ref=result.inserted_id,
              post_model='events',
              notif_type='event',
              exclude_user_id=current_user_id,
              tags=tags
            )
        except Exception as notif_err:
            print(f'Notification error (non-blocking): {notif_err}')
        
        return jsonify({
          'message': 'Event created successfully',
          'event': serialize_doc(event)
        }), 201
        
    except Exception as e:
        print(f'!!! CREATE EVENT ERROR: {str(e)} !!!')
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@events_bp.route('/<event_id>/hide', methods=['POST'])
@jwt_required()
def hide_event(event_id):
    print(f"=== HIDE EVENT DEBUG: {event_id} ===")
    try:
        current_user_id = get_jwt_identity()
        user_doc = mongo.db.users.find_one({'_id': ObjectId(current_user_id)})
        user_role = ((user_doc.get('role') or 'student') if user_doc else 'student').lower()
        
        # User specifically requested silent=True
        data = request.get_json(silent=True) or {}
        hide = data.get('hide', True)
        print(f"Action: {'Hide' if hide else 'Unhide'} | Requester: {current_user_id} ({user_role})")
        
        try:
            obj_id = ObjectId(event_id)
        except Exception:
            return jsonify({'error': 'Invalid event ID format'}), 400

        event = mongo.db.events.find_one({'_id': obj_id})
        if not event:
            return jsonify({'error': 'Event not found'}), 404
        
        is_owner = str(event.get('created_by', '')) == current_user_id
        is_admin = user_role in ['admin', 'moderator']
        
        if not (is_owner or is_admin):
            print(f"FORBIDDEN: User {current_user_id} cannot hide event {event_id}")
            return jsonify({'error': 'Forbidden: Only owner or admin can hide events'}), 403
        
        update_data = {'is_hidden': hide}
        if hide:
            update_data['hidden_at'] = datetime.utcnow()
            update_data['hidden_by'] = ObjectId(current_user_id)
            update_data['status'] = 'archived'
        else:
            update_data['hidden_at'] = None
            update_data['hidden_by'] = None
            update_data['status'] = 'active'
        
        mongo.db.events.update_one({'_id': obj_id}, {'$set': update_data})
        print(f"SUCCESS: Event {event_id} is now {'hidden' if hide else 'visible'}")
        
        return jsonify({'message': f"Event successfully {'hidden' if hide else 'unhidden'}"}), 200
    except Exception as e:
        print("=== HIDE EVENT EXCEPTION ===")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@events_bp.route('/<event_id>', methods=['PUT'])
@jwt_required()
def update_event(event_id):
    user = get_current_user()
    try:
        event = mongo.db.events.find_one({'_id': ObjectId(event_id)})
    except Exception:
        return jsonify({'message': 'Invalid event ID'}), 400

    if not event:
        return jsonify({'message': 'Event not found'}), 404

    # Ownership/Admin permission
    if str(event['created_by']) != str(user['_id']) and (user.get('role', '') or '').lower() not in ['admin', 'moderator']:
        return jsonify({'message': 'Not authorized'}), 403

    data = request.get_json()
    update_fields = {}
    
    for field in ['title', 'college_name', 'student_group_link', 'category', 'date', 'image', 'media_link', 'description', 'registration_link']:
        if field in data:
            val = data[field]
            if isinstance(val, str):
                update_fields[field] = val.strip()
            else:
                update_fields[field] = val
                
    if 'tags' in data:
        tags = data.get('tags', [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(',') if t.strip()]
        update_fields['tags'] = [t.strip() for t in tags if t.strip()]
        
    update_fields['updated_at'] = datetime.utcnow()

    mongo.db.events.update_one({'_id': ObjectId(event_id)}, {'$set': update_fields})
    updated = mongo.db.events.find_one({'_id': ObjectId(event_id)})

    # Notify on update if not hidden
    if not updated.get('is_hidden'):
        notify_keyword_matches(
            title=updated.get('title', ''),
            description=updated.get('description', ''),
            post_ref=updated['_id'],
            post_model='events',
            notif_type='event',
            exclude_user_id=user['_id'],
            tags=updated.get('tags', []),
        )

    return jsonify(serialize_doc(updated))




@events_bp.route('/<event_id>', methods=['DELETE'])
@jwt_required()
def delete_event(event_id):
    user = get_current_user()
    try:
        event = mongo.db.events.find_one({'_id': ObjectId(event_id)})
    except Exception:
        return jsonify({'message': 'Invalid event ID'}), 400

    if not event:
        return jsonify({'message': 'Event not found'}), 404

    if str(event['created_by']) != str(user['_id']) and (user.get('role', '') or '').lower() not in ['admin', 'moderator']:
        return jsonify({'message': 'Not authorized'}), 403

    mongo.db.events.delete_one({'_id': ObjectId(event_id)})
    
    # Cascading Cleanup: bookmarks and reports
    # Note: using contentId for legacy compatibility but ensuring content_id is also considered if needed
    mongo.db.bookmarks.delete_many({'contentId': ObjectId(event_id), 'contentType': 'event'})
    mongo.db.reports.delete_many({'contentId': ObjectId(event_id), 'contentType': 'event'})
    
    return jsonify({'message': 'Event deleted'})


@events_bp.route('/<event_id>/react', methods=['POST'])
@jwt_required()
def react_to_event(event_id):
    try:
        user_id = get_jwt_identity()
        uid = ObjectId(user_id)
        eid = ObjectId(event_id)
        
        event = mongo.db.events.find_one({'_id': eid})
        if not event:
            return jsonify({'error': 'Event not found'}), 404
            
        # Check if already reacted
        existing = mongo.db.reactions.find_one({'event_id': eid, 'user_id': uid})
        
        if existing:
            # UNLIKE
            mongo.db.reactions.delete_one({'_id': existing['_id']})
            mongo.db.events.update_one({'_id': eid}, {'$inc': {'total_reactions': -1}})
            
            # Deduct points
            try:
                from app.routes.leaderboard import award_points
                award_points(uid, -1, action_type='post_likes')
                if str(event.get('created_by')) != str(user_id):
                    award_points(event['created_by'], -1, action_type='upvotes_received')
            except Exception as pe:
                print(f"Points deduction error: {pe}")
                
            updated = mongo.db.events.find_one({'_id': eid})
            return jsonify({
                'action': 'removed',
                'total_reactions': max(0, updated.get('total_reactions', 0))
            }), 200
        else:
            # LIKE
            mongo.db.reactions.insert_one({
                'event_id': eid,
                'user_id': uid,
                'reaction': 'like',
                'created_at': datetime.utcnow()
            })
            mongo.db.events.update_one({'_id': eid}, {'$inc': {'total_reactions': 1}})
            
            # Award points
            try:
                from app.routes.leaderboard import award_points
                # Award 1 pt to liker
                award_points(uid, 1, action_type='post_likes')
                # Award 1 pt to creator
                if str(event.get('created_by')) != str(user_id):
                    award_points(event['created_by'], 1, action_type='upvotes_received')
            except Exception as pe:
                print(f"Points awarding error: {pe}")
                
            updated = mongo.db.events.find_one({'_id': eid})
            return jsonify({
                'action': 'added',
                'total_reactions': updated.get('total_reactions', 0)
            }), 200
            
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

