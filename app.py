import os
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1" 
os.environ["OMP_NUM_THREADS"] = "1"

import resource
resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, -1))

from flask import Flask, render_template
import logging
import openai
from dotenv import load_dotenv
from routes import init_routes
from database import supabase
from flask_cors import CORS
from datetime import datetime
from flask import request, session

os.makedirs('logs', exist_ok=True)

logging.basicConfig(
   level=logging.INFO,
   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
   handlers=[
       logging.StreamHandler(),
       logging.FileHandler(f'logs/app_{datetime.now().strftime("%Y%m%d")}.log')
   ]
)
logger = logging.getLogger(__name__)

load_dotenv()

def create_app():
   try:
       app = Flask(__name__)
       
       CORS(app)

       app.config.update(
           SECRET_KEY=os.getenv('SECRET_KEY', 'your_secret_key_here'),
           MAX_CONTENT_LENGTH=16 * 1024 * 1024,
           UPLOAD_FOLDER=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads'),
           ALLOWED_EXTENSIONS={'txt', 'docx', 'html', 'csv'},
           SESSION_COOKIE_SAMESITE='Lax',
           SESSION_COOKIE_SECURE=True,
           PERMANENT_SESSION_LIFETIME=1800,
           SESSION_COOKIE_HTTPONLY=True
       )

       os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

       openai.api_key = os.getenv("OPENAI_API_KEY")
       if not openai.api_key:
           logger.error("OpenAI API key not found in environment variables")
           raise ValueError("OpenAI API key not configured")

       return app

   except Exception as e:
       logger.error(f"Error creating Flask app: {str(e)}")
       raise

def setup_database(app):
   try:
       response = supabase.table('clients').select("*").limit(1).execute()
       logger.info("Successfully connected to Supabase")
       app.config['supabase'] = supabase
       
   except Exception as e:
       logger.error(f"Error connecting to Supabase: {str(e)}")
       raise

def setup_routes(app):
   try:
       app = init_routes(app)
       
       @app.errorhandler(404)
       def not_found_error(error):
           return render_template('error.html', error="404 - Page Not Found"), 404

       @app.errorhandler(500)
       def internal_error(error):
           logger.error(f"Internal server error: {str(error)}")
           return render_template('error.html', error="500 - Internal Server Error"), 500

       @app.errorhandler(413)
       def request_entity_too_large(error):
           return render_template('error.html', error="413 - File too large"), 413

   except Exception as e:
       logger.error(f"Error setting up routes: {str(e)}")
       raise

def setup_middleware(app):
   @app.before_request
   def before_request():
       logger.info(f"Incoming request: {request.method} {request.path}")

   @app.after_request
   def after_request(response):
       response.headers.add('Cache-Control', 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0')
       logger.info(f"Response status: {response.status}")
       return response
       
   @app.after_request
   def clean_session(response):
       session.modified = True
       return response

def create_error_handlers(app):
   @app.errorhandler(Exception)
   def handle_exception(e):
       logger.error(f"Unhandled exception: {str(e)}")
       return render_template('error.html', error="An unexpected error occurred"), 500

   @app.errorhandler(FileNotFoundError)
   def handle_file_not_found(e):
       logger.error(f"File not found: {str(e)}")
       return render_template('error.html', error="The requested file was not found"), 404

   @app.errorhandler(PermissionError)
   def handle_permission_error(e):
       logger.error(f"Permission error: {str(e)}")
       return render_template('error.html', error="Permission denied"), 403

def init_app():
   try:
       app = create_app()
       setup_database(app)
       setup_routes(app)
       setup_middleware(app)
       create_error_handlers(app)
       
       @app.route('/health')
       def health_check():
           try:
               supabase.table('clients').select("*").limit(1).execute()
               
               return {
                   "status": "healthy",
                   "timestamp": datetime.now().isoformat(),
                   "supabase_connected": True,
                   "openai_configured": bool(openai.api_key)
               }
           except Exception as e:
               logger.error(f"Health check failed: {str(e)}")
               return {
                   "status": "unhealthy",
                   "error": str(e),
                   "timestamp": datetime.now().isoformat()
               }, 500

       logger.info("Application initialized successfully")
       return app

   except Exception as e:
       logger.error(f"Error initializing application: {str(e)}")
       raise

try:
   app = init_app()
except Exception as e:
   logger.critical(f"Failed to initialize application: {str(e)}")
   raise

if __name__ == '__main__':
   try:
       port = int(os.environ.get('PORT', 10000))
       app.run(
           host='0.0.0.0',
           port=port,
           debug=os.getenv('FLASK_ENV') == 'development'
       )
   except Exception as e:
       logger.critical(f"Application failed to start: {str(e)}")
       raise