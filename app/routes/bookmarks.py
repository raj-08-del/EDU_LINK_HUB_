from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from datetime import datetime
from app import mongo
from app.utils import serialize_doc, get_current_user

bookmarks_bp = Blueprint('bookmarks', __name__)

VALID_TYPES = {'event', 'opportunity', 'post'}

def migrate_legacy_bookmarks():
    """One-time migration: users.bookmarks -> bookmarks collection"""
    try:
        users_with_bookmarks = mongo.db.users.find({'bookmarks': {'$exists': True, '$not': {'$size': 0}}})
        count = 0
        for user in users_with_bookmarks:
            u_id = user['_id']
            legacy_bookmarks = user.get('bookmarks', [])
            for lb in legacy_bookmarks:
                item_id = lb.get('item_id')
                item_type = lb.get('item_type')
                if not item_id or not item_type: continue
                
                # Check if already migrated
                exists = mongo.db.bookmarks.find_one({'userId': u_id, 'contentId': item_id})
                if not exists:
                    # Try to find a title
                    title = "Bookmarked Content"
                    if item_type == 'event':
                        doc = mongo.db.events.find_one({'_id': item_id})
                        title = doc.get('title') if doc else title
                    elif item_type == 'opportunity':
                        doc = mongo.db.opportunities.find_one({'_id': item_id})
                        title = doc.get('role') if doc else title
                    elif item_type == 'post':
                        doc = mongo.db.community_posts.find_one({'_id': item_id})
                        title = doc.get('title') if doc else title

                    mongo.db.bookmarks.insert_one({
                        'userId': u_id,
                        'contentId': item_id,
                        'contentType': item_type,
                        'contentTitle': title,
                        'createdAt': lb.get('saved_at', datetime.utcnow())
                    })
                    count += 1
            # Clear legacy
            mongo.db.users.update_one({'_id': u_id}, {'$unset': {'bookmarks': ''}})
        if count > 0:
            print(f"Migrated {count} legacy bookmarks to dedicated collection.")
    except Exception as e:
        print(f"Migration error: {e}")

# Call migration on import
# migrate_legacy_bookmarks()

@bookmarks_bp.route('/', methods=['POST'])
@jwt_required()
def add_bookmark():
    user = get_current_user()
    data = request.get_json() or {}
    
    # Support both old and new field names
    item_id = (data.get('contentId') or data.get('item_id', '')).strip()
    item_type = (data.get('contentType') or data.get('item_type', '')).strip()
    item_title = data.get('contentTitle', '').strip()

    if not item_id or item_type not in VALID_TYPES:
        return jsonify({'message': 'contentId and valid contentType required'}), 400

    try:
        item_oid = ObjectId(item_id)
    except Exception:
        return jsonify({'message': 'Invalid contentId'}), 400

    # Auto-fetch title if missing
    if not item_title:
        if item_type == 'event':
            doc = mongo.db.events.find_one({'_id': item_oid})
            item_title = doc.get('title') if doc else 'Event'
        elif item_type == 'opportunity':
            doc = mongo.db.opportunities.find_one({'_id': item_oid})
            item_title = doc.get('role') if doc else 'Opportunity'
        elif item_type == 'post':
            doc = mongo.db.community_posts.find_one({'_id': item_oid})
            item_title = doc.get('title') if doc else 'Post'

    # Check if already bookmarked
    existing = mongo.db.bookmarks.find_one({'userId': user['_id'], 'contentId': item_oid})
    if existing:
        return jsonify({'message': 'Already bookmarked'}), 200

    bookmark = {
        'userId': user['_id'],
        'contentId': item_oid,
        'contentType': item_type,
        'contentTitle': item_title or 'Untitled',
        'createdAt': datetime.utcnow(),
    }

    try:
        result = mongo.db.bookmarks.insert_one(bookmark)
        print(f"Bookmark saved with ID: {result.inserted_id}")
        return jsonify({'message': f'{item_type.capitalize()} bookmarked successfully', 'success': True}), 201
    except Exception as e:
        print(f"Error saving bookmark: {e}")
        return jsonify({'error': 'Database error saving bookmark'}), 500


@bookmarks_bp.route('/<item_id>', methods=['DELETE'])
@jwt_required()
def remove_bookmark(item_id):
    user = get_current_user()
    try:
        item_oid = ObjectId(item_id)
    except Exception:
        return jsonify({'message': 'Invalid contentId'}), 400

    mongo.db.bookmarks.delete_one({'userId': user['_id'], 'contentId': item_oid})
    return jsonify({'message': 'Bookmark removed successfully'})


@bookmarks_bp.route('/counts', methods=['GET'])
@jwt_required()
def get_bookmark_counts():
    user = get_current_user()
    
    # Get all bookmarks for this user
    user_bookmarks = list(mongo.db.bookmarks.find({'userId': user['_id']}))
    
    counts = {
        'event': 0,
        'opportunity': 0,
        'post': 0
    }
    for b in user_bookmarks:
        ctype = b.get('contentType')
        if ctype in counts:
            counts[ctype] += 1
            
    # [NEW] My Hidden/Archived Items (Events, Opps, Posts)
    hidden_events = mongo.db.events.count_documents({'created_by': user['_id'], 'status': 'archived'})
    hidden_opps_mine = mongo.db.opportunities.count_documents({'created_by': user['_id'], 'status': 'archived'})
    hidden_posts = mongo.db.community_posts.count_documents({'author': user['_id'], 'status': 'archived'})
    
    return jsonify({
        'events': counts['event'],
        'opportunities': counts['opportunity'],
        'posts': counts['post'],
        'archive': hidden_events + hidden_opps_mine + hidden_posts
    })


@bookmarks_bp.route('/', methods=['GET'])
@jwt_required()
def get_bookmarks():
    user = get_current_user()
    user_oid = user['_id']
    
    bookmarks = list(mongo.db.bookmarks.find({'userId': user_oid}))
    
    event_ids = [b['contentId'] for b in bookmarks if b.get('contentType') == 'event']
    opp_ids = [b['contentId'] for b in bookmarks if b.get('contentType') == 'opportunity']
    post_ids = [b['contentId'] for b in bookmarks if b.get('contentType') == 'post']

    # Fetch Data
    events_raw = list(mongo.db.events.find({'_id': {'$in': event_ids}}))
    opps_raw = list(mongo.db.opportunities.find({'_id': {'$in': opp_ids}}))
    posts_raw = list(mongo.db.community_posts.find({'_id': {'$in': post_ids}}))

    def enrich_event(e):
        e['item_type'] = 'event'
        e['is_bookmarked'] = True
        return e

    def enrich_opp(o):
        o['item_type'] = 'opportunity'
        o['is_bookmarked'] = True
        # Add creator info for the badge check
        creator = mongo.db.users.find_one({'_id': o.get('created_by')}, {'is_verified_organizer': 1})
        o['creator_is_verified'] = creator.get('is_verified_organizer', False) if creator else False
        return o

    def enrich_post(p):
        p['item_type'] = 'post'
        p['is_bookmarked'] = True
        reactions = p.get('reactions', {})
        p['upvotes_count'] = len(reactions.get('👍', []))
        p['reply_count'] = mongo.db.community_replies.count_documents({'post_id': p['_id']})
        return p

    final_events = [enrich_event(e) for e in events_raw]
    active_opps = [enrich_opp(o) for o in opps_raw if o.get('status') != 'archived']
    final_posts = [enrich_post(p) for p in posts_raw]

    # [NEW] My Hidden Content (Archive)
    my_hidden_events = list(mongo.db.events.find({'created_by': user_oid, 'is_hidden': True}))
    my_hidden_opps = list(mongo.db.opportunities.find({'created_by': user_oid, 'is_hidden': True}))
    my_hidden_posts = list(mongo.db.community_posts.find({'author': user_oid, 'is_hidden': True}))

    archive_items = []
    
    # 1. My hidden events (Fix 4/5)
    for e in my_hidden_events:
        e['item_type'] = 'event'
        e['archive_source'] = 'mine'
        archive_items.append(enrich_event(e))
        
    # 2. My hidden opportunities (Fix 4/5)
    for o in my_hidden_opps:
        o['item_type'] = 'opportunity'
        o['archive_source'] = 'mine'
        archive_items.append(enrich_opp(o))
            
    # 3. My hidden posts (Fix 4/5)
    for p in my_hidden_posts:
        p['item_type'] = 'post'
        p['archive_source'] = 'mine'
        archive_items.append(enrich_post(p))

    # 4. Expired Bookmarked Opportunities (Fix 5)
    expired_opps_raw = list(mongo.db.opportunities.find({
        '_id': {'$in': opp_ids},
        'is_archived': True
    }))
    for o in expired_opps_raw:
        # Avoid duplicates if I also own it
        if not any(item['_id'] == o['_id'] for item in archive_items):
            o['item_type'] = 'opportunity'
            o['archive_source'] = 'expired'
            archive_items.append(enrich_opp(o))


    return jsonify({
        'events': serialize_doc(final_events),
        'opportunities': serialize_doc(active_opps),
        'posts': serialize_doc(final_posts),
        'archive': serialize_doc(archive_items)
    })


@bookmarks_bp.route('/ids', methods=['GET'])
@jwt_required()
def get_bookmark_ids():
    """Return just the bookmarked item IDs for quick lookup on page load."""
    user = get_current_user()
    bookmarks = list(mongo.db.bookmarks.find({'userId': user['_id']}, {'contentId': 1, 'contentType': 1}))
    return jsonify([
        {'item_id': str(b['contentId']), 'item_type': b.get('contentType')}
        for b in bookmarks
    ])
