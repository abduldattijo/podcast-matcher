
import os
import logging
import openai
from dotenv import load_dotenv
from routes import init_routes
from database import supabase
from flask import Flask, render_template, session

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Set OpenAI API key from environment variable
openai.api_key = os.getenv("OPENAI_API_KEY")

# Create Flask app
app = Flask(__name__)

# In app.py

# Add these lines
@app.after_request
def after_request(response):
    session.pop('_flashes', None)
    return response

def store_in_session(key, value):
    if len(str(value)) > 3000:
        return False
    session[key] = value
    return True

# Rest of your app.py code...

# Basic configuration
app.secret_key = os.getenv('SECRET_KEY', 'your_secret_key')

# Configure upload folder for files
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize routes from routes.py
app = init_routes(app)

# Verify Supabase connection
try:
    response = supabase.table('clients').select("*").limit(1).execute()
    logger.info("Successfully connected to Supabase")
except Exception as e:
    logger.error(f"Error connecting to Supabase: {str(e)}")

# Health check route
@app.route('/health')
def health_check():
    return {
        "status": "healthy",
        "supabase_connected": True if response else False
    }

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)