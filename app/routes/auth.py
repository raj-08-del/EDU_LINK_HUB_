from flask import Blueprint, request, jsonify, session
from flask_jwt_extended import create_access_token, set_access_cookies, unset_jwt_cookies
from app import mongo, bcrypt
from app.utils import serialize_doc
from app.utils_security import (
    validate_password_complexity, sanitize_input, check_rate_limit,
    record_rate_limit, log_security_event
)
from datetime import datetime, timedelta
import re
import time
import secrets
import os
import hashlib
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from app.utils_sms import normalize_phone_number, send_reset_password_email

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/check-user', methods=['POST'])
def check_user():
    data = request.get_json()
    phone = data.get('phone', '').strip()
    email = data.get('email', '').strip().lower()

    full_phone = normalize_phone_number(phone) if phone else None

    query_conditions = []
    if email:
        query_conditions.append({'email': email})
    if full_phone:
        query_conditions.append({'phone': full_phone})

    if not query_conditions:
        return jsonify({'exists': False, 'message': 'Invalid inputs'}), 400

    user = mongo.db.users.find_one({'$or': query_conditions})
    return jsonify({'exists': bool(user), 'message': 'Account already exists. Please try a different phone number or email.' if user else ''})


@auth_bp.route('/register', methods=['POST'])
def register():
    ip = request.remote_addr or request.headers.get('X-Forwarded-For', 'unknown')

    if not check_rate_limit(ip, 'register', 5, window_minutes=60):
        log_security_event('register_rate_limit', ip)
        return jsonify({'message': 'Too many registration attempts. Try again later.'}), 429

    data = request.get_json()

    if data.get('bot_trap', '').strip() != '':
        log_security_event('honeypot_triggered', ip)
        return jsonify({'message': 'Invalid request'}), 400

    submit_time = int(time.time())
    start_time = int(data.get('form_start_time', submit_time))
    if (submit_time - start_time) < 2:
        log_security_event('form_timing_too_fast', ip)
        return jsonify({'message': 'Automated submission detected'}), 400

    client_csrf = data.get('csrf_token', '')
    if not client_csrf or client_csrf != session.get('csrf_token'):
        log_security_event('csrf_failure', ip)
        return jsonify({'message': 'Invalid request token'}), 400

    fields = ['name', 'email', 'password', 'college', 'department', 'phone']
    clean_data = {}
    for f in fields:
        val = str(data.get(f, ''))
        sanitized = sanitize_input(val)
        if sanitized is None:
            log_security_event('malicious_payload', ip, details={'field': f, 'raw': val})
            return jsonify({'message': 'Invalid characters detected'}), 400
        clean_data[f] = sanitized

    if any(not clean_data[f] for f in fields):
        return jsonify({'message': 'All fields are mandatory'}), 400

    email = clean_data['email']

    full_phone = normalize_phone_number(clean_data['phone'])
    if not full_phone:
        return jsonify({'message': 'Invalid phone format'}), 400

    is_valid_pwd, pwd_msg = validate_password_complexity(clean_data['password'])
    if not is_valid_pwd:
        return jsonify({'message': pwd_msg}), 400

    if mongo.db.users.find_one({'$or': [{'email': email}, {'phone': full_phone}]}):
        return jsonify({'message': 'Account already exists. Please try a different phone number or email.'}), 400

    hashed = bcrypt.generate_password_hash(clean_data['password'], 12).decode('utf-8')

    user = {
        'name': clean_data['name'],
        'email': email,
        'password': hashed,
        'college': clean_data['college'],
        'department': clean_data['department'],
        'phone': full_phone,
        'role': 'student',
        'keywords': [],
        'avatar': '',
        'is_verified_organizer': False,
        'points': 0,
        'total_points': 0,
        'created_at': datetime.utcnow(),
    }

    result = mongo.db.users.insert_one(user)
    user['_id'] = result.inserted_id

    session['csrf_token'] = secrets.token_hex(32)

    record_rate_limit(ip, 'register')
    log_security_event('user_registration', ip, email, {'name': clean_data['name']})

    # Initialize user points
    try:
        from app.routes.leaderboard import award_points
        mongo.db.user_points.insert_one({
            'user_id': result.inserted_id,
            'total_points': 0,
            'breakdown': {
                'posts_created': 0,
                'upvotes_received': 0,
                'opportunities_approved': 0,
                'replies_posted': 0,
                'events_created': 0,
                'events_rsvp': 0,
                'study_groups_created': 0,
                'study_groups_joined': 0,
                'college_reviews': 0,
                'polls_created': 0
            },
            'last_activity': None,
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        })
    except Exception as pe:
        print(f'>>> Points init error: {pe}')

    token = create_access_token(identity=str(user['_id']))
    user.pop('password', None)

    response = jsonify({'user': serialize_doc(user)})
    set_access_cookies(response, token)
    return response, 201


@auth_bp.route('/login', methods=['POST'])
def login():
    ip = request.remote_addr or request.headers.get('X-Forwarded-For', 'unknown')

    if not check_rate_limit(ip, 'login_failed', 5, window_minutes=15):
        log_security_event('login_bruteforce_lock', ip)
        return jsonify({'message': 'Too many failed attempts. Try again after 15 minutes.'}), 429

    data = request.get_json()

    login_id = str(data.get('email', '')).strip()
    password = str(data.get('password', ''))

    sanitized_id = sanitize_input(login_id)
    if sanitized_id is None:
        return jsonify({'message': 'Invalid characters detected'}), 400

    if not sanitized_id or not password:
        return jsonify({'message': 'Email or Phone and password are required'}), 400

    normalized_phone = normalize_phone_number(sanitized_id)
    phone_query = normalized_phone if normalized_phone else sanitized_id

    user = mongo.db.users.find_one({
        '$or': [
            {'email': sanitized_id.lower()},
            {'phone': phone_query}
        ]
    })

    if not user or not bcrypt.check_password_hash(user['password'], password):
        record_rate_limit(ip, 'login_failed')
        return jsonify({'message': 'Invalid credentials'}), 400

    token = create_access_token(identity=str(user['_id']))
    user.pop('password', None)

    log_security_event('user_login', ip, sanitized_id)

    session['csrf_token'] = secrets.token_hex(32)

    response = jsonify({'user': serialize_doc(user)})
    set_access_cookies(response, token)
    return response, 200


@auth_bp.route('/logout', methods=['POST'])
def logout():
    response = jsonify({'message': 'Logged out successfully'})
    unset_jwt_cookies(response)
    session.pop('csrf_token', None)
    return response, 200


@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    try:
        data = request.get_json(silent=True) or {}
        email = data.get('email', '').strip().lower()
        
        if not email:
            return jsonify({'error': 'Email is required'}), 400
        
        # Check if user exists
        user = mongo.db.users.find_one({'email': email})
        
        if not user:
            # Inform the user that the email is not registered
            # We use 200 status so the frontend correctly displays our custom error message
            return jsonify({'error': 'This email is not used in EDU_LINK_HUB. Please create an account.'}), 200
        
        # Check if Google-only account
        if user.get('auth_provider') == 'google' and not user.get('password'):
            return jsonify({
                'error': 'This account uses Google Sign In. Please login with Google.'
            }), 400
        
        # Generate secure raw token
        raw_token = secrets.token_urlsafe(32)
        
        # Hash the token before storage
        hashed_token = hashlib.sha256(raw_token.encode()).hexdigest()
        
        # Store hashed token in database with expiry
        mongo.db.password_resets.update_one(
            {'user_id': user['_id']},
            {
                '$set': {
                    'user_id': user['_id'],
                    'hashed_token': hashed_token,
                    'email': email,
                    'expires_at': datetime.utcnow() + timedelta(minutes=30),
                    'used': False,
                    'created_at': datetime.utcnow()
                }
            },
            upsert=True
        )
        
        # Build reset link (Assuming local for now)
        base_url = request.host_url.rstrip('/')
        reset_link = f"{base_url}/reset-password?token={raw_token}"
        
        # Send Email
        success, deliver_msg = send_reset_password_email(email, reset_link)
        
        if not success:
            return jsonify({'error': deliver_msg}), 500
        
        return jsonify({
            'message': 'Password reset link sent to your email.'
        }), 200
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@auth_bp.route('/reset-password', methods=['POST'])
def reset_password():
    try:
        data = request.get_json(silent=True) or {}
        raw_token = data.get('token', '').strip()
        new_password = data.get('new_password', '')
        
        if not raw_token:
            return jsonify({'error': 'Token is required'}), 400
        
        if not new_password or len(new_password) < 8:
            return jsonify({'error': 'Password must be at least 8 characters'}), 400
        
        # Hash the incoming raw token to compare
        hashed_token = hashlib.sha256(raw_token.encode()).hexdigest()
        
        # Find token in DB
        reset_record = mongo.db.password_resets.find_one({
            'hashed_token': hashed_token,
            'used': False
        })
        
        if not reset_record:
            return jsonify({'error': 'Invalid or expired token.'}), 400
        
        # Check expiry
        if datetime.utcnow() > reset_record.get('expires_at', datetime.min):
            return jsonify({'error': 'Token has expired. Please request a new one.'}), 400
        
        # Hash new password
        password_hashed = bcrypt.generate_password_hash(new_password).decode('utf-8')
        
        # Update user password
        mongo.db.users.update_one(
            {'_id': reset_record['user_id']},
            {'$set': {
                'password': password_hashed,
                'updated_at': datetime.utcnow()
            }}
        )
        
        # Mark token as used
        mongo.db.password_resets.update_one(
            {'hashed_token': hashed_token},
            {'$set': {
                'used': True,
                'used_at': datetime.utcnow()
            }}
        )
        
        return jsonify({'message': 'Password updated successfully.'}), 200
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@auth_bp.route('/google', methods=['POST'])
def google_login():
    try:
        data = request.get_json(silent=True) or {}
        credential = data.get('credential', '')
        
        if not credential:
            return jsonify({'error': 'No credential'}), 400
        
        CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
        print(f">>> GOOGLE AUTH: Attempting to verify token for client_id: {CLIENT_ID}")
        
        try:
            # First attempt
            id_info = id_token.verify_oauth2_token(
                credential,
                google_requests.Request(),
                CLIENT_ID
            )
            print(">>> GOOGLE AUTH: Token verified successfully!")
        except ValueError as ve:
            # Reduced wait to 2s for significantly faster logins while still fixing the clock issue
            if "Token used too early" in str(ve):
                print("⚠️ GOOGLE AUTH: Clock sync issue. Waiting 2s to retry...")
                time.sleep(2)
                id_info = id_token.verify_oauth2_token(
                    credential,
                    google_requests.Request(),
                    CLIENT_ID
                )
                print("✅ GOOGLE AUTH: Token verified after retry!")
            else:
                print(f"❌ GOOGLE AUTH VALUE ERROR: {str(ve)}")
                raise ve
        except Exception as verify_err:
            print(f"❌ GOOGLE AUTH VERIFICATION FAILED: {str(verify_err)}")
            raise verify_err
        
        email = id_info.get('email', '')
        name = id_info.get('name', '')
        picture = id_info.get('picture', '')
        google_id = id_info.get('sub', '')
        
        if not email:
            print("❌ GOOGLE AUTH ERROR: No email returned from Google")
            return jsonify({'error': 'No email from Google'}), 400
        
        # Find or create user
        user = mongo.db.users.find_one({'email': email})
        is_new = False
        
        if user:
            mongo.db.users.update_one(
                {'_id': user['_id']},
                {'$set': {
                  'last_login': datetime.utcnow(),
                  'google_id': google_id
                }}
            )
        else:
            is_new = True
            new_user = {
                'name': name,
                'email': email,
                'google_id': google_id,
                'avatar': picture,
                'role': 'student',
                'college': '',
                'department': '',
                'phone': '',
                'keywords': [],
                'password': None,
                'auth_provider': 'google',
                'created_at': datetime.utcnow()
            }
            result = mongo.db.users.insert_one(new_user)
            new_user['_id'] = result.inserted_id
            user = new_user
            
            # Init leaderboard points
            try:
                mongo.db.user_points.insert_one({
                    'user_id': result.inserted_id,
                    'total_points': 0,
                    'breakdown': {},
                    'created_at': datetime.utcnow()
                })
            except:
                pass
        
        token = create_access_token(
            identity=str(user['_id']),
            additional_claims={
                'role': user.get('role','student'),
                'name': user.get('name',''),
                'email': user.get('email','')
            }
        )
        
        response = jsonify({
            'access_token': token,
            'user': {
                '_id': str(user['_id']),
                'name': user.get('name',''),
                'email': user.get('email',''),
                'role': user.get('role','student'),
                'college': user.get('college',''),
                'avatar': user.get('avatar',''),
                'auth_provider': 'google'
            },
            'is_new_user': is_new
        })
        set_access_cookies(response, token)
        return response, 200
        
    except ValueError as ve:
        return jsonify({'error': 'Invalid Google token'}), 401
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@auth_bp.route('/me', methods=['GET'])
def me():
    from flask_jwt_extended import jwt_required
    from app.utils import get_current_user

    @jwt_required()
    def _me():
        user = get_current_user()
        if not user:
            return jsonify({'message': 'User not found'}), 404
        return jsonify(serialize_doc(user))

    return _me()


@auth_bp.route('/me', methods=['PUT'])
def update_me():
    from flask_jwt_extended import jwt_required, get_jwt_identity
    from bson import ObjectId

    @jwt_required()
    def _update_me():
        user_id = get_jwt_identity()
        data = request.get_json()
        updates = {}

        if data.get('name', '').strip():
            updates['name'] = data['name'].strip()
        if 'college' in data:
            updates['college'] = data['college'].strip()
        if 'department' in data:
            updates['department'] = data['department'].strip()
        if 'phone' in data:
            updates['phone'] = data['phone'].strip()
        if 'avatar' in data:
            updates['avatar'] = data['avatar'].strip()

        if data.get('password'):
            if len(data['password']) < 8:
                return jsonify({'message': 'Password must be at least 8 characters'}), 400
            updates['password'] = bcrypt.generate_password_hash(data['password'], 12).decode('utf-8')

        if updates:
            mongo.db.users.update_one({'_id': ObjectId(user_id)}, {'$set': updates})

        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if user:
            user.pop('password', None)
            return jsonify({'user': serialize_doc(user), 'message': 'Profile updated successfully'})
        return jsonify({'message': 'User not found'}), 404

    return _update_me()
