from flask import Blueprint, jsonify, request, redirect, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
import logging
from app import mongo

from app.services.linkedin_service import get_linkedin_auth_url, get_linkedin_token, fetch_linkedin_profile

social_integrations_bp = Blueprint('social_integrations', __name__)


@social_integrations_bp.route('/linkedin/connect', methods=['GET'])
@jwt_required()
def linkedin_connect():
    auth_url = get_linkedin_auth_url()
    if not auth_url:
        return jsonify({'error': 'LinkedIn integration is not configured'}), 500
    return jsonify({'auth_url': auth_url}), 200

@social_integrations_bp.route('/linkedin/callback', methods=['GET'])
def linkedin_callback():
    code = request.args.get('code')
    if not code:
        # In a real app we'd redirect back to settings with an error
        return redirect('/settings?error=linkedin_auth_failed')
        
    token = get_linkedin_token(code)
    if not token:
        return redirect('/settings?error=linkedin_token_failed')
        
    profile = fetch_linkedin_profile(token)
    if not profile:
        return redirect('/settings?error=linkedin_profile_failed')
        
    # How to associate with user? 
    # Usually we would pass user ID in the 'state' param or rely on cookie sessions
    # Since we use JWT in cookies, let's try to verify the JWT from cookies
    from flask_jwt_extended import verify_jwt_in_request
    try:
        verify_jwt_in_request()
        user_id = get_jwt_identity()
        if user_id:
            mongo.db.users.update_one(
                {'_id': ObjectId(user_id)},
                {'$set': {
                    'linkedin_profile': profile,
                    'linkedin_connected': True
                }}
            )
            return redirect('/settings?success=linkedin_connected')
    except Exception as e:
        logging.error(f"Error associating LinkedIn with user: {e}")
    
    return redirect('/settings?error=linkedin_association_failed')

@social_integrations_bp.route('/linkedin/disconnect', methods=['POST', 'DELETE'])
@jwt_required()
def linkedin_disconnect():
    try:
        user_id = get_jwt_identity()
        mongo.db.users.update_one(
            {'_id': ObjectId(user_id)},
            {'$unset': {
                'linkedin_profile': "",
                'linkedin_connected': ""
            }}
        )
        return jsonify({'message': 'LinkedIn disconnected successfully'}), 200
    except Exception as e:
        logging.error(f"Error disconnecting LinkedIn: {e}")
        return jsonify({'error': 'Failed to disconnect LinkedIn'}), 500
