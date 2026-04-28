from flask import Blueprint, request, jsonify, render_template
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from datetime import datetime
from app import mongo
from app.utils import serialize_doc, get_current_user
from app.services.notification_service import create_notification, notify_keyword_matches
import uuid
import logging
import traceback

community_bp = Blueprint('community', __name__)

ALLOWED_REACTIONS = ['👍', '💡', '❤️', '🔥']


def migrate_upvotes_to_reactions():
    """Migrate legacy upvotes field to reactions map for both posts and replies."""
    try:
        posts_with_upvotes = mongo.db.community_posts.find(
            {'upvotes': {'$exists': True}}, {'_id': 1, 'upvotes': 1}
        )
        for post in posts_with_upvotes:
            upvotes = post.get('upvotes', [])
            mongo.db.community_posts.update_one(
                {'_id': post['_id']},
                {
                    '$set': {'reactions': {'👍': upvotes, '💡': [], '❤️': [], '🔥': []}},
                    '$unset': {'upvotes': ''}
                }
            )
        
        replies_with_upvotes = mongo.db.community_replies.find(
            {'upvotes': {'$exists': True}}, {'_id': 1, 'upvotes': 1}
        )
        for reply in replies_with_upvotes:
            upvotes = reply.get('upvotes', [])
            mongo.db.community_replies.update_one(
                {'_id': reply['_id']},
                {
                    '$set': {'reactions': {'👍': upvotes, '💡': [], '❤️': [], '🔥': []}},
                    '$unset': {'upvotes': '', 'upvote_count': ''}
                }
            )
    except Exception as e:
        logging.warning(f"Migration warning: {e}")


def _build_poll_view(poll, user_id=None):
    if not poll:
        return None
    now = datetime.utcnow()
    ends_at = poll.get('ends_at')
    is_closed = ends_at is not None and now > ends_at

    total_votes = sum(len(opt.get('votes', [])) for opt in poll.get('options', []))
    user_vote = None
    options_view = []
    for opt in poll.get('options', []):
        votes = opt.get('votes', [])
        count = len(votes)
        pct = round(count / total_votes * 100) if total_votes else 0
        voted = user_id and ObjectId(user_id) in votes
        if voted:
            user_vote = opt.get('id')
        options_view.append({
            'id': opt.get('id'),
            'text': opt.get('text', 'Unnamed Option'),
            'count': count,
            'pct': pct,
        })

    return {
        'question': poll.get('question', ''),
        'options': options_view,
        'total_votes': total_votes,
        'user_vote': user_vote,
        'ends_at': poll.get('ends_at').isoformat() if poll.get('ends_at') and hasattr(poll.get('ends_at'), 'isoformat') else None,
        'is_closed': is_closed,
    }


def _build_reaction_view(reactions, user_id=None):
    result = {}
    user_reaction = None
    for emoji in ALLOWED_REACTIONS:
        voters = reactions.get(emoji, []) if reactions else []
        result[emoji] = len(voters)
        if user_id and ObjectId(user_id) in voters:
            user_reaction = emoji
    return result, user_reaction


def _anonymize_post(post, current_user_id=None, current_user_role=None):
    p = dict(post)
    is_owner = False
    is_admin = current_user_role in ['admin', 'moderator']
    
    if current_user_id and str(p.get('author')) == str(current_user_id):
        is_owner = True
    elif is_admin:
        is_owner = True
    
    p['is_owner'] = is_owner
    
    if not is_owner and not is_admin:
        p.pop('is_hidden', None)
        p.pop('hidden_at', None)
        p.pop('hidden_by', None)
        p.pop('hide_reason', None)
    
    
    # Basic info
    p['id'] = str(p.get('_id'))
    p['is_owner'] = str(p.get('author', '')) == str(current_user_id)
    p['is_admin'] = current_user_role in ['admin', 'moderator']
    p['can_manage'] = p['is_owner'] or p['is_admin']
    
    # Metadata with safety
    p['status'] = p.get('status', 'approved')
    p['is_hidden'] = p.get('is_hidden', False)
    p['edit_history'] = p.get('edit_history', [])
    
    # Author info
    author_id = p.get('author')
    is_admin_viewer = current_user_role == 'admin'
    
    if author_id and is_admin_viewer:
        author = mongo.db.users.find_one({'_id': ObjectId(author_id)}, {'name': 1, 'avatar': 1})
        p['author_name'] = author.get('name', 'Anonymous') if author else 'Deleted User'
        p['author_avatar'] = author.get('avatar', '') if author else ''
    else:
        p['author_name'] = 'Anonymous'
        p['author_avatar'] = ''

    # Poll processing
    poll_data = p.get('poll')
    p['poll'] = _build_poll_view(poll_data, current_user_id) if poll_data else None

    # Reactions processing
    reactions_raw = p.pop('reactions', {})
    # Reaction counts for the post
    post_reactions, post_user_reaction = _build_reaction_view(reactions_raw, current_user_id)
    p['user_reaction'] = post_user_reaction
    
    # Accepted Answer Status
    accepted_rid = post.get('accepted_reply_id')
    p['accepted_reply_id'] = str(accepted_rid) if accepted_rid else None
    
    # Ensure post_type has a fallback
    p['post_type'] = p.get('post_type') or 'Discussion'

    # Replies
    replies = list(mongo.db.community_replies.find({'post_id': p.get('_id')}).sort('created_at', 1))
    p['reply_count'] = len(replies)
    
    processed_replies = []
    for r in replies:
        r_view = serialize_doc(r)
        r_view['id'] = str(r.get('_id'))
        r_view['is_owner'] = str(r.get('author', '')) == str(current_user_id) or is_admin
        
        # Only expose real name to admin
        if is_admin:
            author_id = r.get('author')
            if author_id:
                author_doc = mongo.db.users.find_one({'_id': ObjectId(author_id)}, {'name': 1})
                r_view['author_name'] = author_doc.get('name', 'Anonymous') if author_doc else 'Deleted User'
            else:
                r_view['author_name'] = 'Anonymous'
        else:
            r_view['author_name'] = 'Anonymous'

        r_reactions_raw = r.get('reactions', {})
        reply_reactions, r_user_reaction = _build_reaction_view(r_reactions_raw, current_user_id)
        r_view['reactions'] = reply_reactions
        r_view['user_reaction'] = r_user_reaction
        r_view['upvote_count'] = reply_reactions.get('👍', 0)

        processed_replies.append(r_view)
    p['replies'] = processed_replies

    if 'poll' in p:
        p['poll'] = _build_poll_view(p.get('poll'), current_user_id)

    p['is_edited'] = post.get('is_edited', False)
    p['edit_history'] = serialize_doc(post.get('edit_history', []))

    p['total_reactions'] = sum(post_reactions.values()) if post_reactions else 0
    p['created_by'] = str(p.get('author', ''))
    p['created_at'] = str(p.get('created_at', ''))

    return p


@community_bp.route('/api/community/', methods=['GET'])
@jwt_required(optional=True)
def get_posts():
    try:
        tag = request.args.get('tag')
        search = request.args.get('search')
        sort = request.args.get('sort', 'newest')
        include_hidden = request.args.get('include_hidden', 'false').lower() == 'true'

        user_id = get_jwt_identity()
        user_role = None
        if user_id:
            user_doc = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if user_doc:
                user_role = (user_doc.get('role') or '').lower()

        query = {}
        if not (include_hidden and user_role in ['admin', 'moderator']):
            query['is_hidden'] = {'$ne': True}
            query['status'] = {'$ne': 'archived'}

        if tag:
            query['tags'] = tag.lower()
        if search:
            query['$or'] = [
                {'title': {'$regex': search, '$options': 'i'}},
                {'content': {'$regex': search, '$options': 'i'}},
            ]

        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 10))
        skip = (page - 1) * limit

        total_posts = mongo.db.community_posts.count_documents(query)
        posts = list(mongo.db.community_posts.find(query).sort('created_at', -1).skip(skip).limit(limit))

        if sort == 'popular':
            posts.sort(key=lambda p: sum(len(v) for v in p.get('reactions', {}).values()) if isinstance(p.get('reactions'), dict) else 0, reverse=True)

        anonymized = [_anonymize_post(p, user_id, user_role) for p in posts]
        return jsonify({
            'posts': serialize_doc(anonymized),
            'current_user_id': str(user_id) if user_id else None,
            'total': total_posts,
            'page': page,
            'limit': limit,
            'has_more': (skip + limit) < total_posts
        }), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"message": "An internal server error occurred", "error": str(e)}), 500






@community_bp.route('/api/community/<post_id>', methods=['GET'])
@jwt_required(optional=True)
def get_post(post_id):
    try:
        post = mongo.db.community_posts.find_one({'_id': ObjectId(post_id)})
        if not post:
            return jsonify({'error': 'Post not found'}), 404

        user_id = get_jwt_identity()
        user_role = None
        if user_id:
            u_doc = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if u_doc:
                user_role = (u_doc.get('role') or '').lower()

        is_admin = user_role in ['admin', 'moderator']
        is_owner = user_id and str(post.get('author')) == str(user_id)
        
        if post.get('is_hidden') and not is_owner and not is_admin:
            return jsonify({'error': 'This post is hidden'}), 403

        return jsonify(serialize_doc(_anonymize_post(post, user_id, user_role))), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@community_bp.route('/api/community/posts', methods=['POST'])
@jwt_required()
def create_post():
    import traceback
    from datetime import datetime
    from bson import ObjectId
    
    print("=== CREATE POST CALLED ===")
    try:
        # force=True to ensure it tries parsing even if Content-Type is missing
        data = request.get_json(force=True, silent=True)
        print("Received data:", data)

        if not data:
            print("ERROR: No JSON data received")
            return jsonify({"error": "No data received. Please check Content-Type header."}), 400

        title = str(data.get('title', '')).strip()
        if not title:
            return jsonify({"error": "Title is required"}), 400

        post_type = str(data.get('post_type', 'question')).lower()
        poll_data = None

        if post_type == 'poll':
            poll = data.get('poll')
            print("Poll data received:", poll)
            if not poll or not isinstance(poll.get('options'), list) or len([o for o in poll.get('options', []) if str(o).strip()]) < 2:
                return jsonify({"error": "Polls must have at least 2 valid options"}), 400
                
            poll_data = {
                'question': str(poll.get('question', title)),
                'options': [
                    {'id': str(idx + 1), 'text': str(opt).strip(), 'votes': []}
                    for idx, opt in enumerate(poll.get('options', []))
                    if str(opt).strip()
                ],
                'total_votes': 0,
                'voted_by': []
            }

        current_user_id = get_jwt_identity()

        post_doc = {
            'title': title,
            'content': str(data.get('content', '')),
            'post_type': post_type,
            'anonymous': bool(data.get('anonymous', True)),
            'tags': [str(t) for t in data.get('tags', []) if t],
            'poll': poll_data,
            'author': ObjectId(current_user_id),
            'created_at': datetime.utcnow(),
            'is_hidden': False,
            'status': 'active',
            'reactions': {'👍': [], '💡': [], '❤️': [], '🔥': []},
            'total_reactions': 0
        }

        print("Inserting post into community_posts:", post_doc['title'])
        result = mongo.db.community_posts.insert_one(post_doc)
        print("Post inserted with ID:", str(result.inserted_id))

        # Award points
        try:
            from app.routes.leaderboard import award_points
            award_points(current_user_id, 5, action_type='posts_created') # Standardized +5 for post
            if post_type == 'poll':
                award_points(current_user_id, 4, action_type='polls_created') # Standardized +4 for poll
        except Exception as pe:
             print(f'>>> Points award error: pe')

        # Keyword Notifications (Optional, non-blocking)
        try:
            from app.services.notification_service import notify_keyword_matches
            notify_keyword_matches(
                title=title,
                description=post_doc['content'],
                post_ref=result.inserted_id,
                post_model='community',
                notif_type='post',
                exclude_user_id=current_user_id,
                tags=post_doc['tags']
            )
        except Exception as n_err:
            print(f"Notification error: n_err")

        return jsonify({
            "message": "Post created successfully",
            "id": str(result.inserted_id),
            "success": True
        }), 201

    except Exception as e:
        print("=== CREATE POST ERROR ===")
        traceback.print_exc()
        print("Error:", str(e))
        return jsonify({"error": str(e)}), 500



@community_bp.route('/api/community/<post_id>', methods=['PUT'])
@jwt_required()
def update_post(post_id):
    try:
        user = get_current_user()
        post = mongo.db.community_posts.find_one({'_id': ObjectId(post_id)})
        if not post:
            return jsonify({'error': 'Not found'}), 404

        if str(post['author']) != str(user['_id']) and (user.get('role', '') or '').lower() not in ['admin', 'moderator']:
            return jsonify({'error': 'Forbidden'}), 403

        data = request.get_json()
        update_fields = {}
        
        if 'title' in data: update_fields['title'] = data['title'].strip()
        if 'content' in data: update_fields['content'] = data['content'].strip()
        if 'tags' in data:
            tags = data['tags']
            if isinstance(tags, str):
                tags = [t.strip().lower() for t in tags.split(',') if t.strip()]
            update_fields['tags'] = [t.strip().lower() for t in tags if t.strip()]

        update_fields['is_edited'] = True
        update_fields['updated_at'] = datetime.utcnow()

        edit_entry = {'title': post.get('title'), 'content': post.get('content'), 'edited_at': datetime.utcnow()}
        
        mongo.db.community_posts.update_one(
            {'_id': ObjectId(post_id)}, 
            {'$set': update_fields, '$push': {'edit_history': edit_entry}}
        )
        
        updated = mongo.db.community_posts.find_one({'_id': ObjectId(post_id)})
        return jsonify(serialize_doc(_anonymize_post(updated, str(user['_id']), (user.get('role') or '').lower()))), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@community_bp.route('/api/community/<post_id>/hide', methods=['PATCH', 'POST'])
@jwt_required()
def hide_post(post_id):
    try:
        user = get_current_user()
        post = mongo.db.community_posts.find_one({'_id': ObjectId(post_id)})
        if not post:
            return jsonify({'error': 'Not found'}), 404

        if str(post['author']) != str(user['_id']) and (user.get('role', '') or '').lower() not in ['admin', 'moderator']:
            return jsonify({'error': 'Forbidden'}), 403

        data = request.get_json(silent=True) or {}
        hide = data.get('hide', True)

        update = {'is_hidden': hide}
        if hide:
            update['hidden_at'] = datetime.utcnow()
            update['hidden_by'] = ObjectId(user['_id'])
            update['status'] = 'archived'
        else:
            update['hidden_at'] = None
            update['hidden_by'] = None
            update['status'] = 'active'

        mongo.db.community_posts.update_one({'_id': ObjectId(post_id)}, {'$set': update})
        return jsonify({
            'success': True,
            'message': 'Post hidden successfully' if hide else 'Post restored successfully'
        }), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@community_bp.route('/api/community/<post_id>', methods=['DELETE'])
@jwt_required()
def delete_post(post_id):
    try:
        user = get_current_user()
        post = mongo.db.community_posts.find_one({'_id': ObjectId(post_id)})
        if not post:
            return jsonify({'error': 'Not found'}), 404

        if str(post['author']) != str(user['_id']) and (user.get('role', '') or '').lower() not in ['admin', 'moderator']:
            return jsonify({'error': 'Forbidden'}), 403

        mongo.db.community_posts.delete_one({'_id': ObjectId(post_id)})
        mongo.db.community_replies.delete_many({'post_id': ObjectId(post_id)})
        mongo.db.bookmarks.delete_many({'contentId': ObjectId(post_id), 'contentType': 'post'})
        mongo.db.reports.delete_many({'item_id': str(post_id), 'item_type': 'post'})
        
        return jsonify({'message': 'Post deleted'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@community_bp.route('/api/community/<post_id>/reply', methods=['POST'])
@jwt_required()
def add_reply(post_id):
    try:
        user = get_current_user()
        data = request.get_json()
        if not data.get('content', '').strip():
            return jsonify({'error': 'Content is required'}), 400

        post = mongo.db.community_posts.find_one({'_id': ObjectId(post_id)})
        if not post:
            return jsonify({'error': 'Post not found'}), 404

        reply = {
            'post_id': ObjectId(post_id),
            'content': data['content'].strip(),
            'author': user['_id'],
            'author_name': user.get('name', 'Student'),
            'reactions': {'👍': [], '💡': [], '❤️': [], '🔥': []},
            'created_at': datetime.utcnow(),
        }
        mongo.db.community_replies.insert_one(reply)

        # Award points
        try:
            from app.routes.leaderboard import award_points
            award_points(user['_id'], 2, action_type='replies_posted') # +2 for replying
            if str(post.get('author')) != str(user['_id']):
                # Award +1 for receiving engagement (mapped to upvotes/engagement)
                award_points(post['author'], 1, action_type='upvotes_received') 
        except Exception as pe:
             print(f'>>> Points award error (reply): {pe}')

        if str(post['author']) != str(user['_id']):
            create_notification(
                user_id=post['author'],
                notif_type='comment_notification',
                message=f'💬 Someone commented on your post: "{post["title"]}"',
                post_ref=post['_id'],
                post_model='community_posts',
            )

        return jsonify({'message': 'Reply added'}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@community_bp.route('/api/community/posts/<post_id>/react', methods=['POST'])
@jwt_required()
def react_to_post(post_id):
    import traceback
    from bson import ObjectId
    from datetime import datetime
    from flask_jwt_extended import get_jwt_identity

    print("\n========== REACT CALLED ==========")
    try:
        # Step A - Get IDs
        uid_str = get_jwt_identity()
        print(f"User ID string: {uid_str}")
        
        try:
            uid = ObjectId(str(uid_str))
            pid = ObjectId(str(post_id))
        except Exception as e:
            print(f"ObjectId error: {e}")
            return jsonify({"error": f"Invalid ID: {e}"}), 400

        # Step B - Get post
        # Note: using community_posts and author to match project schema
        post = mongo.db.community_posts.find_one({"_id": pid})
        if not post:
            print("Post not found")
            return jsonify({"error": "Post not found"}), 404
        print(f"Post found: {post.get('title', 'no title')}")
        print(f"Post author: {post.get('author')} type: {type(post.get('author'))}")

        # Step C - Check existing reaction
        existing = mongo.db.reactions.find_one({"post_id": pid, "user_id": uid})
        print(f"Existing reaction: {existing}")

        if existing:
            # Remove reaction
            mongo.db.reactions.delete_one({"_id": existing["_id"]})
            mongo.db.community_posts.update_one({"_id": pid}, {"$inc": {"total_reactions": -1}})
            
            # Deduct points using award_points (with negative value)
            from app.routes.leaderboard import award_points
            award_points(uid, -1, action_type='post_likes')
            
            updated = mongo.db.community_posts.find_one({"_id": pid})
            return jsonify({
                "action": "removed",
                "total_reactions": updated.get("total_reactions", 0)
            }), 200

        else:
            # Add reaction
            mongo.db.reactions.insert_one({
                "post_id": pid,
                "user_id": uid,
                "reaction": "like",
                "created_at": datetime.utcnow()
            })
            print("Reaction inserted")
            
            mongo.db.community_posts.update_one({"_id": pid}, {"$inc": {"total_reactions": 1}})
            print("Post total_reactions incremented")

            # Use award_points for real-time tracking
            from app.routes.leaderboard import award_points
            # Award 1 point to liker
            award_points(uid, 1, action_type='post_likes')

            # Award 1 point to post creator (mapped to upvotes_received)
            creator_raw = post.get('author')
            if creator_raw and str(creator_raw) != str(uid_str):
                try:
                    award_points(creator_raw, 1, action_type='upvotes_received')
                except Exception as ce:
                    print(f"Creator points error: {ce}")
            
            # Verify liker points
            verify_liker = mongo.db.leaderboard.find_one({"user_id": uid})
            print(f"Liker leaderboard after update: {verify_liker}")

            updated = mongo.db.community_posts.find_one({"_id": pid})
            return jsonify({
                "action": "added",
                "total_reactions": updated.get("total_reactions", 0),
                "points_awarded": True
            }), 200

    except Exception as e:
        traceback.print_exc()
        print(f"REACT ROUTE EXCEPTION: {e}")
        return jsonify({"error": str(e)}), 500


@community_bp.route('/api/community/<post_id>/vote', methods=['PATCH'])
@jwt_required()
def vote_poll(post_id):
    import traceback
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        option_id = data.get('option_id')
        if not option_id:
            return jsonify({'error': 'Option ID is required'}), 400

        post = mongo.db.community_posts.find_one({'_id': ObjectId(post_id)})
        if not post or not post.get('poll'):
            return jsonify({'error': 'Poll not found'}), 404

        poll = post['poll']
        voted_by = poll.get('voted_by', [])
        if ObjectId(user_id) in voted_by:
            return jsonify({'error': 'You have already voted in this poll'}), 403

        options = poll.get('options', [])
        found_option = False
        for opt in options:
            if str(opt.get('id')) == str(option_id):
                if 'votes' not in opt: opt['votes'] = []
                opt['votes'].append(ObjectId(user_id))
                found_option = True
                break
        
        if not found_option:
            return jsonify({'error': 'Invalid poll option selected'}), 400

        mongo.db.community_posts.update_one(
            {'_id': ObjectId(post_id)},
            {
                '$set': {'poll.options': options},
                '$push': {'poll.voted_by': ObjectId(user_id)},
                '$inc': {'poll.total_votes': 1}
            }
        )

        updated_post = mongo.db.community_posts.find_one({'_id': ObjectId(post_id)})
        user_doc = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        user_role = (user_doc.get('role') or '').lower() if user_doc else 'student'
        
        return jsonify(serialize_doc(_anonymize_post(updated_post, user_id, user_role))), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': 'Internal server error processing vote'}), 500


@community_bp.route('/api/community/<post_id>/accept-reply/<reply_id>', methods=['PATCH'])
@jwt_required()
def accept_reply(post_id, reply_id):
    """Mark a reply as the 'Accepted Solution' for a post."""
    try:
        user_id = get_jwt_identity()
        post = mongo.db.community_posts.find_one({'_id': ObjectId(post_id)})
        if not post:
            return jsonify({'error': 'Post not found'}), 404

        # Only post author or admin can accept a reply
        is_admin = mongo.db.users.find_one({'_id': ObjectId(user_id)}).get('role') in ['admin', 'moderator']
        if str(post.get('author')) != str(user_id) and not is_admin:
            return jsonify({'error': 'Unauthorized'}), 403

        reply = mongo.db.community_replies.find_one({'_id': ObjectId(reply_id), 'post_id': ObjectId(post_id)})
        if not reply:
            return jsonify({'error': 'Reply not found'}), 404

        # Toggle or Set
        if post.get('accepted_reply_id') == ObjectId(reply_id):
            mongo.db.community_posts.update_one({'_id': ObjectId(post_id)}, {'$set': {'accepted_reply_id': None}})
            message = "Solution removed"
        else:
            mongo.db.community_posts.update_one({'_id': ObjectId(post_id)}, {'$set': {'accepted_reply_id': ObjectId(reply_id)}})
            message = "Solution accepted!"
            
            # Notify the replier
            if str(reply.get('author')) != str(user_id):
                create_notification(
                    user_id=reply['author'],
                    notif_type='solution_accepted',
                    message=f'✅ Your reply was marked as the solution for: "{post.get("title")}"',
                    post_ref=post['_id'],
                    post_model='community_posts',
                )

        return jsonify({'success': True, 'message': message}), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@community_bp.route('/api/channel/messages', methods=['POST'])
@jwt_required()
def send_channel_message():
    from datetime import datetime
    try:
        user_id = get_jwt_identity()
        data = request.get_json(force=True)
        
        content = data.get('content', '').strip()
        channel_slug = data.get('channel_slug', '')
        if not content or not channel_slug:
            return jsonify({"error": "Content and channel required"}), 400
            
        msg = {
            'channel_slug': channel_slug,
            'content': content,
            'sent_by': str(user_id),
            'author': ObjectId(user_id),
            'reply_to': data.get('reply_to'),
            'reply_to_text': data.get('reply_to_text', ''),
            'prefill_opp_id': data.get('prefill_opp_id'),
            'created_at': datetime.utcnow(),
            'is_anonymous': True
        }
        
        # Determine channel_id for compatibility
        channel = mongo.db.chat_channels.find_one({'slug': channel_slug})
        if channel:
            msg['channel_id'] = channel['_id']
            
        result = mongo.db.chat_messages.insert_one(msg)
        print("Message saved:", str(result.inserted_id))

        # Notify opportunity uploader if message came from an opportunity card
        opp_id = data.get('prefill_opp_id')
        if opp_id:
            try:
                opp = mongo.db.opportunities.find_one({"_id": ObjectId(opp_id)})
                if opp and opp.get('created_by'):
                    from app.services.notification_service import create_notification
                    create_notification(
                        user_id=opp['created_by'],
                        notif_type='opportunity_chat',
                        message=f'📢 Someone is discussing your opportunity "{opp.get("role", "")}" in Career & Internships chat.',
                        link='/community/channel/career-internships'
                    )
                    print("Notification sent to uploader:", str(opp['created_by']))
            except Exception as notif_err:
                print("Notification error:", notif_err)

        return jsonify({"message": "Sent", "id": str(result.inserted_id)}), 201
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@community_bp.route('/channel/test')
def channel_test():
    return jsonify({"ok": True, "msg": "Channel routing works"})

@community_bp.route('/community/channel/<slug>')
@jwt_required()
def channel_view(slug):
    import traceback
    try:
        from flask import request
        prefill_opp_id = request.args.get('opp_id', '')
        prefill_text = request.args.get('prefill', '')

        # Step 1 - find or create the channel
        # Standardize to 'chat_channels' to match existing schema
        channel = mongo.db.chat_channels.find_one({"slug": slug})

        if not channel:
            # Auto-create channel if it doesn't exist
            channel_names = {
                'general': {'name': 'General', 'description': 'General discussion for all students'},
                'career-internships': {'name': 'Career & Internships', 'description': 'Discuss placements, internships, and career tips'}
            }
            info = channel_names.get(slug, {'name': slug.replace('-', ' ').title(), 'description': ''})
            mongo.db.chat_channels.insert_one({
                'name': info['name'],
                'slug': slug,
                'description': info['description'],
                'created_at': datetime.utcnow(),
                'is_active': True
            })
            channel = mongo.db.chat_channels.find_one({"slug": slug})

        # Step 2 - fetch messages for this channel
        messages = list(mongo.db.chat_messages.find(
            {"channel_slug": slug}
        ).sort("created_at", 1).limit(100))

        # Step 3 - convert ObjectIds to strings
        for msg in messages:
            msg['_id'] = str(msg['_id'])
            # Safeguard: existing messages use 'author' or 'sent_by'
            msg['sent_by'] = str(msg.get('sent_by', msg.get('author', '')))

        # Step 4 - get all channels for sidebar
        all_channels = list(mongo.db.chat_channels.find({"is_active": True}))

        user = get_current_user()
        current_user_role = (user.get('role') or 'student').lower() if user else 'student'

        # For admin view only: enrich messages with sender name
        is_admin = current_user_role == 'admin'
        if is_admin:
            for msg in messages:
                author_id = msg.get('author') or msg.get('sent_by')
                if author_id:
                    try:
                        u = mongo.db.users.find_one({'_id': ObjectId(str(author_id))}, {'name': 1})
                        msg['author_name'] = u.get('name', 'Anonymous') if u else 'Anonymous'
                    except Exception:
                        msg['author_name'] = 'Anonymous'
                else:
                    msg['author_name'] = 'Anonymous'

        return render_template('channel.html',
            channel=channel,
            messages=messages,
            all_channels=all_channels,
            prefill_opp_id=prefill_opp_id,
            prefill_text=prefill_text,
            current_user_id=str(get_jwt_identity()),
            current_user_role=current_user_role
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"message": "An internal server error occurred", "error": str(e)}), 500
