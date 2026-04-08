import sys
import os

# Add relevant paths
sys.path.append(os.getcwd())

from app import create_app, mongo
from app.routes.leaderboard import backfill_all_user_points

app = create_app()
with app.app_context():
    print("--- Starting Manual Points Fix ---")
    backfill_all_user_points()
    print("--- Points Fix Complete ---")
