from flask import Flask, render_template
from flask_migrate import Migrate
import os
import logging
import openai
from dotenv import load_dotenv
from routes import init_routes
from database import supabase

# Set up logging
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Set OpenAI API key from environment variable
openai.api_key = os.getenv("OPENAI_API_KEY")

# Create Flask app
app = Flask(__name__)

# Basic configuration
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.getenv('SECRET_KEY', 'your_secret_key')

# Configure upload folder for files
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Basic test route
@app.route('/test')
def test():
    return "Application is running!"

# Initialize routes from routes.py
app = init_routes(app)

# Verify Supabase connection
try:
    response = supabase.table('clients').select("*").limit(1).execute()
    logger.info("Successfully connected to Supabase")
except Exception as e:
    logger.error(f"Error connecting to Supabase: {str(e)}")

# Get port from environment variable for Render deployment
port = int(os.environ.get('PORT', 10000))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=port, debug=False)