from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from bson import ObjectId
from datetime import datetime
from app import mongo
from app.utils import serialize_doc, get_current_user, role_required
import logging

reports_bp = Blueprint('reports', __name__)

@reports_bp.route('/', methods=['POST'])
@jwt_required()
def submit_report():
    user = get_current_user()
    data = request.get_json() or {}

    content_id = data.get('contentId') or data.get('item_id')
    content_type = data.get('contentType') or data.get('item_type')
    content_title = data.get('contentTitle') or data.get('item_title') or 'Untitled Content'
    reason = data.get('reason', '').strip()
    description = data.get('description', '').strip()

    if not content_id or not content_type:
        return jsonify({'message': 'contentId and contentType required'}), 400

    try:
        content_oid = ObjectId(content_id)
    except Exception:
        return jsonify({'message': 'Invalid contentId'}), 400

    report = {
        'contentType': content_type,
        'contentId': content_oid,
        'contentTitle': content_title,
        'reportedBy': user['_id'],
        'reportedByName': user['name'],
        'reason': reason or 'No reason provided',
        'description': description,
        'status': 'pending',
        'createdAt': datetime.utcnow()
    }
    
    mongo.db.reports.insert_one(report)

    # Notify all admins
    from app.services.notification_service import create_notification
    admins = mongo.db.users.find({'role': 'admin'})
    for admin in admins:
        create_notification(
            user_id=admin['_id'],
            notif_type='report_alert',
            message=f'🚩 A {content_type} has been reported: {content_title}. Review required.',
            link='/admin'
        )

    return jsonify({'message': 'Report submitted successfully'}), 201

def calculate_urgency(total_count, reasons):
    """Calculate urgency level based on count and reason similarity."""
    if not reasons:
        return 'low'
    
    # Check for 5+ same reason
    reason_counts = {}
    for r in reasons:
        reason_counts[r] = reason_counts.get(r, 0) + 1
        if reason_counts[r] >= 5:
            return 'critical'
            
    if total_count >= 4:
        return 'high'
    if total_count >= 2:
        return 'medium'
    return 'low'

@reports_bp.route('/', methods=['GET'])
@jwt_required()
@role_required('admin')
def list_reports():
    status_filter = request.args.get('status', 'pending')
    
    # 1. Pipeline for grouping by contentId
    pipeline = []
    if status_filter != 'all':
        pipeline.append({'$match': {'status': status_filter}})
    
    pipeline.extend([
        {
            '$group': {
                '_id': {
                    'contentId': '$contentId',
                    'contentType': '$contentType'
                },
                'report_count': {'$sum': 1},
                'reasons': {'$push': '$reason'},
                'latest_at': {'$max': '$createdAt'},
                'status': {'$first': '$status'},
                'report_ids': {'$push': '$_id'}
            }
        },
        {'$sort': {'report_count': -1, 'latest_at': -1}}
    ])
    
    report_groups = list(mongo.db.reports.aggregate(pipeline))
    
    # Summary counts
    pending_count = mongo.db.reports.count_documents({'status': 'pending'})
    total_count = mongo.db.reports.count_documents({})
    
    results = []
    for group in report_groups:
        _id_data = group.get('_id') or {}
        item_id = _id_data.get('contentId')
        item_type = _id_data.get('contentType')
        
        if not item_id: continue
        
        # Determine existence and fetch title/url
        item_exists = False
        item_title = 'Deleted Content'
        item_url = '#'
        
        try:
            if item_type == 'opportunity':
                item = mongo.db.opportunities.find_one({'_id': ObjectId(item_id)})
                if item:
                    item_exists = True
                    item_title = f"{item.get('role', 'Opportunity')} — {item.get('company', 'Unknown')}"
                    item_url = f"/opportunities?highlight={item_id}"
            elif item_type == 'event':
                item = mongo.db.events.find_one({'_id': ObjectId(item_id)})
                if item:
                    item_exists = True
                    item_title = item.get('title', 'Untitled Event')
                    item_url = f"/explore?highlight={item_id}"
            elif item_type == 'post':
                item = mongo.db.community_posts.find_one({'_id': ObjectId(item_id)})
                if item:
                    item_exists = True
                    item_title = item.get('title', 'Community Post')
                    item_url = f"/community/{item_id}"
            elif item_type == 'forum post':
                item_title = "Forum Post"
                item_url = f"/forums/post/{item_id}"
                item = mongo.db.forum_posts.find_one({'_id': ObjectId(item_id)})
                if item:
                    item_exists = True
                    item_title = item.get('title', 'Forum Post')
                    item_url = f"/forums/any/{item_id}"
        except Exception:
            pass

        # Fetch ALL individual reports for this item (No limit)
        report_details = []
        try:
            indiv_reports = list(mongo.db.reports.find(
                {'contentId': ObjectId(item_id)}
            ).sort('createdAt', -1))
            
            for r in indiv_reports:
                # Fetch reporter name if needed (optional since stored in reportedByName)
                reporter_name = r.get('reportedByName') or 'Anonymous User'
                
                report_details.append({
                    'report_id': str(r['_id']),
                    'reporter_name': reporter_name,
                    'reason': r.get('reason', 'other'),
                    'description': r.get('description', ''),
                    'comment': r.get('description', ''), # For frontend compatibility
                    'created_at': r['createdAt'].strftime('%d %b %Y, %I:%M %p') if 'createdAt' in r else 'N/A',
                    'status': r.get('status', 'pending')
                })
        except Exception:
            pass

        results.append({
            'item_id': str(item_id),
            'item_type': item_type,
            'item_title': item_title,
            'item_url': item_url,
            'item_exists': item_exists,
            'report_count': len(report_details),
            'latest_at': group['latest_at'].strftime('%d %b %Y, %I:%M %p') if hasattr(group['latest_at'], 'strftime') else str(group['latest_at']),
            'status': group['status'],
            'urgency': calculate_urgency(group['report_count'], group['reasons']),
            'report_details': report_details,
            'report_ids': [str(rid) for rid in group.get('report_ids', [])]
        })

    return jsonify({
        'pending_count': pending_count,
        'total_count': total_count,
        'reports': results
    })

@reports_bp.route('/item/<item_id>', methods=['GET'])
@jwt_required()
@role_required('admin')
def get_item_reports(item_id):
    """Get all individual reports for one content item."""
    try:
        reports = list(mongo.db.reports.find(
            {'contentId': ObjectId(item_id)}
        ).sort('createdAt', -1))
        
        result = []
        for r in reports:
            reporter = None
            if r.get('reportedBy'):
                try:
                    reporter = mongo.db.users.find_one(
                        {'_id': r['reportedBy']},
                        {'name': 1, 'email': 1, 'college': 1}
                    )
                except:
                    pass
            
            result.append({
                '_id': str(r['_id']),
                'reporter_name': reporter.get('name', r.get('reportedByName', 'Anonymous')) if reporter else r.get('reportedByName', 'Anonymous'),
                'reporter_college': reporter.get('college', '') if reporter else '',
                'reason': r.get('reason', ''),
                'description': r.get('description', ''),
                'created_at': r['createdAt'].strftime('%d %b %Y, %I:%M %p') if r.get('createdAt') else '',
                'status': r.get('status', 'pending')
            })
        
        return jsonify({
            'reports': result,
            'total': len(result)
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@reports_bp.route('/resolve', methods=['PATCH', 'POST'])
@jwt_required()
@role_required('admin')
def resolve_all_for_item():
    """Marks all reports for a specific item as resolved."""
    data = request.get_json() or {}
    item_id = data.get('item_id')
    item_type = data.get('item_type')
    
    if not item_id or not item_type:
        return jsonify({'message': 'item_id and item_type required'}), 400
        
    try:
        result = mongo.db.reports.update_many(
            {'contentId': ObjectId(item_id), 'contentType': item_type},
            {'$set': {'status': 'resolved', 'resolvedAt': datetime.utcnow()}}
        )
        return jsonify({
            'message': 'Reports resolved for this item',
            'resolved_count': result.modified_count
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@reports_bp.route('/pending-count', methods=['GET'])
@jwt_required()
@role_required('admin')
def get_count_simple():
    count = mongo.db.reports.count_documents({'status': 'pending'})
    return jsonify({'count': count})

@reports_bp.route('/delete', methods=['DELETE', 'POST'])
@jwt_required()
@role_required('admin')
def delete_reports_legacy():
    # Keep for backwards compatibility or refine to resolve
    data = request.get_json() or {}
    report_ids = data.get('report_ids', [])
    if not report_ids and 'reportId' in data:
        report_ids = [data['reportId']]
        
    if not report_ids:
        return jsonify({'message': 'report_ids required'}), 400
        
    try:
        oids = [ObjectId(rid) for rid in report_ids]
        result = mongo.db.reports.update_many(
            {'_id': {'$in': oids}},
            {'$set': {'status': 'resolved', 'deletedAt': datetime.utcnow()}}
        )
        return jsonify({'message': f'Marked {result.modified_count} reports as resolved/deleted'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@reports_bp.route('/<report_id>/resolve', methods=['POST'])
@jwt_required()
@role_required('admin')
def resolve_single_report(report_id):
    """Mark a single report as resolved."""
    try:
        result = mongo.db.reports.update_one(
            {'_id': ObjectId(report_id)},
            {'$set': {'status': 'resolved', 'resolvedAt': datetime.utcnow()}}
        )
        if result.matched_count == 0:
            return jsonify({'message': 'Report not found'}), 404
        return jsonify({'message': 'Report resolved'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@reports_bp.route('/<report_id>', methods=['DELETE'])
@jwt_required()
@role_required('admin')
def delete_single_report(report_id):
    """Permanently delete a single report entry."""
    try:
        result = mongo.db.reports.delete_one({'_id': ObjectId(report_id)})
        if result.deleted_count == 0:
            return jsonify({'message': 'Report not found'}), 404
        return jsonify({'message': 'Report deleted'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
