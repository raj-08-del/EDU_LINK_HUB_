from datetime import datetime
from bson import ObjectId
from app import mongo


def create_notification(user_id, notif_type, message, post_ref=None, post_model=None, extra_data=None, link=None):
    """Create a notification for a specific user."""
    try:
        notification = {
            'user_id': ObjectId(user_id) if isinstance(user_id, str) else user_id,
            'type': notif_type,
            'message': message,
            'post_ref': ObjectId(post_ref) if post_ref else None,
            'post_model': post_model,
            'extra_data': extra_data,
            'link': link,
            'read': False,
            'created_at': datetime.utcnow(),
        }
        result = mongo.db.notifications.insert_one(notification)
        notification['_id'] = result.inserted_id
        return notification
    except Exception as e:
        print(f"Error creating notification: {e}")
        return None


def notify_keyword_matches(title, description, post_ref, post_model, notif_type, exclude_user_id=None, tags=None):
    """Scan all users' keywords and send notifications for matching content."""
    try:
        tags_str = " ".join(tags) if tags else ""
        search_text = f"{title} {description} {tags_str}".lower()
        query = {'keywords': {'$exists': True, '$ne': []}}
        # Note: We now allow self-notifications for better user feedback and testing.

        users = mongo.db.users.find(query)
        notifications = []

        for user in users:
            matched = [kw for kw in user.get('keywords', []) if kw.lower() in search_text]
            if matched:
                msg = f"New {notif_type} matches your keyword{'s' if len(matched) > 1 else ''}: {', '.join(matched)}"
                notif = create_notification(
                    user_id=user['_id'],
                    notif_type='keyword',
                    message=msg,
                    post_ref=post_ref,
                    post_model=post_model,
                )
                if notif:
                    notifications.append(notif)

        return notifications
    except Exception as e:
        print(f"Error notifying keyword matches: {e}")
        return []
