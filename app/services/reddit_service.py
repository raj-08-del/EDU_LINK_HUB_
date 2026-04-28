import os
import requests
from datetime import datetime, timedelta
import logging

def fetch_reddit_feed(mongo):
    """
    Fetches hot posts from student-relevant subreddits.
    Caches the results in MongoDB for 30 minutes.
    """
    CACHE_COLLECTION = 'social_cache'
    CACHE_KEY = 'reddit_feed'
    CACHE_DURATION = timedelta(minutes=30)
    
    try:
        # Check cache
        cache_doc = mongo.db[CACHE_COLLECTION].find_one({'_id': CACHE_KEY})
        if cache_doc and datetime.utcnow() - cache_doc.get('updated_at', datetime.min) < CACHE_DURATION:
            logging.info("Serving Reddit feed from cache")
            return cache_doc.get('data', [])
        
        subreddits = ['indianstudents', 'cscareerquestionsIN', 'Btechtards', 'developersIndia']
        all_posts = []
        
        headers = {
            'User-Agent': 'EduLinkHub/1.0 (Integration for Indian College Students)'
        }
        
        for sub in subreddits:
            try:
                url = f"https://www.reddit.com/r/{sub}/hot.json?limit=10"
                res = requests.get(url, headers=headers, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    posts = data.get('data', {}).get('children', [])
                    for post in posts:
                        pdata = post['data']
                        if pdata.get('stickied'):
                            continue  # Skip pinned posts
                        all_posts.append({
                            'id': pdata.get('id'),
                            'title': pdata.get('title'),
                            'subreddit': pdata.get('subreddit_name_prefixed'),
                            'author': pdata.get('author'),
                            'score': pdata.get('score'),
                            'num_comments': pdata.get('num_comments'),
                            'url': f"https://www.reddit.com{pdata.get('permalink')}",
                            'thumbnail': pdata.get('thumbnail') if pdata.get('thumbnail') and pdata.get('thumbnail').startswith('http') else None,
                            'created_utc': pdata.get('created_utc')
                        })
            except Exception as e:
                logging.error(f"Error fetching from r/{sub}: {e}")
                
        # Sort by score descending
        all_posts.sort(key=lambda x: x['score'], reverse=True)
        # Keep top 30
        all_posts = all_posts[:30]
        
        # Update cache
        mongo.db[CACHE_COLLECTION].update_one(
            {'_id': CACHE_KEY},
            {'$set': {
                'data': all_posts,
                'updated_at': datetime.utcnow()
            }},
            upsert=True
        )
        
        return all_posts
        
    except Exception as e:
        logging.error(f"Critical error in reddit_service: {e}")
        # Fallback to expired cache if available
        cache_doc = mongo.db[CACHE_COLLECTION].find_one({'_id': CACHE_KEY})
        if cache_doc:
            return cache_doc.get('data', [])
        return []
