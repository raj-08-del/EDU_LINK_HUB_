from app import create_app, mongo

app = create_app()
with app.app_context():
    result = mongo.db.opportunities.update_many(
        {'is_auto_collected': True, 'status': 'approved'},
        {'$set': {'status': 'pending'}}
    )
    print(f"Updated {result.modified_count} opportunities to 'pending' state.")
