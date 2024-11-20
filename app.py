from flask import Flask
from flask_migrate import Migrate
import os
import logging
import openai
from dotenv import load_dotenv
from routes import init_routes
from database import supabase

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Set your OpenAI API key
os.environ["OPENAI_API_KEY"] = "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"


# Load environment variables
load_dotenv()

# Set your OpenAI API key
openai.api_key = os.getenv("OPENAI_API_KEY")




def create_app():
    app = Flask(__name__)

    # Basic configuration
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.secret_key = 'your_secret_key'

    # Configure upload folder
    app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    
    

    # Initialize routes
    init_routes(app)

    return app

# Verify Supabase connection
try:
    response = supabase.table('clients').select("*").limit(1).execute()
    logger.info("Successfully connected to Supabase")
except Exception as e:
    logger.error(f"Error connecting to Supabase: {str(e)}")

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)