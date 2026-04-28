import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from bson import ObjectId
import hashlib
import os

# ── HELPER: Generate unique ID for deduplication ──
def generate_source_id(title, source):
    return hashlib.md5(f"{title}{source}".encode()).hexdigest()

# ── HELPER: Check if already exists ──
def already_exists(mongo, source_id, collection):
    return mongo.db[collection].find_one({"source_id": source_id}) is not None

# ══════════════════════════════════════════════
# OPPORTUNITIES COLLECTORS
# ══════════════════════════════════════════════

def collect_from_internshala(mongo):
    """Scrape internships from Internshala RSS"""
    try:
        feed = feedparser.parse("https://internshala.com/rss/internships")
        count = 0
        for entry in feed.entries[:20]:
            source_id = generate_source_id(entry.title, "internshala")
            if already_exists(mongo, source_id, "opportunities"):
                continue
            opp = {
                "role": entry.get("title", ""),
                "company": entry.get("author", "Internshala"),
                "category": "internship",
                "description": BeautifulSoup(
                    entry.get("summary", ""), "html.parser"
                ).get_text()[:500],
                "apply_link": entry.get("link", ""),
                "location": "India",
                "eligibility": "Open to All",
                "tags": ["internship", "student"],
                "deadline": str(
                    (datetime.utcnow() + timedelta(days=30)).date()
                ),
                "source": "internshala",
                "source_id": source_id,
                "is_auto_collected": True,
                "is_hidden": False,
                "status": "pending",
                "created_by": None,
                "created_at": datetime.utcnow(),
                "image_url": "",
                "total_reactions": 0
            }
            mongo.db.opportunities.insert_one(opp)
            count += 1
        print(f"[AutoCollector] Internshala: +{count} opportunities")
    except Exception as e:
        print(f"[AutoCollector] Internshala error: {e}")

def collect_from_unstop(mongo):
    """Fetch competitions and opportunities from Unstop RSS"""
    try:
        feed = feedparser.parse("https://unstop.com/api/public/opportunity/rss")
        count = 0
        for entry in feed.entries[:15]:
            source_id = generate_source_id(entry.title, "unstop")
            if already_exists(mongo, source_id, "opportunities"):
                continue
            opp = {
                "role": entry.get("title", ""),
                "company": entry.get("author", "Unstop"),
                "category": "competition",
                "description": BeautifulSoup(
                    entry.get("summary", ""), "html.parser"
                ).get_text()[:500],
                "apply_link": entry.get("link", ""),
                "location": "Online",
                "eligibility": "Open to All",
                "tags": ["competition", "student", "unstop"],
                "deadline": str(
                    (datetime.utcnow() + timedelta(days=20)).date()
                ),
                "source": "unstop",
                "source_id": source_id,
                "is_auto_collected": True,
                "is_hidden": False,
                "status": "pending",
                "created_by": None,
                "created_at": datetime.utcnow(),
                "image_url": "",
                "total_reactions": 0
            }
            mongo.db.opportunities.insert_one(opp)
            count += 1
        print(f"[AutoCollector] Unstop: +{count} opportunities")
    except Exception as e:
        print(f"[AutoCollector] Unstop error: {e}")

def collect_from_adzuna(mongo, app_id, app_key, country="in"):
    """Fetch jobs from Adzuna API (free tier available)"""
    try:
        url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": 10,
            "what": "internship OR graduate OR fresher",
            "content-type": "application/json"
        }
        res = requests.get(url, params=params, timeout=10)
        if res.status_code != 200:
            return
        data = res.json()
        count = 0
        for job in data.get("results", []):
            source_id = generate_source_id(job.get("title",""), "adzuna")
            if already_exists(mongo, source_id, "opportunities"):
                continue
            opp = {
                "role": job.get("title", ""),
                "company": job.get("company", {}).get("display_name", "Unknown"),
                "category": "job",
                "description": job.get("description", "")[:500],
                "apply_link": job.get("redirect_url", ""),
                "location": job.get("location", {}).get("display_name", "India"),
                "eligibility": "Open to All",
                "tags": ["job", "fresher", "hiring"],
                "deadline": str(
                    (datetime.utcnow() + timedelta(days=15)).date()
                ),
                "source": "adzuna",
                "source_id": source_id,
                "is_auto_collected": True,
                "is_hidden": False,
                "status": "pending",
                "created_by": None,
                "created_at": datetime.utcnow(),
                "image_url": "",
                "total_reactions": 0
            }
            mongo.db.opportunities.insert_one(opp)
            count += 1
        print(f"[AutoCollector] Adzuna: +{count} jobs")
    except Exception as e:
        print(f"[AutoCollector] Adzuna error: {e}")

def collect_from_remotive(mongo):
    """Fetch remote jobs from Remotive API"""
    try:
        url = "https://remotive.com/api/remote-jobs?limit=15"
        res = requests.get(url, timeout=10)
        if res.status_code != 200:
            return
        data = res.json()
        count = 0
        for job in data.get("jobs", []):
            source_id = generate_source_id(job.get("title", ""), "remotive")
            if already_exists(mongo, source_id, "opportunities"):
                continue
            
            desc_html = job.get("description", "")
            desc_text = BeautifulSoup(desc_html, "html.parser").get_text()[:500] if desc_html else ""
            
            opp = {
                "role": job.get("title", ""),
                "company": job.get("company_name", "Unknown"),
                "category": "job",
                "description": desc_text,
                "apply_link": job.get("url", ""),
                "location": job.get("candidate_required_location", "Remote"),
                "eligibility": "Open to All",
                "tags": ["remote", "job", job.get("category", "").lower()],
                "deadline": str((datetime.utcnow() + timedelta(days=20)).date()),
                "source": "remotive",
                "source_id": source_id,
                "is_auto_collected": True,
                "is_hidden": False,
                "status": "pending",
                "created_by": None,
                "created_at": datetime.utcnow(),
                "image_url": job.get("company_logo", ""),
                "total_reactions": 0
            }
            mongo.db.opportunities.insert_one(opp)
            count += 1
        print(f"[AutoCollector] Remotive: +{count} jobs")
    except Exception as e:
        print(f"[AutoCollector] Remotive error: {e}")

def collect_from_jobicy(mongo):
    """Fetch remote jobs from Jobicy API"""
    try:
        url = "https://jobicy.com/api/v2/remote-jobs"
        res = requests.get(url, timeout=10)
        if res.status_code != 200:
            return
        data = res.json()
        count = 0
        for job in data.get("jobs", [])[:15]:
            source_id = generate_source_id(job.get("jobTitle", ""), "jobicy")
            if already_exists(mongo, source_id, "opportunities"):
                continue
                
            desc_html = job.get("jobDescription", "")
            desc_text = BeautifulSoup(desc_html, "html.parser").get_text()[:500] if desc_html else ""
            
            job_type_raw = job.get("jobType", "full-time")
            if isinstance(job_type_raw, list):
                job_type = job_type_raw[0] if job_type_raw else "full-time"
            else:
                job_type = job_type_raw or "full-time"
            job_type = str(job_type).lower()
            
            opp = {
                "role": job.get("jobTitle", ""),
                "company": job.get("companyName", "Unknown"),
                "category": "job",
                "description": desc_text,
                "apply_link": job.get("url", ""),
                "location": job.get("jobGeo", "Remote"),
                "eligibility": "Open to All",
                "tags": ["remote", "job", job_type],
                "deadline": str((datetime.utcnow() + timedelta(days=20)).date()),
                "source": "jobicy",
                "source_id": source_id,
                "is_auto_collected": True,
                "is_hidden": False,
                "status": "pending",
                "created_by": None,
                "created_at": datetime.utcnow(),
                "image_url": job.get("companyLogo", ""),
                "total_reactions": 0
            }
            mongo.db.opportunities.insert_one(opp)
            count += 1
        print(f"[AutoCollector] Jobicy: +{count} jobs")
    except Exception as e:
        print(f"[AutoCollector] Jobicy error: {e}")

def collect_from_themuse(mongo):
    """Fetch jobs from The Muse API"""
    try:
        url = "https://www.themuse.com/api/public/jobs?page=1"
        res = requests.get(url, timeout=10)
        if res.status_code != 200:
            return
        data = res.json()
        count = 0
        for job in data.get("results", [])[:15]:
            source_id = generate_source_id(job.get("name", ""), "themuse")
            if already_exists(mongo, source_id, "opportunities"):
                continue
                
            desc_html = job.get("contents", "")
            desc_text = BeautifulSoup(desc_html, "html.parser").get_text()[:500] if desc_html else ""
            
            locations = job.get("locations", [])
            location_str = locations[0].get("name") if locations else "Flexible"
            
            opp = {
                "role": job.get("name", ""),
                "company": job.get("company", {}).get("name", "Unknown"),
                "category": "job",
                "description": desc_text,
                "apply_link": job.get("refs", {}).get("landing_page", ""),
                "location": location_str,
                "eligibility": "Open to All",
                "tags": ["job", "culture"],
                "deadline": str((datetime.utcnow() + timedelta(days=20)).date()),
                "source": "themuse",
                "source_id": source_id,
                "is_auto_collected": True,
                "is_hidden": False,
                "status": "pending",
                "created_by": None,
                "created_at": datetime.utcnow(),
                "image_url": "",
                "total_reactions": 0
            }
            mongo.db.opportunities.insert_one(opp)
            count += 1
        print(f"[AutoCollector] The Muse: +{count} jobs")
    except Exception as e:
        print(f"[AutoCollector] The Muse error: {e}")

# ══════════════════════════════════════════════
# EVENTS COLLECTORS

# ══════════════════════════════════════════════

def collect_hackathons_from_devpost(mongo):
    """Scrape hackathons from Devpost"""
    try:
        url = "https://devpost.com/hackathons?status[]=open"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        cards = soup.select(".hackathon-tile")[:10]
        count = 0
        for card in cards:
            title = card.select_one("h3")
            if not title:
                continue
            title_text = title.get_text(strip=True)
            source_id = generate_source_id(title_text, "devpost")
            if already_exists(mongo, source_id, "events"):
                continue
            link_tag = card.select_one("a")
            link = "https://devpost.com" + link_tag["href"] if link_tag else ""
            img_tag = card.select_one("img")
            img = img_tag.get("src", "") if img_tag else ""
            prize_tag = card.select_one(".prize-amount")
            prize = prize_tag.get_text(strip=True) if prize_tag else ""
            event = {
                "title": title_text,
                "college_name": "Devpost",
                "category": "hackathon",
                "description": f"Online hackathon on Devpost. {prize}",
                "date": str(
                    (datetime.utcnow() + timedelta(days=14)).date()
                ),
                "registration_link": link,
                "image_url": img,
                "tags": ["hackathon", "tech", "online", "coding"],
                "source": "devpost",
                "source_id": source_id,
                "is_auto_collected": True,
                "is_hidden": False,
                "status": "approved",
                "created_by": None,
                "created_at": datetime.utcnow(),
                "total_reactions": 0
            }
            mongo.db.events.insert_one(event)
            count += 1
        print(f"[AutoCollector] Devpost: +{count} hackathons")
    except Exception as e:
        print(f"[AutoCollector] Devpost error: {e}")

def collect_tech_events_from_rss(mongo):
    """Collect tech events from multiple RSS feeds"""
    feeds = [
        ("https://dev.to/feed", "dev.to", "workshop"),
        ("https://techcrunch.com/feed/", "techcrunch", "technical"),
        ("https://www.geeksforgeeks.org/feed/", "geeksforgeeks", "workshop"),
    ]
    for feed_url, source, category in feeds:
        try:
            feed = feedparser.parse(feed_url)
            count = 0
            for entry in feed.entries[:5]:
                title = entry.get("title", "")
                if not any(kw in title.lower() for kw in [
                    "event", "hackathon", "workshop", "conference",
                    "webinar", "contest", "challenge", "bootcamp"
                ]):
                    continue
                source_id = generate_source_id(title, source)
                if already_exists(mongo, source_id, "events"):
                    continue
                event = {
                    "title": title,
                    "college_name": source.title(),
                    "category": category,
                    "description": BeautifulSoup(
                        entry.get("summary", ""), "html.parser"
                    ).get_text()[:400],
                    "date": str(
                        (datetime.utcnow() + timedelta(days=7)).date()
                    ),
                    "registration_link": entry.get("link", ""),
                    "image_url": "",
                    "tags": [category, "tech", "student"],
                    "source": source,
                    "source_id": source_id,
                    "is_auto_collected": True,
                    "is_hidden": False,
                    "status": "active",
                    "created_by": None,
                    "created_at": datetime.utcnow(),
                    "total_reactions": 0
                }
                mongo.db.events.insert_one(event)
                count += 1
            print(f"[AutoCollector] {source}: +{count} events")
        except Exception as e:
            print(f"[AutoCollector] {source} error: {e}")

def collect_from_mlh(mongo):
    """Scrape hackathons from MLH (Major League Hacking)"""
    try:
        url = "https://mlh.io/seasons/2025/events"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        cards = soup.select(".event-wrapper")[:10]
        count = 0
        for card in cards:
            title_tag = card.select_one("h3.event-name")
            if not title_tag:
                continue
            title_text = title_tag.get_text(strip=True)
            source_id = generate_source_id(title_text, "mlh")
            
            if already_exists(mongo, source_id, "events"):
                continue
                
            link_tag = card.select_one("a.event-link")
            link = link_tag["href"] if link_tag else ""
            
            date_tag = card.select_one("p.event-date")
            date_str = date_tag.get_text(strip=True) if date_tag else ""
            
            img_tag = card.select_one("div.event-logo img")
            img = img_tag.get("src", "") if img_tag else ""
            
            event = {
                "title": title_text,
                "college_name": "MLH",
                "category": "hackathon",
                "description": f"MLH Hackathon: {date_str}. Register now!",
                "date": str((datetime.utcnow() + timedelta(days=30)).date()),
                "registration_link": link,
                "image_url": img,
                "tags": ["hackathon", "mlh", "tech", "coding"],
                "source": "mlh",
                "source_id": source_id,
                "is_auto_collected": True,
                "is_hidden": False,
                "status": "pending",
                "created_by": None,
                "created_at": datetime.utcnow(),
                "total_reactions": 0
            }
            mongo.db.events.insert_one(event)
            count += 1
        print(f"[AutoCollector] MLH: +{count} hackathons")
    except Exception as e:
        print(f"[AutoCollector] MLH error: {e}")

def collect_from_eventbrite(mongo, api_key):
    """Fetch events from Eventbrite API"""
    if not api_key:
        return
    try:
        url = "https://www.eventbriteapi.com/v3/events/search/"
        headers = {
            "Authorization": f"Bearer {api_key}"
        }
        params = {
            "q": "tech hackathon workshop",
            "sort_by": "date"
        }
        res = requests.get(url, headers=headers, params=params, timeout=10)
        if res.status_code != 200:
            return
        data = res.json()
        count = 0
        for ev in data.get("events", [])[:10]:
            source_id = generate_source_id(ev.get("name", {}).get("text", ""), "eventbrite")
            if already_exists(mongo, source_id, "events"):
                continue
                
            desc_text = ev.get("description", {}).get("text", "")[:500]
            start_date = ev.get("start", {}).get("local", "")[:10]
            if not start_date:
                start_date = str((datetime.utcnow() + timedelta(days=14)).date())
                
            event = {
                "title": ev.get("name", {}).get("text", ""),
                "college_name": "Eventbrite",
                "category": "workshop",
                "description": desc_text,
                "date": start_date,
                "registration_link": ev.get("url", ""),
                "image_url": ev.get("logo", {}).get("url", "") if ev.get("logo") else "",
                "tags": ["eventbrite", "tech", "event"],
                "source": "eventbrite",
                "source_id": source_id,
                "is_auto_collected": True,
                "is_hidden": False,
                "status": "pending",
                "created_by": None,
                "created_at": datetime.utcnow(),
                "total_reactions": 0
            }
            mongo.db.events.insert_one(event)
            count += 1
        print(f"[AutoCollector] Eventbrite: +{count} events")
    except Exception as e:
        print(f"[AutoCollector] Eventbrite error: {e}")

# ══════════════════════════════════════════════
# MAIN COLLECTOR — runs all collectors
# ══════════════════════════════════════════════

def run_all_collectors(mongo, config=None):
    print(f"\n[AutoCollector] Starting collection at {datetime.utcnow()}")
    config = config or {}
    
    # Opportunities
    collect_from_internshala(mongo)
    collect_from_unstop(mongo)
    collect_from_remotive(mongo)
    collect_from_jobicy(mongo)
    collect_from_themuse(mongo)
    
    # Events
    collect_hackathons_from_devpost(mongo)
    collect_tech_events_from_rss(mongo)
    collect_from_mlh(mongo)
    
    # Only run Adzuna if API keys configured
    if config.get("ADZUNA_APP_ID") and config.get("ADZUNA_APP_KEY"):
        collect_from_adzuna(
            mongo,
            config["ADZUNA_APP_ID"],
            config["ADZUNA_APP_KEY"]
        )
        
    # Only run Eventbrite if API key configured
    if config.get("EVENTBRITE_API_KEY"):
        collect_from_eventbrite(
            mongo,
            config["EVENTBRITE_API_KEY"]
        )
    
    print(f"[AutoCollector] Collection complete at {datetime.utcnow()}\n")

# ── Start the scheduler ──
def start_scheduler(mongo, config=None):
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=lambda: run_all_collectors(mongo, config),
        trigger="interval",
        hours=6,
        id="auto_collector",
        replace_existing=True
    )
    scheduler.start()
    print("[AutoCollector] Scheduler started — runs every 6 hours")
    # Run once immediately on startup
    run_all_collectors(mongo, config)
    return scheduler
