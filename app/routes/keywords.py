from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from app import mongo
from app.utils import get_current_user

keywords_bp = Blueprint('keywords', __name__)


@keywords_bp.route('/', methods=['GET'])
@jwt_required()
def get_keywords():
    user = get_current_user()
    return jsonify({'keywords': user.get('keywords', [])})


@keywords_bp.route('/', methods=['PUT'])
@jwt_required()
def update_keywords():
    user = get_current_user()
    data = request.get_json()

    if not isinstance(data.get('keywords'), list):
        return jsonify({'message': 'Keywords must be an array'}), 400

    # Clean and limit keywords
    cleaned = list(set(
        kw.strip().lower()
        for kw in data['keywords']
        if isinstance(kw, str) and kw.strip()
    ))[:20]

    mongo.db.users.update_one(
        {'_id': user['_id']},
        {'$set': {'keywords': cleaned}}
    )

    return jsonify({'keywords': cleaned})
