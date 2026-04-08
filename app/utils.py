from functools import wraps
from flask import jsonify
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from app import mongo
from bson import ObjectId
from datetime import datetime


def role_required(*roles):
    """Decorator to restrict access based on user role."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            user_id = get_jwt_identity()
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if not user:
                return jsonify({'message': 'User not found'}), 401
            if user.get('role') not in roles:
                return jsonify({'message': 'Access denied. Insufficient permissions.'}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def get_current_user():
    """Get current user from JWT identity."""
    user_id = get_jwt_identity()
    if not user_id:
        return None
    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    if user:
        user.pop('password', None)
    return user


def serialize_doc(doc):
    """Convert MongoDB document to JSON-serializable dict."""
    if doc is None:
        return None
    if isinstance(doc, list):
        return [serialize_doc(d) for d in doc]
    if isinstance(doc, dict):
        result = {}
        for key, value in doc.items():
            if isinstance(value, ObjectId):
                result[key] = str(value)
            elif isinstance(value, datetime):
                result[key] = value.isoformat() + 'Z'
            elif isinstance(value, list):
                result[key] = [serialize_doc(v) if isinstance(v, (dict, ObjectId)) else v for v in value]
            elif isinstance(value, dict):
                result[key] = serialize_doc(value)
            else:
                result[key] = value
        return result
    if isinstance(doc, ObjectId):
        return str(doc)
    return doc
