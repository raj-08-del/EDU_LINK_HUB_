from flask import Blueprint, request, jsonify, send_from_directory, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from datetime import datetime
import os
from werkzeug.utils import secure_filename
from app import mongo
from app.utils import serialize_doc

resources_bp = Blueprint('resources', __name__)

# ── Feature 2: Resource Library ──────────────────────────────────────────────

@resources_bp.route('/dept/<dept_id>', methods=['GET'])
def get_dept_resources(dept_id):
    """
    Returns resources for a department, grouped by semester.
    Params: ?semester=1&type=notes&search=maths
    """
    try:
        semester = request.args.get('semester')
        resource_type = request.args.get('type')
        search = request.args.get('search')

        query = {'department_id': ObjectId(dept_id)}
        if semester and semester != 'all': query['semester'] = int(semester)
        if resource_type and resource_type != 'all': query['resource_type'] = resource_type
        if search:
            query['$or'] = [
                {'title': {'$regex': search, '$options': 'i'}},
                {'subject': {'$regex': search, '$options': 'i'}}
            ]

        resources = list(mongo.db.dept_resources.find(query).sort('created_at', -1))
        
        # Grouping logic
        grouped = {}
        for r in resources:
            sem_key = f"Semester {r.get('semester')}" if r.get('semester') != 0 else "General"
            if sem_key not in grouped: grouped[sem_key] = []
            grouped[sem_key].append(serialize_doc(r))

        return jsonify(grouped), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@resources_bp.route('/dept/<dept_id>', methods=['POST'])
@jwt_required()
def upload_resource(dept_id):
    """Upload a resource for a department."""
    try:
        user_id = get_jwt_identity()
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        # Validate file size
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)

        # Max sizes: PDF/DOC/PPT: 20MB, Images: 5MB, Video: 100MB, Audio: 20MB
        ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
        max_size = 20 * 1024 * 1024 # Default 20MB
        if ext in ['jpg', 'jpeg', 'png', 'gif']: max_size = 5 * 1024 * 1024
        elif ext in ['mp4', 'webm', 'mov']: max_size = 100 * 1024 * 1024
        elif ext in ['mp3', 'wav']: max_size = 20 * 1024 * 1024

        if size > max_size:
            return jsonify({'error': f'File too large for this type (max {max_size/1e6}MB)'}), 400

        # Save file
        upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'resources')
        if not os.path.exists(upload_dir): os.makedirs(upload_dir)
        
        filename = secure_filename(f"{datetime.utcnow().timestamp()}_{file.filename}")
        file_path = os.path.join(upload_dir, filename)
        file.save(file_path)

        # Metadata
        title = request.form.get('title', 'Untitled Resource')
        description = request.form.get('description', '')
        semester = int(request.form.get('semester', 0))
        subject = request.form.get('subject', '')
        res_type = request.form.get('resource_type', 'other')
        tags = [t.strip() for t in request.form.get('tags', '').split(',') if t.strip()]
        academic_year = request.form.get('academic_year', '')

        resource_doc = {
            'college_id': ObjectId(request.form.get('college_id')),
            'department_id': ObjectId(dept_id),
            'title': title,
            'description': description,
            'semester': semester,
            'subject': subject,
            'resource_type': res_type,
            'tags': tags,
            'academic_year': academic_year,
            'uploaded_by': ObjectId(user_id),
            'file': {
                'url': f'/static/uploads/resources/{filename}',
                'filename': filename,
                'original_name': file.filename,
                'file_type': ext,
                'file_size': size,
                'mime_type': file.content_type
            },
            'upvotes': [],
            'download_count': 0,
            'is_verified': False,
            'created_at': datetime.utcnow()
        }

        result = mongo.db.dept_resources.insert_one(resource_doc)
        return jsonify({'message': 'Resource uploaded', 'id': str(result.inserted_id)}), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@resources_bp.route('/<resource_id>/download', methods=['GET'])
@jwt_required()
def download_resource(resource_id):
    """Download a resource and increment count."""
    try:
        resource = mongo.db.dept_resources.find_one({'_id': ObjectId(resource_id)})
        if not resource: return jsonify({'error': 'Not found'}), 404

        mongo.db.dept_resources.update_one(
            {'_id': ObjectId(resource_id)}, 
            {'$inc': {'download_count': 1}}
        )

        upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'resources')
        return send_from_directory(upload_dir, resource['file']['filename'], as_attachment=True, download_name=resource['file']['original_name'])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@resources_bp.route('/<resource_id>', methods=['DELETE'])
@jwt_required()
def delete_resource(resource_id):
    """Delete a resource."""
    try:
        user_id = get_jwt_identity()
        resource = mongo.db.dept_resources.find_one({'_id': ObjectId(resource_id)})
        if not resource: return jsonify({'error': 'Not found'}), 404

        # Check permission: Only owner or admin
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if str(resource['uploaded_by']) != str(user_id) and user.get('role') != 'admin':
            return jsonify({'error': 'Unauthorized'}), 403

        # Delete physical file
        try:
            file_path = os.path.join(current_app.root_path, 'static', 'uploads', 'resources', resource['file']['filename'])
            if os.path.exists(file_path): os.remove(file_path)
        except: pass

        mongo.db.dept_resources.delete_one({'_id': ObjectId(resource_id)})
        return jsonify({'message': 'Resource deleted'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@resources_bp.route('/<resource_id>/upvote', methods=['PATCH'])
@jwt_required()
def upvote_resource(resource_id):
    """Toggle upvote for a resource."""
    try:
        user_id = get_jwt_identity()
        resource = mongo.db.dept_resources.find_one({'_id': ObjectId(resource_id)})
        if not resource: return jsonify({'error': 'Not found'}), 404

        upvotes = resource.get('upvotes', [])
        user_obj_id = ObjectId(user_id)
        
        if user_obj_id in upvotes:
            mongo.db.dept_resources.update_one({'_id': ObjectId(resource_id)}, {'$pull': {'upvotes': user_obj_id}})
            active = False
        else:
            mongo.db.dept_resources.update_one({'_id': ObjectId(resource_id)}, {'$addToSet': {'upvotes': user_obj_id}})
            active = True

        return jsonify({'active': active, 'count': len(upvotes) + (1 if active else -1)}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@resources_bp.route('/dept/<dept_id>/stats', methods=['GET'])
def get_resource_stats(dept_id):
    """Returns resource usage statistics for a department."""
    try:
        resources = list(mongo.db.dept_resources.find({'department_id': ObjectId(dept_id)}))
        
        stats = {
            'total_resources': len(resources),
            'by_semester': {},
            'by_type': {},
            'top_downloaded': [],
            'recently_added': []
        }

        # Calculation
        for r in resources:
            sem = r.get('semester', 0)
            rtype = r.get('resource_type', 'other')
            stats['by_semester'][sem] = stats['by_semester'].get(sem, 0) + 1
            stats['by_type'][rtype] = stats['by_type'].get(rtype, 0) + 1

        # Sorted results
        stats['top_downloaded'] = serialize_doc(sorted(resources, key=lambda x: x.get('download_count', 0), reverse=True)[:5])
        stats['recently_added'] = serialize_doc(sorted(resources, key=lambda x: x.get('created_at'), reverse=True)[:5])
        
        return jsonify(stats), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
