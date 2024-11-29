from flask import Flask, render_template, send_from_directory
import os
import logging
import openai
import psutil
import gc
from dotenv import load_dotenv
from routes import init_routes
from database import supabase
from flask_cors import CORS
from datetime import datetime
from flask import request
import torch

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

def log_memory_usage():
    """Log current memory usage."""
    process = psutil.Process()
    memory_mb = process.memory_info().rss / 1024 / 1024
    logger.info(f"Memory usage: {memory_mb:.2f} MB")

def cleanup_memory():
    """Perform memory cleanup operations."""
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    log_memory_usage()

def create_app():
    """
    Create and configure the Flask application.
    
    Returns:
        Flask: Configured Flask application
    """
    try:
        # Create Flask app with static file configuration
        app = Flask(__name__,
                   static_url_path='/static',
                   static_folder='static')
        
        # Enable CORS
        CORS(app)

        # Basic configuration with memory optimizations
        app.config.update(
            SECRET_KEY=os.getenv('SECRET_KEY', 'your_secret_key_here'),
            MAX_CONTENT_LENGTH=5 * 1024 * 1024,  # 5MB max file size
            UPLOAD_FOLDER=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads'),
            ALLOWED_EXTENSIONS={'txt', 'docx', 'html', 'csv'},
            UPLOAD_CHUNK_SIZE=1024 * 1024,  # 1MB chunks for file processing
            MAX_POOL_SIZE=5,  # Limit database connection pool
            BATCH_SIZE=50     # Batch size for database operations
        )

        # Ensure upload folder exists
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

        # Set OpenAI API key
        openai.api_key = os.getenv("OPENAI_API_KEY")
        if not openai.api_key:
            logger.error("OpenAI API key not found in environment variables")
            raise ValueError("OpenAI API key not configured")

        # Add static file handler
        @app.route('/static/<path:filename>')
        def serve_static(filename):
            return send_from_directory(app.static_folder, filename)

        # Log initial memory usage
        log_memory_usage()

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
        # Verify Supabase connection with timeout
        response = supabase.table('clients').select("*").limit(1).execute()
        logger.info("Successfully connected to Supabase")
        
        # Add database connection to app context
        app.config['supabase'] = supabase
        
        # Log memory usage after database setup
        log_memory_usage()
        
    except Exception as e:
        logger.error(f"Error connecting to Supabase: {str(e)}")
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
            cleanup_memory()
            return render_template('error.html', error="404 - Page Not Found"), 404

        @app.errorhandler(500)
        def internal_error(error):
            cleanup_memory()
            logger.error(f"Internal server error: {str(error)}")
            return render_template('error.html', error="500 - Internal Server Error"), 500

        @app.errorhandler(413)
        def request_entity_too_large(error):
            cleanup_memory()
            return render_template('error.html', error="413 - File too large"), 413

    except Exception as e:
        logger.error(f"Error setting up routes: {str(e)}")
        raise

def setup_middleware(app):
    """
    Configure middleware and before/after request handlers.
    
    Args:
        app (Flask): Flask application instance
    """
    @app.before_request
    def before_request():
        """Log incoming requests and memory usage."""
        logger.info(f"Incoming request: {request.method} {request.path}")
        log_memory_usage()

    @app.after_request
    def after_request(response):
        """Configure response headers and clean up memory."""
        # Ensure proper headers are set
        response.headers.add('Cache-Control', 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0')
        
        # Log response status and memory usage
        logger.info(f"Response status: {response.status}")
        cleanup_memory()
        
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
        cleanup_memory()
        logger.error(f"Unhandled exception: {str(e)}")
        return render_template('error.html', error="An unexpected error occurred"), 500

    @app.errorhandler(FileNotFoundError)
    def handle_file_not_found(e):
        """Handle file not found errors."""
        cleanup_memory()
        logger.error(f"File not found: {str(e)}")
        return render_template('error.html', error="The requested file was not found"), 404

    @app.errorhandler(PermissionError)
    def handle_permission_error(e):
        """Handle permission errors."""
        cleanup_memory()
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
            """Basic health check endpoint."""
            try:
                # Test database connection
                supabase.table('clients').select("*").limit(1).execute()
                
                return {
                    "status": "healthy",
                    "timestamp": datetime.now().isoformat(),
                    "supabase_connected": True,
                    "openai_configured": bool(openai.api_key),
                    "memory_usage_mb": psutil.Process().memory_info().rss / 1024 / 1024
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
        
        # Run the application
        app.run(
            host='0.0.0.0',
            port=port,
            debug=os.getenv('FLASK_ENV') == 'development'
        )
    except Exception as e:
        logger.critical(f"Application failed to start: {str(e)}")
        raise