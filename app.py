from flask import Flask, render_template
import os
import logging
import openai
from dotenv import load_dotenv
from routes import init_routes
from database import supabase
from flask_cors import CORS
from datetime import datetime
import sys
from flask import request

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
    """
    Create and configure the Flask application.
    
    Returns:
        Flask: Configured Flask application
    """
    try:
        # Create Flask app
        app = Flask(__name__)
        
        # Enable CORS
        CORS(app)

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

        # Ensure upload folder exists
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

        # Set OpenAI API key
        openai.api_key = os.getenv("OPENAI_API_KEY")
        if not openai.api_key:
            logger.error("OpenAI API key not found in environment variables")
            raise ValueError("OpenAI API key not configured")
            
        # Configure gunicorn settings if running with it
        if 'gunicorn' in sys.modules:
            logger.info("Configuring Gunicorn settings")
            # Increase timeouts and worker configurations
            app.config.update(
                GUNICORN_TIMEOUT=600,  # 10 minutes
                GUNICORN_WORKERS=2,
                GUNICORN_WORKER_CLASS='sync',
                GUNICORN_MAX_REQUESTS=100,
                GUNICORN_MAX_REQUESTS_JITTER=50,
                GUNICORN_KEEPALIVE=5,
                GUNICORN_WORKER_CONNECTIONS=1000
            )

        return app

    except Exception as e:
        logger.critical(f"Error creating Flask app: {str(e)}")
        raise

def setup_database(app):
    """
    Verify database connection and setup.
    
    Args:
        app (Flask): Flask application instance
    """
    try:
        # Verify Supabase connection with timeout
        response = supabase.table('clients').select("*").limit(1).execute()
        logger.info("Successfully connected to Supabase")
        
        # Add database connection to app context
        app.config['supabase'] = supabase
        
    except Exception as e:
        logger.critical(f"Error connecting to Supabase: {str(e)}")
        raise

def setup_routes(app):
    """
    Initialize routes and add error handlers.
    
    Args:
        app (Flask): Flask application instance
    """
    try:
        # Initialize routes from routes.py
        app = init_routes(app)
        
        # Add error handlers
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
            logger.warning(f"413 error: File too large")
            return render_template('error.html', error="413 - File too large"), 413

    except Exception as e:
        logger.critical(f"Error setting up routes: {str(e)}")
        raise

def setup_middleware(app):
    """
    Configure middleware and before/after request handlers.
    
    Args:
        app (Flask): Flask application instance
    """
    @app.before_request
    def before_request():
        """Log incoming requests."""
        logger.info(f"Incoming request: {request.method} {request.path}")

    @app.after_request
    def after_request(response):
        """Configure response headers and log response status."""
        # Security headers
        response.headers.update({
            'Cache-Control': 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0',
            'Pragma': 'no-cache',
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'SAMEORIGIN',
            'X-XSS-Protection': '1; mode=block'
        })
        
        # Log response status
        logger.info(f"Response status: {response.status}")
        
        return response

def create_error_handlers(app):
    """
    Create custom error handlers for the application.
    
    Args:
        app (Flask): Flask application instance
    """
    @app.errorhandler(Exception)
    def handle_exception(e):
        """Handle all unhandled exceptions."""
        logger.error(f"Unhandled exception: {str(e)}")
        return render_template('error.html', error="An unexpected error occurred"), 500

    @app.errorhandler(FileNotFoundError)
    def handle_file_not_found(e):
        """Handle file not found errors."""
        logger.error(f"File not found: {str(e)}")
        return render_template('error.html', error="The requested file was not found"), 404

    @app.errorhandler(PermissionError)
    def handle_permission_error(e):
        """Handle permission errors."""
        logger.error(f"Permission error: {str(e)}")
        return render_template('error.html', error="Permission denied"), 403

def init_app():
    """
    Initialize and configure the complete Flask application.
    
    Returns:
        Flask: Fully configured Flask application
    """
    try:
        # Create the Flask app
        app = create_app()
        
        # Setup database connection
        setup_database(app)
        
        # Setup routes and error handlers
        setup_routes(app)
        
        # Setup middleware
        setup_middleware(app)
        
        # Create error handlers
        create_error_handlers(app)
        
        # Add health check route
        @app.route('/health')
        def health_check():
            """Basic health check endpoint with enhanced checks."""
            try:
                # Test database connection
                supabase.table('clients').select("*").limit(1).execute()
                
                # Check upload directory
                upload_dir = app.config['UPLOAD_FOLDER']
                if not os.path.exists(upload_dir):
                    os.makedirs(upload_dir)
                
                # Verify OpenAI API key
                if not openai.api_key:
                    raise ValueError("OpenAI API key not configured")
                
                return {
                    "status": "healthy",
                    "timestamp": datetime.now().isoformat(),
                    "supabase_connected": True,
                    "openai_configured": True,
                    "upload_dir_accessible": True,
                    "environment": os.getenv('FLASK_ENV', 'production')
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
        logger.critical(f"Error initializing application: {str(e)}")
        raise

# Create the application instance
try:
    app = init_app()
except Exception as e:
    logger.critical(f"Failed to initialize application: {str(e)}")
    raise

if __name__ == '__main__':
    try:
        # Get port from environment variable or use default
        port = int(os.environ.get('PORT', 10000))
        
        # Configure server settings
        server_settings = {
            'host': '0.0.0.0',
            'port': port,
            'debug': os.getenv('FLASK_ENV') == 'development',
            'threaded': True,
            'use_reloader': os.getenv('FLASK_ENV') == 'development',
            'ssl_context': None  # Configure SSL in production
        }
        
        # Run the application
        app.run(**server_settings)
    except Exception as e:
        logger.critical(f"Application failed to start: {str(e)}")
        raise