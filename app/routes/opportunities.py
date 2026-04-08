from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from bson.errors import InvalidId
from datetime import datetime, date
from app import mongo
from app.utils import serialize_doc, get_current_user, role_required
from app.services.notification_service import notify_keyword_matches
import traceback
import logging
import os
from werkzeug.utils import secure_filename
from flask import current_app

opportunities_bp = Blueprint('opportunities', __name__)

CATEGORIES = ['internship', 'job', 'campus-placement', 'skill-based']


def _auto_archive_expired():
    """Auto-archive opportunities whose deadline has passed."""
    try:
        today_str = date.today().isoformat()  # "YYYY-MM-DD"
        mongo.db.opportunities.update_many(
            {
                'status': 'approved',
                'is_archived': {'$ne': True},
                'deadline': {'$lt': today_str},
            },
            {'$set': {
                'is_archived': True,
                'archived_at': datetime.utcnow(),
                'archive_reason': 'expired',
            }}
        )
    except Exception as e:
        logging.error(f"Auto-archive warning: {e}")


@opportunities_bp.route('/', methods=['GET'])
@jwt_required(optional=True)
def get_opportunities():
    try:
        if mongo.db is None:
            return jsonify({"error": "Database connection unavailable"}), 503
        
        # Auto-archive check
        _auto_archive_expired()

        category = request.args.get('category')
        search = request.args.get('search')
        include_archived = request.args.get('include_archived', 'false').lower() == 'true'
        include_hidden = request.args.get('include_hidden', 'false').lower() == 'true'

        user_id = get_jwt_identity()
        user_role = None
        if user_id:
            u_doc = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if u_doc:
                user_role = (u_doc.get('role') or '').lower()

        # Base query
        query = {'status': 'approved'}
        
        if user_role in ['admin', 'moderator']:
            query['status'] = {'$in': ['approved', 'pending']}
        elif user_id:
            query = {
                '$or': [
                    {'status': 'approved'},
                    {'created_by': ObjectId(user_id), 'status': 'pending'}
                ]
            }

        # Archive/Hidden filtering
        if not include_archived:
            query['is_archived'] = {'$ne': True}
        else:
            query['is_archived'] = True

        if not include_hidden or user_role not in ['admin', 'moderator']:
            query['is_hidden'] = {'$ne': True}

        if category and category in CATEGORIES:
            query['category'] = category
        if search:
            query['$or'] = [
                {'company': {'$regex': search, '$options': 'i'}},
                {'role': {'$regex': search, '$options': 'i'}},
            ]

        opps = list(mongo.db.opportunities.find(query).sort('created_at', -1))

        # Batch status fetch
        user_statuses = {}
        user_likes = []
        if user_id:
            status_docs = mongo.db.opportunity_status.find({
                'user_id': ObjectId(user_id),
                'opportunity_id': {'$in': [o['_id'] for o in opps]}
            })
            user_statuses = {str(d['opportunity_id']): d['status'] for d in status_docs}
            
            # Reactions fetch
            like_docs = mongo.db.reactions.find({
                'user_id': ObjectId(user_id),
                'opp_id': {'$in': [o['_id'] for o in opps]}
            })
            user_likes = [str(d['opp_id']) for d in like_docs]

        for opp in opps:
            creator = mongo.db.users.find_one({'_id': opp.get('created_by')}, {'name': 1, 'college': 1, 'is_verified_organizer': 1})
            opp['creator'] = serialize_doc(creator) if creator else None
            # Only expose real creator name to admin
            if user_role == 'admin' and creator:
                opp['creator_name'] = creator.get('name', '')
            opp['is_owner'] = True if (user_id and str(opp.get('created_by')) == str(user_id)) or (user_role in ['admin', 'moderator']) else False
            opp['user_status'] = user_statuses.get(str(opp['_id']), 'Saved')
            opp['has_liked'] = str(opp['_id']) in user_likes
            
            deadline = opp.get('deadline', '')
            if deadline and not opp.get('is_archived'):
                try:
                    days_left = (date.fromisoformat(deadline) - date.today()).days
                    opp['days_left'] = days_left
                except:
                    opp['days_left'] = None
            else:
                opp['days_left'] = None

        return jsonify(serialize_doc(opps)), 200
    except Exception as e:
        logging.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@opportunities_bp.route('/pending', methods=['GET'])
@jwt_required()
@role_required('moderator', 'admin')
def get_pending():
    try:
        user = get_current_user()
        opps = list(mongo.db.opportunities.find({'status': 'pending'}).sort('created_at', -1))
        for opp in opps:
            creator = mongo.db.users.find_one({'_id': opp.get('created_by')}, {'name': 1, 'college': 1})
            opp['creator'] = serialize_doc(creator) if creator else None
            opp['is_owner'] = True if str(opp.get('created_by')) == str(user['_id']) or user['role'] == 'admin' else False
        return jsonify(serialize_doc(opps)), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@opportunities_bp.route('/<opp_id>', methods=['GET'])
@jwt_required(optional=True)
def get_opportunity(opp_id):
    try:
        opp = mongo.db.opportunities.find_one({'_id': ObjectId(opp_id)})
        if not opp:
            return jsonify({'error': 'Opportunity not found'}), 404

        user_id = get_jwt_identity()
        user_role = None
        if user_id:
            u_doc = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if u_doc:
                user_role = (u_doc.get('role') or '').lower()

        opp['is_owner'] = True if (user_id and str(opp.get('created_by')) == str(user_id)) or (user_role in ['admin', 'moderator']) else False
        
        if opp.get('is_hidden') and not opp['is_owner']:
            return jsonify({'error': 'This opportunity is hidden'}), 403

        creator = mongo.db.users.find_one({'_id': opp.get('created_by')}, {'name': 1, 'college': 1, 'is_verified_organizer': 1})
        opp['creator'] = serialize_doc(creator) if creator else None
        # Only expose real creator name to admin
        if user_role == 'admin' and creator:
            opp['creator_name'] = creator.get('name', '')

        return jsonify(serialize_doc(opp)), 200
    except InvalidId:
        return jsonify({'error': 'Invalid opportunity ID'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@opportunities_bp.route('/', methods=['POST'])
@jwt_required()
def create_opportunity():
    try:
        user = get_current_user()
        
        # Switch to request.form for multipart/form-data
        company = request.form.get('company')
        role = request.form.get('role')
        category = request.form.get('category')
        location = request.form.get('location')
        eligibility = request.form.get('eligibility')
        deadline = request.form.get('deadline')
        apply_link = request.form.get('applyLink')
        media_link = request.form.get('media_link', '')
        description = request.form.get('description', '')
        tags_raw = request.form.get('tags', '')

        if not all([company, role, category, location, eligibility, deadline, apply_link]):
            return jsonify({'error': 'Missing required fields'}), 400

        if category not in CATEGORIES:
            return jsonify({'error': 'Invalid category'}), 400

        # Handle Image Upload
        image_url = ''
        image_file = request.files.get('image')
        if image_file and image_file.filename != '':
            filename = secure_filename(f"{datetime.utcnow().timestamp()}_{image_file.filename}")
            upload_path = os.path.join(current_app.root_path, 'static', 'uploads', 'opportunities')
            os.makedirs(upload_path, exist_ok=True)
            image_file.save(os.path.join(upload_path, filename))
            image_url = f"/static/uploads/opportunities/{filename}"

        opp = {
            'company': company.strip(),
            'role': role.strip(),
            'category': category,
            'location': location.strip(),
            'eligibility': eligibility.strip(),
            'deadline': deadline,
            'description': description.strip(),
            'image': image_url,
            'media_link': media_link.strip(),
            'apply_link': apply_link.strip(),
            'tags': [t.strip() for t in tags_raw.split(',') if t.strip()],
            'status': 'pending',
            'is_hidden': False,
            'is_archived': False,
            'created_by': user['_id'],
            'created_at': datetime.utcnow(),
        }
        result = mongo.db.opportunities.insert_one(opp)
        opp['_id'] = result.inserted_id

        # Award points
        try:
            from app.routes.leaderboard import award_points
            award_points(str(user['_id']), 3, action_type='opportunities_created') # +3 for creation
        except Exception as pe:
            print(f'>>> Points award error: {pe}')

        return jsonify(serialize_doc(opp)), 201
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@opportunities_bp.route('/<opp_id>', methods=['PUT'])
@jwt_required()
def update_opportunity(opp_id):
    try:
        user = get_current_user()
        opp = mongo.db.opportunities.find_one({'_id': ObjectId(opp_id)})
        if not opp:
            return jsonify({'error': 'Not found'}), 404

        is_owner = str(opp.get('created_by')) == str(user['_id'])
        is_admin = user.get('role') in ['admin', 'moderator']
        
        if not (is_owner or is_admin):
            return jsonify({'error': 'Forbidden'}), 403

        # Switch to request.form for multipart/form-data
        update_fields = {}
        
        # Simple string fields
        for f in ['company', 'role', 'category', 'location', 'eligibility', 'deadline', 'description', 'media_link']:
            if f in request.form:
                update_fields[f] = request.form.get(f).strip()

        if 'applyLink' in request.form:
            update_fields['apply_link'] = request.form.get('applyLink').strip()
        
        if 'tags' in request.form:
            tags_raw = request.form.get('tags', '')
            update_fields['tags'] = [t.strip() for t in tags_raw.split(',') if t.strip()]

        # Handle Image Upload
        image_file = request.files.get('image')
        if image_file and image_file.filename != '':
            filename = secure_filename(f"{datetime.utcnow().timestamp()}_{image_file.filename}")
            upload_path = os.path.join(current_app.root_path, 'static', 'uploads', 'opportunities')
            os.makedirs(upload_path, exist_ok=True)
            image_file.save(os.path.join(upload_path, filename))
            update_fields['image'] = f"/static/uploads/opportunities/{filename}"

        update_fields['updated_at'] = datetime.utcnow()

        mongo.db.opportunities.update_one({'_id': ObjectId(opp_id)}, {'$set': update_fields})
        updated = mongo.db.opportunities.find_one({'_id': ObjectId(opp_id)})

        # Keyword matching notifications
        if updated.get('status') == 'approved' and not updated.get('is_hidden'):
            notify_keyword_matches(
                title=f"{updated.get('company')} - {updated.get('role')}",
                description=updated.get('description', ''),
                post_ref=updated['_id'],
                post_model='opportunities',
                notif_type='opportunity',
                exclude_user_id=user['_id'],
                tags=updated.get('tags', []),
            )

        return jsonify(serialize_doc(updated)), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@opportunities_bp.route('/<opp_id>', methods=['DELETE'])
@jwt_required()
def delete_opportunity(opp_id):
    try:
        user = get_current_user()
        opp = mongo.db.opportunities.find_one({'_id': ObjectId(opp_id)})
        if not opp:
            return jsonify({'error': 'Not found'}), 404

        is_owner = str(opp.get('created_by')) == str(user['_id'])
        is_admin = user.get('role') in ['admin', 'moderator']
        
        if not (is_owner or is_admin):
            return jsonify({'error': 'Forbidden'}), 403

        mongo.db.opportunities.delete_one({'_id': ObjectId(opp_id)})
        
        # Cascading Cleanup
        mongo.db.bookmarks.delete_many({'item_id': str(opp_id), 'item_type': 'opportunity'})
        mongo.db.reports.delete_many({'item_id': str(opp_id), 'item_type': 'opportunity'})
        
        return jsonify({'message': 'Opportunity deleted'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@opportunities_bp.route('/<opp_id>/hide', methods=['PATCH'])
@jwt_required()
def hide_opportunity(opp_id):
    try:
        current_user_id = get_jwt_identity()
        data = request.get_json() or {}
        hide = data.get('hide', True)
        
        opp = mongo.db.opportunities.find_one({'_id': ObjectId(opp_id)})
        if not opp:
            return jsonify({'error': 'Not found'}), 404
        
        user = mongo.db.users.find_one({'_id': ObjectId(current_user_id)})
        is_owner = str(opp.get('created_by', '')) == current_user_id
        is_admin = user.get('role') in ['admin', 'moderator']
        
        if not (is_owner or is_admin):
            return jsonify({'error': 'Forbidden'}), 403
        
        update = {'is_hidden': hide}
        if hide:
            update['hidden_at'] = datetime.utcnow()
            update['hidden_by'] = ObjectId(current_user_id)
            update['status'] = 'archived'
        else:
            update['hidden_at'] = None
            update['hidden_by'] = None
            update['status'] = 'approved'
        
        mongo.db.opportunities.update_one({'_id': ObjectId(opp_id)}, {'$set': update})
        return jsonify({'message': 'hidden' if hide else 'unhidden'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@opportunities_bp.route('/<opp_id>/review', methods=['PATCH'])
@jwt_required()
@role_required('moderator', 'admin')
def review_opportunity(opp_id):
    try:
        user = get_current_user()
        data = request.get_json()

        if data.get('status') not in ['approved', 'rejected']:
            return jsonify({'error': 'Invalid status'}), 400

        opp = mongo.db.opportunities.find_one({'_id': ObjectId(opp_id)})
        if not opp:
            return jsonify({'error': 'Not found'}), 404

        mongo.db.opportunities.update_one(
            {'_id': ObjectId(opp_id)},
            {'$set': {
                'status': data['status'],
                'reviewed_by': user['_id'],
                'review_note': data.get('reviewNote', ''),
                'reviewed_at': datetime.utcnow(),
            }}
        )

        if data['status'] == 'approved':
            # Award points for approved opportunity
            try:
                from app.routes.leaderboard import award_points
                award_points(str(opp['created_by']), 10, action_type='opportunities_approved') # +10 for approval
            except Exception as e:
                logging.error(f"Points award error: {e}")
            
            if not opp.get('is_hidden'):
                notify_keyword_matches(
                title=f"{opp['company']} - {opp['role']}",
                description=opp.get('description', ''),
                post_ref=opp['_id'],
                post_model='opportunities',
                notif_type='opportunity',
                exclude_user_id=opp['created_by'],
                tags=opp.get('tags', []),
            )

        updated = mongo.db.opportunities.find_one({'_id': ObjectId(opp_id)})
        return jsonify(serialize_doc(updated)), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@opportunities_bp.route('/<opp_id>/archive', methods=['PATCH'])
@jwt_required()
@role_required('moderator', 'admin')
def archive_opportunity(opp_id):
    try:
        data = request.get_json()
        archive = data.get('archive', True)

        opp = mongo.db.opportunities.find_one({'_id': ObjectId(opp_id)})
        if not opp:
            return jsonify({'error': 'Not found'}), 404

        if archive:
            mongo.db.opportunities.update_one(
                {'_id': ObjectId(opp_id)},
                {'$set': {
                    'is_archived': True,
                    'archived_at': datetime.utcnow(),
                    'archive_reason': 'manual',
                }}
            )
        else:
            mongo.db.opportunities.update_one(
                {'_id': ObjectId(opp_id)},
                {'$set': {
                    'is_archived': False,
                    'archived_at': None,
                    'archive_reason': None,
                }}
            )

        updated = mongo.db.opportunities.find_one({'_id': ObjectId(opp_id)})
        return jsonify(serialize_doc(updated)), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@opportunities_bp.route('/<opp_id>/status', methods=['GET'])
@jwt_required()
def get_personal_status(opp_id):
    try:
        user_id = ObjectId(get_jwt_identity())
        status_doc = mongo.db.opportunity_status.find_one({
            'user_id': user_id,
            'opportunity_id': ObjectId(opp_id)
        })
        return jsonify({'status': status_doc['status'] if status_doc else 'Saved'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@opportunities_bp.route('/<opp_id>/status', methods=['PATCH'])
@jwt_required()
def update_personal_status(opp_id):
    try:
        user_id = ObjectId(get_jwt_identity())
        data = request.get_json()
        new_status = data.get('status')
        
        allowed = ['Saved', 'Applied', 'Interviewing', 'Rejected']
        if new_status not in allowed:
            return jsonify({'error': 'Invalid status'}), 400
            
        mongo.db.opportunity_status.update_one(
            {'user_id': user_id, 'opportunity_id': ObjectId(opp_id)},
            {'$set': {'status': new_status, 'updated_at': datetime.utcnow()}},
            upsert=True
        )
        return jsonify({'message': 'Status updated', 'status': new_status}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
@opportunities_bp.route('/<opp_id>/react', methods=['POST'])
@jwt_required()
def react_to_opportunity(opp_id):
    try:
        user_id = get_jwt_identity()
        uid = ObjectId(user_id)
        oid = ObjectId(opp_id)
        
        opp = mongo.db.opportunities.find_one({'_id': oid})
        if not opp:
            return jsonify({'error': 'Opportunity not found'}), 404
            
        # Check if already reacted
        # Reusing the 'reactions' collection but with 'opp_id'
        existing = mongo.db.reactions.find_one({'opp_id': oid, 'user_id': uid})
        
        if existing:
            # UNLIKE
            mongo.db.reactions.delete_one({'_id': existing['_id']})
            mongo.db.opportunities.update_one({'_id': oid}, {'$inc': {'total_reactions': -1}})
            
            # Deduct points (using negative value in award_points)
            try:
                from app.routes.leaderboard import award_points
                award_points(uid, -1, action_type='post_likes')
                if str(opp.get('created_by')) != str(user_id):
                    award_points(opp['created_by'], -1, action_type='upvotes_received')
            except Exception as pe:
                print(f"Points deduction error: {pe}")
                
            updated = mongo.db.opportunities.find_one({'_id': oid})
            return jsonify({
                'action': 'removed',
                'total_reactions': updated.get('total_reactions', 0)
            }), 200
        else:
            # LIKE
            mongo.db.reactions.insert_one({
                'opp_id': oid,
                'user_id': uid,
                'reaction': 'like',
                'created_at': datetime.utcnow()
            })
            mongo.db.opportunities.update_one({'_id': oid}, {'$inc': {'total_reactions': 1}})
            
            # Award points
            try:
                from app.routes.leaderboard import award_points
                # Award 1 pt to liker
                award_points(uid, 1, action_type='post_likes')
                # Award 1 pt to creator
                if str(opp.get('created_by')) != str(user_id):
                    award_points(opp['created_by'], 1, action_type='upvotes_received')
            except Exception as pe:
                print(f"Points awarding error: {pe}")
                
            updated = mongo.db.opportunities.find_one({'_id': oid})
            return jsonify({
                'action': 'added',
                'total_reactions': updated.get('total_reactions', 0)
            }), 200
            
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
