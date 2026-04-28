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
        
        is_admin = False
        try:
            verify_jwt_in_request(optional=True)
            user_id_from_jwt = get_jwt_identity()
            user = None
            if user_id_from_jwt:
                user = mongo.db.users.find_one({'_id': ObjectId(user_id_from_jwt)})
                if user:
                    is_admin = bool(
                        user.get('is_admin') is True or 
                        (user.get('role') or '').lower() == 'admin'
                    )
            user_id = user['_id'] if user else None
        except Exception as e:
            current_app.logger.error(f"Admin check error: {e}")
            user = None
            user_id = None
            is_admin = False

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
            
        return render_template('opportunities.html', opportunities=processed_opps, current_user=user, is_admin=is_admin)

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


@pages_bp.route('/opportunities/<opp_id>/edit')
@jwt_required()
def edit_opportunity_page(opp_id):
    try:
        user = get_current_user()
        opp = mongo.db.opportunities.find_one({'_id': ObjectId(opp_id)})
        
        if not opp:
            return render_template('offline.html', message="Opportunity not found"), 404

        is_owner = str(opp.get('created_by')) == str(user['_id'])
        is_admin = user.get('role') in ['admin', 'moderator']
        
        if not (is_owner or is_admin):
            return render_template('offline.html', message="Forbidden: You cannot edit this opportunity."), 403

        # Convert tags list to comma-separated string for the input field
        if 'tags' in opp and isinstance(opp['tags'], list):
            opp['tags_str'] = ", ".join(opp['tags'])
        else:
            opp['tags_str'] = ""

        return render_template('edit_opportunity.html', opp=opp, current_user=user)

    except InvalidId:
        return render_template('offline.html', message="Invalid opportunity ID"), 400
    except Exception as e:
        current_app.logger.error(f"Edit page error: {e}")
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
def admin_page():
    try:
        verify_jwt_in_request(optional=True)
    except:
        pass
    user = get_current_user()
    if not user or user.get('role') not in ['admin', 'moderator']:
        return redirect(url_for('pages.login_page'))
        
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
def study_groups_page():
    try:
        verify_jwt_in_request(optional=True)
    except:
        pass
    try:
        user = get_current_user()
        if not user:
            return redirect(url_for('pages.login_page'))
            
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
def leaderboard_page():
    try:
        verify_jwt_in_request(optional=True)
    except:
        pass
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
def college_profile(college_id):
    try:
        verify_jwt_in_request(optional=True)
        user = get_current_user()
    except:
        user = None
    
    try:
        college = mongo.db.colleges.find_one({"_id": ObjectId(college_id)})
        if not college:
            return render_template('offline.html', message="College not found"), 404

        # Fetch all related data
        reviews = list(mongo.db.college_reviews.find(
            {"college_id": ObjectId(college_id)}
        ).sort("created_at", -1).limit(20))

        departments = list(mongo.db.departments.find(
            {"college_id": ObjectId(college_id)}
        ))

        # Unified Placements: Merge from all potential collections
        p1 = list(mongo.db.placements.find({"college_id": ObjectId(college_id)}))
        p2 = list(mongo.db.dept_placements.find({"college_id": ObjectId(college_id)}))
        p3 = list(mongo.db.college_placements.find({"college_id": ObjectId(college_id)}))
        
        # Add dept name to dept_placements for display/filtering
        dept_map = {str(d['_id']): d.get('name', 'General') for d in departments}
        for p in (p1 + p2 + p3):
            if 'dept_id' in p:
                p['department'] = dept_map.get(str(p.get('dept_id')), 'General')
            
            # Field Normalization for different schemas
            if not p.get('student_photo') and p.get('photo_url'):
                p['student_photo'] = p.get('photo_url')
            if not p.get('package_lpa') and p.get('package'):
                p['package_lpa'] = p.get('package')
            
        real_p_list = p1 + p2 + p3
        placements = sorted(real_p_list, key=lambda x: x.get('batch_year', 0), reverse=True)

        if not placements:
            # Inject same demo placements used in department.html to maintain consistency
            placements = [
                { '_id': 'demo-p1', 'student_name': 'David Smith', 'company': 'Google', 'package_lpa': 42.5, 'role': 'Software Engineer', 'batch_year': 2024, 'department': 'Computer Science Engineering', 'student_photo': 'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=200' },
                { '_id': 'demo-p2', 'student_name': 'Emily Chen', 'company': 'Microsoft', 'package_lpa': 38.2, 'role': 'Cloud Architect', 'batch_year': 2023, 'department': 'Information Technology', 'student_photo': 'https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=200' },
                { '_id': 'demo-p3', 'student_name': 'Marcus Thorne', 'company': 'Amazon', 'package_lpa': 35.0, 'role': 'SDE', 'batch_year': 2024, 'department': 'Software Engineering', 'student_photo': 'https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=200' }
            ]
        
        real_placement_count = len(placements)

        alumni = list(mongo.db.alumni.find(
            {"college_id": ObjectId(college_id)}
        ).sort("package", -1).limit(10))

        events_gallery = list(mongo.db.college_events.find(
            {"college_id": ObjectId(college_id)}
        ).sort("date", -1).limit(20))

        # Calculate overall ratings
        if reviews:
            avg_rating = sum(r.get('overall_rating', 0) for r in reviews) / len(reviews)
            faculty_avg = sum(r.get('faculty_rating', 0) for r in reviews) / len(reviews)
            infra_avg = sum(r.get('infrastructure_rating', 0) for r in reviews) / len(reviews)
            placement_avg = sum(r.get('placement_rating', 0) for r in reviews) / len(reviews)
            campus_avg = sum(r.get('campus_rating', 0) for r in reviews) / len(reviews)
        else:
            avg_rating = faculty_avg = infra_avg = placement_avg = campus_avg = 0.0

        # Placement stats by year
        placement_stats = {}
        for p in placements:
            year = p.get('batch_year', 'Unknown')
            if year not in placement_stats:
                placement_stats[year] = {
                    "total_placed": 0,
                    "highest_package": 0.0,
                    "average_package": 0.0,
                    "total_package": 0.0
                }
            placement_stats[year]["total_placed"] += 1
            pkg = float(p.get('package_lpa', 0) or 0)
            if pkg > placement_stats[year]["highest_package"]:
                placement_stats[year]["highest_package"] = pkg
            placement_stats[year]["total_package"] += pkg
            
        for year in placement_stats:
            if placement_stats[year]["total_placed"] > 0:
                placement_stats[year]["average_package"] = round(placement_stats[year]["total_package"] / placement_stats[year]["total_placed"], 1)

        # Membership Check
        is_member = False
        if user:
            is_member = mongo.db.college_members.find_one({
                'user_id': user['_id'], 
                'college_id': ObjectId(college_id)
            }) is not None

        return render_template('college_profile.html',
            college=college,
            reviews=reviews,
            placements=placements,
            departments=departments,
            alumni=alumni,
            events_gallery=events_gallery,
            placement_stats=placement_stats,
            avg_rating=round(avg_rating, 1),
            faculty_avg=round(faculty_avg, 1),
            infra_avg=round(infra_avg, 1),
            placement_avg=round(placement_avg, 1),
            campus_avg=round(campus_avg, 1),
            review_count=len(reviews),
            is_member=is_member,
            real_placement_count=real_placement_count,
            current_user=user
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return render_template('offline.html', message=f"Error loading college: {str(e)}"), 500


@pages_bp.route('/colleges/<college_id>/edit')
def edit_college_page(college_id):
    try:
        verify_jwt_in_request(optional=True)
    except:
        pass
    try:
        user = get_current_user()
        if not user:
            return redirect(url_for('pages.login_page'))
        college = mongo.db.colleges.find_one({"_id": ObjectId(college_id)})
        
        if not college:
            return render_template('offline.html', message="College not found"), 404

        is_owner = str(college.get('created_by')) == str(user['_id'])
        is_admin = user.get('role') in ['admin', 'moderator']
        
        if not (is_owner or is_admin):
            return render_template('offline.html', message="Forbidden: You cannot edit this college."), 403

        return render_template('edit_college.html', college=college, current_user=user)

    except InvalidId:
        return render_template('offline.html', message="Invalid college ID"), 400
    except Exception as e:
        current_app.logger.error(f"Edit college page error: {e}")
        return render_template('offline.html', message="An error occurred"), 500


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
