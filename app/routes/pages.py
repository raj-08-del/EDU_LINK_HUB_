from flask import Blueprint, render_template, session, send_from_directory, Response, request, jsonify, current_app
from collections import defaultdict
from flask_jwt_extended import verify_jwt_in_request, jwt_required, get_jwt_identity
from app import mongo
from bson import ObjectId
from bson.errors import InvalidId
from app.utils import get_current_user
from app.services.leaderboard_service import get_leaderboard_rankings
import secrets
import time
import os
import traceback
from dotenv import load_dotenv

load_dotenv()

from app.utils_security import sanitize_input
from flask import redirect, url_for

pages_bp = Blueprint('pages', __name__)

@pages_bp.before_request
def enforce_profile_completion():
    # Exempt essential routes and static/API requests
    exempt_endpoints = [
        'pages.login_page', 
        'pages.register_page', 
        'pages.index', 
        'pages.settings_page',
        'pages.service_worker',
        'pages.offline_page',
        'pages.reset_password_page'
    ]
    
    if request.endpoint in exempt_endpoints or request.path.startswith('/static') or request.path.startswith('/api'):
        return

    # Optimization: Use session to remember if profile is already verified as complete
    if session.get('profile_complete') is True:
        return

    try:
        verify_jwt_in_request(optional=True)
        user = get_current_user()
        
        if user:
            # Mandatory fields check
            is_incomplete = not user.get('name') or not user.get('college') or not user.get('department') or not user.get('phone')
            
            if is_incomplete:
                return redirect(url_for('pages.settings_page', incomplete='true'))
            else:
                # Cache the result in session to speed up the next page load
                session['profile_complete'] = True
    except Exception as e:
        pass

@pages_bp.route('/')
def index():
    google_client_id = os.environ.get('GOOGLE_CLIENT_ID', '')
    return render_template('login.html', google_client_id=google_client_id)


@pages_bp.route('/login')
def login_page():
    google_client_id = os.environ.get('GOOGLE_CLIENT_ID', '')
    return render_template('login.html', google_client_id=google_client_id)


@pages_bp.route('/reset-password')
def reset_password_page():
    token = request.args.get('token', '')
    google_client_id = os.environ.get('GOOGLE_CLIENT_ID', '')
    return render_template('reset_password.html', token=token, google_client_id=google_client_id)


@pages_bp.route('/register')
def register_page():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    start_time = int(time.time())
    
    google_client_id = os.environ.get('GOOGLE_CLIENT_ID', '')
    
    return render_template('register.html', 
                           csrf_token=session['csrf_token'], 
                           form_start_time=start_time,
                           google_client_id=google_client_id)





@pages_bp.route('/dashboard')
def dashboard_page():
    try:
        verify_jwt_in_request(optional=True)
        user = get_current_user()
    except:
        user = None
    
    # 1. Base counts (Public)
    try:
        campus_events_count = mongo.db.events.count_documents({"is_hidden": {"$ne": True}})
    except Exception:
        campus_events_count = 0
        
    try:
        opportunities_count = mongo.db.opportunities.count_documents({"status": "approved", "is_archived": {"$ne": True}})
    except Exception:
        opportunities_count = 0
        
    try:
        community_posts_count = mongo.db.community_posts.count_documents({"is_hidden": {"$ne": True}, "status": {"$ne": "archived"}})
    except Exception:
        community_posts_count = 0
        
    try:
        communities_count = mongo.db.colleges.count_documents({})
    except Exception:
        communities_count = 0
    
    # 2. User-specific counts
    notifications_count = 0
    study_groups_count = 0
    saved_items_count = 0
    leaderboard_rank = "Unranked"
    
    if user:
        try:
            user_id = user['_id']
            try:
                notifications_count = mongo.db.notifications.count_documents({'user_id': user_id, 'read': False})
            except Exception:
                notifications_count = 0
                
            try:
                study_groups_count = mongo.db.study_groups.count_documents({'members': user_id})
            except Exception:
                study_groups_count = 0
                
            # Fix saved items count — check ALL possible storage methods:
            try:
                # Method A — if bookmarks stored inside user document:
                bookmarks_in_user = len(user.get('bookmarks', [])) if user else 0

                # Method B — if bookmarks stored in separate collection:
                # Try ALL common field names and ID formats
                count_userId_oid = mongo.db.bookmarks.count_documents({"userId": user_id})
                count_userId_str = mongo.db.bookmarks.count_documents({"userId": str(user_id)})
                count_user_id_oid = mongo.db.bookmarks.count_documents({"user_id": user_id})
                count_user_id_str = mongo.db.bookmarks.count_documents({"user_id": str(user_id)})
                
                bookmarks_in_collection = max(count_userId_oid, count_userId_str, count_user_id_oid, count_user_id_str)

                # Method C — if saved_items is a separate field:
                saved_items_field = len(user.get('saved_items', [])) if user else 0

                # Use the correct one based on highest count:
                saved_items_count = max(
                    bookmarks_in_user,
                    bookmarks_in_collection,
                    saved_items_field
                )
            except Exception as e:
                print(f"Saved items calculation error: {e}")
                saved_items_count = 0
                
            # Fixed: Real-time leaderboard rank from persistent 'leaderboard' collection
            try:
                user_lb = mongo.db.leaderboard.find_one({'user_id': user_id})
                if user_lb:
                    pts = user_lb.get('points', 0)
                    higher_count = mongo.db.leaderboard.count_documents({'points': {'$gt': pts}})
                    leaderboard_rank = f"#{higher_count + 1}"
                else:
                    leaderboard_rank = "Unranked"
            except Exception:
                leaderboard_rank = "Unranked"
        except Exception:
            pass

    # 3. Admin Reports (Grouped by Item)
    # This is now handled entirely client-side via JavaScript loading from /api/reports/

    return render_template('dashboard.html', 
                           current_user=user, 
                           campus_events_count=campus_events_count,
                           opportunities_count=opportunities_count,
                           community_posts_count=community_posts_count,
                           notifications_count=notifications_count,
                           study_groups_count=study_groups_count,
                           saved_items_count=saved_items_count,
                           communities_count=communities_count,
                           leaderboard_rank=leaderboard_rank)


@pages_bp.route('/api/debug/saved-items', methods=['GET'])
@jwt_required()
def debug_saved_items():
    from bson import ObjectId
    from flask_jwt_extended import get_jwt_identity
    try:
        uid_str = get_jwt_identity()
        uid = ObjectId(str(uid_str))

        # Check every possible location
        user = mongo.db.users.find_one({"_id": uid})
        
        results = {
            "user_id": uid_str,
            "bookmarks_in_user_doc": len(user.get('bookmarks', [])) if user else 0,
            "saved_items_in_user_doc": len(user.get('saved_items', [])) if user else 0,
            "user_doc_keys": list(user.keys()) if user else [],
            "bookmarks_collection_by_userId_oid": mongo.db.bookmarks.count_documents({"userId": uid}),
            "bookmarks_collection_by_userId_str": mongo.db.bookmarks.count_documents({"userId": uid_str}),
            "bookmarks_collection_by_user_id_oid": mongo.db.bookmarks.count_documents({"user_id": uid}),
            "bookmarks_collection_by_user_id_str": mongo.db.bookmarks.count_documents({"user_id": uid_str}),
            "all_collections": mongo.db.list_collection_names(),
            "sample_bookmark_doc": str(mongo.db.bookmarks.find_one()),
            "sample_user_bookmarks": str(user.get('bookmarks', [])[:2]) if user else "none"
        }
        
        print("=== SAVED ITEMS DEBUG ===")
        for k, v in results.items():
            print(f"{k}: {v}")
        
        return jsonify(results), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@pages_bp.route('/explore')
def explore_page():
    try:
        verify_jwt_in_request(optional=True)
        user = get_current_user()
    except:
        user = None
    return render_template('explore.html', 
                           user=user, 
                           current_user_role=(user.get('role') or 'student').lower() if user else 'student')


@pages_bp.route('/opportunities')
def opportunities_page():
    try:
        # DB Connection Guard
        if mongo.db is None:
            current_app.logger.error("Database connection unavailable")
            return jsonify({"message": "Database connection unavailable"}), 503

        category = request.args.get('category')
        query = {'status': 'approved', 'is_archived': {'$ne': True}}
        if category and category != 'all':
            query['category'] = category
        
        opps = list(mongo.db.opportunities.find(query).sort('created_at', -1))
        
        try:
            verify_jwt_in_request(optional=True)
            user = get_current_user()
            user_id = user['_id'] if user else None
        except:
            user = None
            user_id = None

        # Batch fetch statuses if user logged in
        user_statuses = {}
        if user_id:
            try:
                status_docs = mongo.db.opportunity_status.find({
                    'user_id': ObjectId(user_id),
                    'opportunity_id': {'$in': [o['_id'] for o in opps]}
                })
                user_statuses = {str(d['opportunity_id']): d['status'] for d in status_docs}
            except Exception as e:
                current_app.logger.error(f"Status fetch error: {e}")

        # Data Processing with dictionary safety
        processed_opps = []
        from datetime import date
        for opp in opps:
            try:
                # Basic Fields with .get()
                opp['company'] = opp.get('company', 'Unknown Company')
                opp['role'] = opp.get('role', 'Unknown Role')
                
                # Creator Info
                creator_id = opp.get('created_by')
                if creator_id:
                    creator = mongo.db.users.find_one({'_id': ObjectId(creator_id)}, {'name': 1, 'college': 1, 'is_verified_organizer': 1})
                    opp['creator_is_verified'] = creator.get('is_verified_organizer', False) if creator else False
                    # Only expose real creator name to admin
                    if user and (user.get('role') or '').lower() == 'admin' and creator:
                        opp['creator_name'] = creator.get('name', '')
                else:
                    opp['creator_is_verified'] = False
                    opp['creator_name'] = None

                # Ownership
                opp['is_owner'] = True if (user_id and str(opp.get('created_by')) == str(user_id)) else False

                # Personal Status
                opp['user_status'] = user_statuses.get(str(opp['_id']), 'Saved')

                # Deadline & Days Left
                deadline = opp.get('deadline', '')
                opp['days_left'] = None
                if deadline:
                    try:
                        opp['days_left'] = (date.fromisoformat(deadline) - date.today()).days
                    except (ValueError, TypeError):
                        pass
                
                processed_opps.append(opp)
            except Exception as e:
                current_app.logger.error(f"Single opportunity processing error: {e}")
                # Skip bad document instead of crashing
                continue
            
        return render_template('opportunities.html', opportunities=processed_opps, current_user=user)

    except Exception as e:
        current_app.logger.error(f"Opportunities page global error: {e}")
        current_app.logger.error(traceback.format_exc())
        return jsonify({
            "message": "Failed to load opportunities",
            "error": str(e)
        }), 500


@pages_bp.route('/opportunities/<opp_id>')
def opportunity_detail_page(opp_id):
    try:
        verify_jwt_in_request(optional=True)
        user = get_current_user()
    except:
        user = None

    try:
        from datetime import date
        opp = mongo.db.opportunities.find_one({'_id': ObjectId(opp_id)})
        if not opp:
            return render_template('offline.html', message="Opportunity not found"), 404
        
        # Data Processing
        opp['company'] = opp.get('company', 'Unknown Company')
        opp['role'] = opp.get('role', 'Unknown Role')
        
        creator_id = opp.get('created_by')
        creator = None
        if creator_id:
            creator = mongo.db.users.find_one({'_id': ObjectId(creator_id)}, {'name': 1, 'college': 1, 'is_verified_organizer': 1})
            opp['creator_is_verified'] = creator.get('is_verified_organizer', False) if creator else False
            # Only expose real creator name to admin
            if user and (user.get('role') or '').lower() == 'admin' and creator:
                opp['creator_name'] = creator.get('name', '')
        else:
            opp['creator_is_verified'] = False
            opp['creator_name'] = None

        opp['is_owner'] = True if (user and str(opp.get('created_by')) == str(user['_id'])) else False
        
        deadline = opp.get('deadline', '')
        opp['days_left'] = None
        if deadline:
            try:
                opp['days_left'] = (date.fromisoformat(deadline) - date.today()).days
            except:
                pass

        return render_template('opportunity_detail.html', opp=opp, creator=creator, current_user=user)

    except InvalidId:
        return render_template('offline.html', message="Invalid opportunity ID"), 400
    except Exception as e:
        current_app.logger.error(f"Detail page error: {e}")
        return render_template('offline.html', message="An error occurred"), 500


@pages_bp.route('/community')
def community_page():
    try:
        verify_jwt_in_request(optional=True)
        user = get_current_user()
    except Exception as jwt_err:
        print("JWT Verification Note:", jwt_err)
        user = None
    
    return render_template('community.html', current_user=user)


@pages_bp.route('/community/<post_id>')
def community_post_page(post_id):
    try:
        verify_jwt_in_request(optional=True)
        user = get_current_user()
    except:
        user = None
    return render_template('community_post.html', post_id=post_id, current_user=user)


@pages_bp.route('/admin')
@jwt_required()
def admin_page():
    user = get_current_user()
    if not user or user.get('role') not in ['admin', 'moderator']:
        return render_template('offline.html', message="Unauthorized"), 403
        
    reports = list(mongo.db.reports.find({}).sort('createdAt', -1))
    for r in reports:
        r['_id'] = str(r['_id'])
        r['contentId'] = str(r.get('contentId', ''))
        # Resolve content link if possible
        t = r.get('contentType')
        cid = r.get('contentId')
        if t == 'opportunity': r['content_link'] = f"/opportunities?highlight={cid}"
        elif t == 'event': r['content_link'] = f"/explore?highlight={cid}"
        elif t == 'post' or t == 'community_post': r['content_link'] = f"/community/{cid}"
        elif t == 'group' or t == 'study_group': r['content_link'] = f"/study-groups/{cid}"
        elif t == 'forum_post': r['content_link'] = f"/forums/{r.get('forumSlug', 'general')}?post={cid}"
        else: r['content_link'] = "#"

    pending_count = mongo.db.reports.count_documents({'status': 'pending'})
    resolved_count = mongo.db.reports.count_documents({'status': 'resolved'})
    total_count = len(reports)
    
    return render_template('admin.html', 
                           user=user, 
                           reports=reports,
                           pending_count=pending_count,
                           total_count=total_count,
                           resolved_count=resolved_count)


@pages_bp.route('/moderate')
def moderate_page():
    return render_template('moderate.html')


@pages_bp.route('/settings')
def settings_page():
    return render_template('settings.html')





@pages_bp.route('/notifications')
def notifications_page():
    return render_template('notifications.html')


@pages_bp.route('/notifications/keywords')
def notifications_keywords_page():
    return render_template('keyword_alerts.html')


@pages_bp.route('/study-groups')
@jwt_required()
def study_groups_page():
    try:
        user = get_current_user()
        if not user:
            return render_template('login.html'), 401
            
        user_id = user['_id']
        user_role = user.get('role', 'student')

        if user_role == 'admin':
            # Admin sees all groups
            all_groups = list(mongo.db.study_groups.find({}))
        else:
            # Regular users see public groups, groups they created, or groups they are members of
            all_groups = list(mongo.db.study_groups.find({
                "$or": [
                    {"is_private": {"$ne": True}},
                    {"created_by": user_id},
                    {"members": user_id}
                ]
            }))

        for g in all_groups:
            g['_id'] = str(g['_id'])
            g['created_by'] = str(g.get('created_by', ''))
            g['is_private'] = g.get('is_private', False)
            # Ensure members list is serialized for Jinja2 checks
            if 'members' in g:
                g['members'] = [m if isinstance(m, str) else str(m) for m in g['members']]
            else:
                g['members'] = []

            # Only expose creator name to admin
            if user_role == 'admin':
                cid = g.get('created_by')
                if cid:
                    creator = mongo.db.users.find_one({'_id': ObjectId(cid)}, {'name': 1})
                    g['creator_name'] = creator.get('name', 'Anonymous') if creator else 'Deleted User'
                else:
                    g['creator_name'] = 'Anonymous'
            else:
                g['creator_name'] = None

        return render_template('study_groups.html',
            groups=all_groups,
            current_user_id=str(user_id),
            current_user_role=user_role
        )
    except Exception as e:
        traceback.print_exc()
        return render_template('offline.html', message=f"Internal Server Error: {str(e)}"), 500


@pages_bp.route('/study-groups/<group_id>')
def study_group_room_page(group_id):
    try:
        verify_jwt_in_request(optional=True)
        user = get_current_user()
    except:
        user = None
    group = mongo.db.study_groups.find_one({'_id': ObjectId(group_id)})
    if not group:
        return "Group not found", 404
        
    is_creator = False
    if user and str(group.get('created_by')) == str(user.get('_id')):
        is_creator = True

    is_admin = user and user.get('role') in ['admin', 'moderator']

    return render_template('study_group_room.html', 
                           group_id=group_id, 
                           group=group, 
                           user=user, 
                           is_creator=is_creator,
                           is_admin=is_admin)


@pages_bp.route('/leaderboard')
@jwt_required(optional=True)
def leaderboard_page():
    try:
        from bson import ObjectId
        from flask_jwt_extended import get_jwt_identity
        jwt_identity = get_jwt_identity()

        # Step 4 - Debug: Print what MongoDB actually has
        sample = mongo.db.leaderboard.find_one()
        print("Sample leaderboard document:", sample)

        # 1. Try leaderboard collection first
        leaders_from_lb = list(mongo.db.leaderboard.find().sort("points", -1).limit(50))

        if not leaders_from_lb:
            # 2. Fall back to users collection points field
            leaders_raw = list(mongo.db.users.find(
                {}, {"name": 1, "college": 1, "points": 1, "total_points": 1}
            ).sort("points", -1).limit(50))
            # Normalize field names for template
            for l in leaders_raw:
                l['college_name'] = l.get('college', 'Pioneer')
                l['points'] = l.get('points', 0)
        else:
            # 3. Enrich leaderboard entries with user data
            leaders_raw = []
            for lb in leaders_from_lb:
                user = mongo.db.users.find_one({"_id": lb['user_id']})
                if user:
                    leaders_raw.append({
                        "_id": lb['user_id'],
                        "name": user.get('name', 'Unknown'),
                        "college_name": user.get('college', 'Pioneer'),
                        "points": lb.get('points', 0)
                    })

        # 4. Get current user rank and points
        current_points = 0
        current_rank = "Unranked"

        if jwt_identity:
            current_lb = mongo.db.leaderboard.find_one({"user_id": ObjectId(str(jwt_identity))})
            if current_lb:
                current_points = current_lb.get('points', 0)
                # Calculate rank
                higher_count = mongo.db.leaderboard.count_documents(
                    {"points": {"$gt": current_points}}
                )
                current_rank = higher_count + 1
            else:
                # Check user document if not in leaderboard yet
                u_doc = mongo.db.users.find_one({"_id": ObjectId(str(jwt_identity))})
                if u_doc:
                    current_points = u_doc.get('points', 0)

        for i, entry in enumerate(leaders_raw):
            entry['_id'] = str(entry.get('_id', ''))
            entry['rank'] = i + 1

        return render_template('leaderboard.html',
            leaders=leaders_raw,
            current_rank=current_rank,
            current_points=current_points,
            current_user_id=str(jwt_identity) if jwt_identity else None
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return render_template('offline.html', message=f"Leaderboard error: {str(e)}"), 500


# ── F4: Bookmarks ────────────────────────────────────────────────────────────
@pages_bp.route('/bookmarks')
def bookmarks_page():
    try:
        verify_jwt_in_request(optional=True)
        user = get_current_user()
    except:
        user = None
    
    archive_events = []
    archive_opportunities = []
    archive_posts = []
    
    if user:
        user_id = user['_id']
        # Fetch hidden items
        archive_events = list(mongo.db.events.find({"created_by": user_id, "is_hidden": True}))
        archive_opportunities = list(mongo.db.opportunities.find({"created_by": user_id, "is_hidden": True}))
        # Community model uses 'author' field
        archive_posts = list(mongo.db.community_posts.find({"author": user_id, "is_hidden": True}))
        
    return render_template('bookmarks.html', 
                           current_user=user,
                           archive_events=archive_events,
                           archive_opportunities=archive_opportunities,
                           archive_posts=archive_posts)





# ── Colleges & Departments ───────────────────────────────────────────────────
@pages_bp.route('/colleges')
def colleges_page():
    try:
        verify_jwt_in_request(optional=True)
        user = get_current_user()
    except:
        user = None
    return render_template('colleges.html', current_user=user)


@pages_bp.route('/colleges/<college_id>')
def college_detail_page(college_id):
    try:
        verify_jwt_in_request(optional=True)
        user = get_current_user()
    except:
        user = None
    
    college = mongo.db.colleges.find_one({'_id': ObjectId(college_id)})
    if not college:
        return render_template('offline.html', message="College not found"), 404
        
    depts = list(mongo.db.departments.find({'college_id': ObjectId(college_id)}))
    
    # Check membership
    is_member = False
    if user:
        is_member = mongo.db.college_members.find_one({
            'user_id': user['_id'], 
            'college_id': ObjectId(college_id)
        }) is not None

    return render_template('college_detail.html', 
                           college=college, 
                           departments=depts, 
                           is_member=is_member, 
                           current_user=user)


@pages_bp.route('/colleges/<college_id>/dept/<dept_id>')
def department(college_id, dept_id):
    try:
        verify_jwt_in_request(optional=True)
        user = get_current_user()
    except:
        user = None
    return render_template('department.html', college_id=college_id, dept_id=dept_id, current_user=user)


@pages_bp.route('/colleges/<college_id>/dept/<dept_id>/resources')
def dept_resources_page(college_id, dept_id):
    try:
        verify_jwt_in_request(optional=True)
        user = get_current_user()
    except:
        user = None
        
    college = mongo.db.colleges.find_one({'_id': ObjectId(college_id)})
    dept = mongo.db.departments.find_one({'_id': ObjectId(dept_id)})
    
    if not college or not dept:
        return render_template('offline.html', message="Resource library not found"), 404
        
    return render_template('dept_resources.html', 
                           college=college, 
                           dept=dept, 
                           current_user=user)


# ── F10: Service Worker — must be served at root scope ───────────────────────
@pages_bp.route('/sw.js')
def service_worker():
    root = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static')
    response = send_from_directory(root, 'sw.js')
    response.headers['Content-Type'] = 'application/javascript'
    response.headers['Service-Worker-Allowed'] = '/'
    return response


# ── F10: Offline fallback page ────────────────────────────────────────────────
@pages_bp.route('/offline')
def offline_page():
    return render_template('offline.html')
