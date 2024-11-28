from flask import Flask, render_template
import os
import logging
import openai
from dotenv import load_dotenv
from routes import init_routes
from database import supabase
from flask_cors import CORS
from datetime import datetime
from flask import request, jsonify
import multiprocessing
import psutil
import gc

# Ensure logs directory exists
os.makedirs('logs', exist_ok=True)

# Set up logging configuration
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

def check_memory_usage():
    """Check current memory usage"""
    try:
        process = psutil.Process(os.getpid())
        memory_info = process.memory_info()
        memory_percent = process.memory_percent()
        
        return {
            "memory_used_mb": memory_info.rss / 1024 / 1024,
            "memory_percent": memory_percent
        }
    except Exception as e:
        logger.error(f"Error checking memory usage: {str(e)}")
        return None

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
            SECRET_KEY=os.getenv('SECRET_KEY', 'your-secret-key-here'),
            MAX_CONTENT_LENGTH=16 * 1024 * 1024,  # 16MB max file size
            UPLOAD_FOLDER=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads'),
            ALLOWED_EXTENSIONS={'txt', 'docx', 'html', 'csv'}
        )

        # Ensure upload folder exists
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

        # Set OpenAI API key
        openai.api_key = os.getenv("OPENAI_API_KEY")
        if not openai.api_key:
            logger.error("OpenAI API key not found in environment variables")
            raise ValueError("OpenAI API key not configured")

        # Configure basic health check endpoint that doesn't block
        @app.route('/health')
        def health_check():
            """Quick health check that doesn't depend on database connection"""
            try:
                memory_info = check_memory_usage()
                return jsonify({
                    "status": "healthy",
                    "timestamp": datetime.now().isoformat(),
                    "memory": memory_info
                })
            except Exception as e:
                logger.error(f"Health check failed: {str(e)}")
                return jsonify({
                    "status": "unhealthy",
                    "error": str(e),
                    "timestamp": datetime.now().isoformat()
                }), 500

        # Configure deep health check endpoint
        @app.route('/health/deep')
        def deep_health_check():
            """Deeper health check that verifies all connections"""
            try:
                # Test database connection
                supabase.table('clients').select("*").limit(1).execute()
                
                # Check memory usage
                memory_info = check_memory_usage()
                
                # Check OpenAI API key
                api_configured = bool(openai.api_key)
                
                # Check upload directory
                upload_dir_exists = os.path.exists(app.config['UPLOAD_FOLDER'])
                upload_dir_writable = os.access(app.config['UPLOAD_FOLDER'], os.W_OK)
                
                return jsonify({
                    "status": "healthy",
                    "timestamp": datetime.now().isoformat(),
                    "database_connected": True,
                    "api_configured": api_configured,
                    "upload_directory": {
                        "exists": upload_dir_exists,
                        "writable": upload_dir_writable,
                        "path": app.config['UPLOAD_FOLDER']
                    },
                    "memory": memory_info,
                    "process_id": os.getpid(),
                    "worker_type": "gthread",
                    "workers": multiprocessing.cpu_count() * 2 + 1
                })
            except Exception as e:
                logger.error(f"Deep health check failed: {str(e)}")
                return jsonify({
                    "status": "unhealthy",
                    "error": str(e),
                    "timestamp": datetime.now().isoformat()
                }), 500

        # Error handlers
        @app.errorhandler(404)
        def not_found_error(error):
            logger.error(f"404 error: {str(error)}")
            return render_template('error.html', error="404 - Page Not Found"), 404

        @app.errorhandler(500)
        def internal_error(error):
            logger.error(f"500 error: {str(error)}")
            return render_template('error.html', error="500 - Internal Server Error"), 500

        @app.errorhandler(413)
        def request_entity_too_large(error):
            logger.error(f"413 error: {str(error)}")
            return render_template('error.html', error="413 - File too large"), 413

        # Before request handler
        @app.before_request
        def before_request():
            """Log incoming requests and check memory"""
            logger.info(f"Incoming request: {request.method} {request.path}")
            memory_info = check_memory_usage()
            if memory_info and memory_info["memory_percent"] > 90:
                logger.warning(f"High memory usage detected: {memory_info['memory_percent']}%")
                gc.collect()

        # After request handler
        @app.after_request
        def after_request(response):
            """Configure response headers and log response status"""
            # Ensure proper headers are set
            response.headers.add('Cache-Control', 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0')
            
            # Log response status
            logger.info(f"Response status: {response.status}")
            
            return response

        logger.info("Application initialized successfully")
        return app

    except Exception as e:
        logger.error(f"Error creating Flask app: {str(e)}")
        raise

def setup_database(app):
    """
    Verify database connection and setup.
    
    Args:
        app (Flask): Flask application instance
    """
    try:
        # Verify Supabase connection
        response = supabase.table('clients').select("*").limit(1).execute()
        logger.info("Successfully connected to Supabase")
        
        # Add database connection to app context
        app.config['supabase'] = supabase
        
    except Exception as e:
        logger.error(f"Error connecting to Supabase: {str(e)}")
        raise

def setup_routes(app):
    """
    Initialize routes and error handlers.
    
    Args:
        app (Flask): Flask application instance
    """
    try:
        # Initialize routes
        app = init_routes(app)
    except Exception as e:
        logger.error(f"Error setting up routes: {str(e)}")
        raise

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

# Gunicorn configuration
workers = multiprocessing.cpu_count() * 2 + 1  # Number of worker processes
threads = 4  # Number of threads per worker
worker_class = 'gthread'  # Use threads
timeout = 300  # 5 minutes timeout
keepalive = 65  # Keepalive timeout
worker_connections = 1000  # Maximum number of simultaneous connections
max_requests = 1000  # Restart workers after this many requests
max_requests_jitter = 50  # Add randomness to max_requests

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
        
        # Setup routes
        setup_routes(app)
        
        # Create error handlers
        create_error_handlers(app)
        
        logger.info("Application initialized successfully")
        return app

    except Exception as e:
        logger.error(f"Error initializing application: {str(e)}")
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
        port = int(os.environ.get('PORT', 8080))
        
        # Run the application
        app.run(
            host='0.0.0.0',
            port=port,
            debug=os.getenv('FLASK_ENV') == 'development'
        )
    except Exception as e:
        logger.critical(f"Application failed to start: {str(e)}")
        raise