from app import mongo
from bson import ObjectId
from datetime import datetime, timedelta

def calculate_user_points(user_id, period='all'):
    """
    Calculate leaderboard points for a user with robust error handling and zero fallbacks.
    """
    uid = ObjectId(user_id)
    now = datetime.utcnow()
    start_date = None
    
    if period == 'weekly':
        start_date = now - timedelta(days=7)
    elif period == 'monthly':
        start_date = now - timedelta(days=30)
        
    print(f">>> Calculating points for {user_id} (period: {period})")
    
    # helper for safe counting
    def safe_count(collection, query):
        try:
            return collection.count_documents(query)
        except Exception as e:
            print(f"❌ Error counting in {collection.name}: {e}")
            return 0

    # 1. Creations
    query = {'created_by': uid}
    if start_date:
        query['created_at'] = {'$gte': start_date}
    
    events_count = safe_count(mongo.db.events, query)
    
    post_query = {'author': uid}
    if start_date:
        post_query['created_at'] = {'$gte': start_date}
    
    q_count = 0
    poll_count = 0
    post_likes_received = 0
    replies_received = 0
    
    try:
        posts = list(mongo.db.community_posts.find(post_query))
        for p in posts:
            if p.get('post_type') == 'poll':
                poll_count += 1
            else:
                q_count += 1
                
            reactions = p.get('reactions', {})
            if isinstance(reactions, dict):
                post_likes_received += sum(len(v) for v in reactions.values())
            
            # Community replies on my posts
            replies_received += safe_count(mongo.db.community_replies, {'post_id': p['_id']})
    except Exception as e:
        print(f"❌ Error processing community posts: {e}")

    opp_query = {'created_by': uid, 'status': 'approved'}
    if start_date:
        opp_query['created_at'] = {'$gte': start_date}
    opps_count = safe_count(mongo.db.opportunities, opp_query)

    forum_query = {'author': uid}
    if start_date:
        forum_query['created_at'] = {'$gte': start_date}
    forums_count = safe_count(mongo.db.forum_posts, forum_query)

    group_query = {'created_by': uid}
    if start_date:
        group_query['created_at'] = {'$gte': start_date}
    groups_count = safe_count(mongo.db.study_groups, group_query)

    # 2. User Activity (Replies Created)
    replies_created = 0
    reply_likes_received = 0
    comm_reply_ids = []
    
    try:
        reply_query = {'author': uid}
        if start_date:
            reply_query['created_at'] = {'$gte': start_date}
        comm_replies = list(mongo.db.community_replies.find(reply_query))
        replies_created += len(comm_replies)
        comm_reply_ids = [r['_id'] for r in comm_replies]
        
        for r in comm_replies:
            r_reactions = r.get('reactions', {})
            if isinstance(r_reactions, dict):
                reply_likes_received += sum(len(v) for v in r_reactions.values())
    except Exception as e:
        print(f"❌ Error processing community replies: {e}")

    # Forum Replies (nested in forum_posts)
    forum_replies_count = 0
    try:
        forum_reply_pipeline = [
            {'$unwind': '$replies'},
            {'$match': {'replies.author': uid}}
        ]
        if start_date:
            forum_reply_pipeline[1]['$match']['replies.created_at'] = {'$gte': start_date}
        forum_replies_count = len(list(mongo.db.forum_posts.aggregate(forum_reply_pipeline)))
    except Exception as e:
        print(f"❌ Error processing forum replies: {e}")
    
    replies_created += forum_replies_count
    
    # Forum engagement on my posts
    forum_replies_on_my_posts = 0
    forum_upvotes_on_my_posts = 0
    try:
        my_forum_posts = list(mongo.db.forum_posts.find({'author': uid}))
        for fp in my_forum_posts:
            forum_replies_on_my_posts += len(fp.get('replies', []))
            forum_upvotes_on_my_posts += len(fp.get('upvotes', []))
    except Exception as e:
        print(f"❌ Error processing forum engagement: {e}")

    replies_received += forum_replies_on_my_posts
    total_likes_received = post_likes_received + forum_upvotes_on_my_posts

    # 3. Accepted Answers & Likes
    accepted_count = 0
    if comm_reply_ids:
        try:
            acc_query = {'accepted_reply_id': {'$in': comm_reply_ids}}
            accepted_count = safe_count(mongo.db.community_posts, acc_query)
        except Exception as e:
            print(f"❌ Error processing accepted answers: {e}")

    # Final scoring formula:
    # (events * 15) + (posts * 10) + (polls * 12) + (opportunities * 20) + (forums * 8) + (study_groups * 10) + (likes * 2) + (accepted_answers * 25)
    
    total = (events_count * 15) + (q_count * 10) + (poll_count * 12) + \
            (opps_count * 20) + (forums_count * 8) + (groups_count * 10) + \
            (total_likes_received * 2) + (accepted_count * 25)
    
    return {
        'total': total,
        'breakdown': {
            'events': events_count,
            'posts': q_count,
            'polls': poll_count,
            'opportunities': opps_count,
            'forums': forums_count,
            'study_groups': groups_count,
            'likes': total_likes_received,
            'accepted_answers': accepted_count
        }
    }

def get_leaderboard_rankings(period='all'):
    """
    Optimized aggregation for leaderboard rankings with global fail-safe.
    """
    try:
        users = mongo.db.users.find({'hidden_from_leaderboard': {'$ne': True}}, {'_id': 1, 'name': 1, 'avatar': 1, 'college': 1})
        rankings = []
        
        for user in users:
            stats = calculate_user_points(user['_id'], period)
            if stats['total'] > 0:
                rankings.append({
                    'user_id': str(user['_id']),
                    'name': user.get('name', 'Anonymous'),
                    'avatar': user.get('avatar', ''),
                    'college': user.get('college', 'Pioneer'),
                    'score': stats['total'],
                    'breakdown': stats['breakdown']
                })
                
        rankings.sort(key=lambda x: x['score'], reverse=True)
        return rankings
    except Exception as e:
        print(f"❌ GLOBAL LEADERBOARD ERROR: {e}")
        return []
