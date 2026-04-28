from app import create_app, mongo

app = create_app()
with app.app_context():
    # Find all opportunities that were auto_collected and have the wrong keys
    opps = mongo.db.opportunities.find({"is_auto_collected": True, "title": {"$exists": True}})
    count = 0
    
    for opp in opps:
        updates = {}
        # Move title -> role
        if "title" in opp:
            updates["role"] = opp.pop("title")
        # Move company_name -> company
        if "company_name" in opp:
            updates["company"] = opp.pop("company_name")
        # Move opportunity_type -> category
        if "opportunity_type" in opp:
            updates["category"] = opp.pop("opportunity_type")
        # Move application_url -> apply_link
        if "application_url" in opp:
            updates["apply_link"] = opp.pop("application_url")
            
        # Ensure eligibility exists
        if "eligibility" not in opp:
            updates["eligibility"] = "Open to All"
            
        if updates:
            mongo.db.opportunities.update_one(
                {"_id": opp["_id"]},
                {
                    "$set": updates,
                    "$unset": {
                        "title": "",
                        "company_name": "",
                        "opportunity_type": "",
                        "application_url": ""
                    }
                }
            )
            count += 1
            
    print(f"Fixed schema for {count} auto-collected opportunities.")
