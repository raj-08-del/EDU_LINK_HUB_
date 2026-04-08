from dotenv import load_dotenv
load_dotenv()

from app import create_app
import os

app = create_app()

if __name__ == '__main__':
    app.run(debug=True, port=5000, use_reloader=False)
