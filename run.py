from dotenv import load_dotenv
load_dotenv()

from app import create_app
import os

app = create_app()

if __name__ == '__main__':
    with app.app_context():
        # Bug 5 Guard: Prevent double startup in debug mode
        if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
            from app.services.auto_collector import start_scheduler
            from app import mongo
            start_scheduler(mongo, {
                "ADZUNA_APP_ID": os.getenv("ADZUNA_APP_ID", ""),
                "ADZUNA_APP_KEY": os.getenv("ADZUNA_APP_KEY", "")
            })
    app.run(debug=True, port=5000, use_reloader=True)
