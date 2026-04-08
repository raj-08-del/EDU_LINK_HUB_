import re
from datetime import datetime, timedelta
from app import mongo

def validate_password_complexity(password):
    """
    Ensures password is at least 6 characters, contains 1 uppercase,
    1 lowercase, 1 number, and 1 special character.
    """
    if len(password) < 6:
        return False, "Password must be at least 6 characters"
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least 1 uppercase letter"
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least 1 lowercase letter"
    if not re.search(r'\d', password):
        return False, "Password must contain at least 1 number"
    if not re.search(r'[^A-Za-z0-9]', password):
        return False, "Password must contain at least 1 special character"
    
    return True, "Valid password"

def sanitize_input(text):
    """
    Very basic string sanitization to prevent rudimentary script injection
    and NoSQL injection.
    """
    if not isinstance(text, str):
        return ""
    
    # Block script tags and typical XSS/SQL payloads
    forbidden = ['<script>', 'javascript:', 'drop table', 'delete from']
    lower_text = text.lower()
    for f in forbidden:
        if f in lower_text:
            return None # Indicate invalid input
    
    # Escaping could be done here if rendering raw HTML, but since 
    # the frontend uses React/Jinja (which autoescapes), this is primarily
    # backend validation to reject malicious intent.
    return text.strip()

def check_rate_limit(ip, action, limit, window_minutes=15):
    """
    Checks if a given IP has exceeded the allowed `limit` for `action`
    within `window_minutes`. Returns (bool_is_allowed, time_remaining_ms).
    """
    now = datetime.utcnow()
    window_start = now - timedelta(minutes=window_minutes)
    
    # Clean up old records for this action (optional but good for performance)
    mongo.db.rate_limits.delete_many({'action': action, 'timestamp': {'$lt': window_start}})
    
    count = mongo.db.rate_limits.count_documents({
        'ip': ip,
        'action': action,
        'timestamp': {'$gte': window_start}
    })
    
    if count >= limit:
        return False
        
    # Standard request, will be logged by caller or here
    return True

def record_rate_limit(ip, action):
    """ Record a hit for rate limiting """
    mongo.db.rate_limits.insert_one({
        'ip': ip,
        'action': action,
        'timestamp': datetime.utcnow()
    })

def log_security_event(event_type, ip, email_or_phone='', details=None):
    """
    Logs security events like repeated failures, payload rejections.
    """
    mongo.db.security_logs.insert_one({
        'type': event_type,
        'ip': ip,
        'user_identifier': email_or_phone,
        'details': details or {},
        'timestamp': datetime.utcnow()
    })
