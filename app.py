from flask import Flask, render_template, request
import os
import logging
import openai
from dotenv import load_dotenv
from routes import init_routes
from database import supabase
from flask_cors import CORS
from datetime import datetime
import sys
from werkzeug.middleware.proxy_fix import ProxyFix

# Set up logging configuration
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

# Load environment variables
load_dotenv()

def create_app():
    """Create and configure the Flask application."""
    try:
        app = Flask(__name__)
        
        # Enable CORS
        CORS(app)

        # Fix for proxy headers
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

        # Basic configuration
        app.config.update(
            SECRET_KEY=os.getenv('SECRET_KEY', os.urandom(24).hex()),
            MAX_CONTENT_LENGTH=32 * 1024 * 1024,  # 32MB max file size
            UPLOAD_FOLDER=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads'),
            ALLOWED_EXTENSIONS={'txt', 'docx', 'html', 'csv'},
            PERMANENT_SESSION_LIFETIME=1800,  # 30 minutes
            SESSION_COOKIE_SECURE=True,
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE='Lax'
        )

        # Gunicorn configuration for production
        if 'gunicorn' in sys.modules:
            logger.info("Configuring Gunicorn settings")
            app.config.update(
                GUNICORN_TIMEOUT=600,  # 10 minutes
                GUNICORN_WORKERS=2,  # Reduce number of workers
                GUNICORN_WORKER_CLASS='sync',
                GUNICORN_MAX_REQUESTS=100,  # Lower to prevent memory buildup
                GUNICORN_MAX_REQUESTS_JITTER=50,
                GUNICORN_WORKER_CONNECTIONS=1000,
                GUNICORN_KEEPALIVE=5,
                GUNICORN_PRELOAD_APP=True
            )

        # Ensure upload folder exists
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

        # Set OpenAI API key with error handling
        openai.api_key = os.getenv("OPENAI_API_KEY")
        if not openai.api_key:
            logger.error("OpenAI API key not found in environment variables")
            raise ValueError("OpenAI API key not configured")

        # Initialize database connection
        setup_database(app)
        
        # Setup routes and error handlers
        setup_routes(app)
        
        # Setup middleware
        setup_middleware(app)
        
        # Create error handlers
        create_error_handlers(app)
        
        # Add health check route
        setup_health_check(app)

        logger.info("Application initialized successfully")
        return app

    except Exception as e:
        logger.critical(f"Error creating Flask app: {str(e)}")
        raise

def setup_database(app):
    """Verify database connection and setup."""
    try:
        # Test database connection with timeout
        response = supabase.table('clients').select("*").limit(1).execute()
        logger.info("Successfully connected to Supabase")
        app.config['supabase'] = supabase
    except Exception as e:
        logger.critical(f"Error connecting to Supabase: {str(e)}")
        raise

def setup_routes(app):
    """Initialize routes and add error handlers."""
    try:
        app = init_routes(app)
        
        @app.errorhandler(404)
        def not_found_error(error):
            logger.warning(f"404 error: {request.url}")
            return render_template('error.html', error="404 - Page Not Found"), 404

        @app.errorhandler(500)
        def internal_error(error):
            logger.error(f"500 error: {str(error)}")
            return render_template('error.html', error="500 - Internal Server Error"), 500

        @app.errorhandler(413)
        def request_entity_too_large(error):
            logger.warning("413 error: File too large")
            return render_template('error.html', error="413 - File too large"), 413

    except Exception as e:
        logger.critical(f"Error setting up routes: {str(e)}")
        raise

def setup_middleware(app):
    """Configure middleware and request handlers."""
    @app.before_request
    def before_request():
        logger.info(f"Incoming request: {request.method} {request.path}")

    @app.after_request
    def after_request(response):
        response.headers.update({
            'Cache-Control': 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0',
            'Pragma': 'no-cache',
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'SAMEORIGIN',
            'X-XSS-Protection': '1; mode=block',
            'Strict-Transport-Security': 'max-age=31536000; includeSubDomains'
        })
        logger.info(f"Response status: {response.status}")
        return response

def create_error_handlers(app):
    """Create custom error handlers."""
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

def setup_health_check(app):
    """Configure health check endpoint."""
    @app.route('/health')
    def health_check():
        try:
            supabase.table('clients').select("*").limit(1).execute()
            upload_dir = app.config['UPLOAD_FOLDER']
            
            if not os.path.exists(upload_dir):
                os.makedirs(upload_dir)
            
            if not openai.api_key:
                raise ValueError("OpenAI API key not configured")
            
            return {
                "status": "healthy",
                "timestamp": datetime.now().isoformat(),
                "supabase_connected": True,
                "openai_configured": True,
                "upload_dir_accessible": True,
                "environment": os.getenv('FLASK_ENV', 'production'),
                "worker_pid": os.getpid()
            }
        except Exception as e:
            logger.error(f"Health check failed: {str(e)}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }, 500

# Create the application instance
try:
    app = create_app()
except Exception as e:
    logger.critical(f"Failed to initialize application: {str(e)}")
    raise

if __name__ == '__main__':
    try:
        port = int(os.environ.get('PORT', 10000))
        
        server_settings = {
            'host': '0.0.0.0',
            'port': port,
            'debug': os.getenv('FLASK_ENV') == 'development',
            'threaded': True,
            'use_reloader': os.getenv('FLASK_ENV') == 'development',
            'ssl_context': None  # Configure SSL in production
        }
        
        app.run(**server_settings)
    except Exception as e:
        logger.critical(f"Application failed to start: {str(e)}")
        raise