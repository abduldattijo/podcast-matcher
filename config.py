import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    # Basic Flask configuration
    SECRET_KEY = os.getenv('SECRET_KEY', 'your-secret-key-here')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
    ALLOWED_EXTENSIONS = {'txt', 'docx', 'html', 'csv'}

    # Database configuration
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_KEY')

    # OpenAI configuration
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

    # Processing configurations
    CHUNK_SIZE = 10  # Number of podcasts to process at once
    MAX_DESCRIPTION_LENGTH = 5000  # Maximum length for descriptions
    RSS_FETCH_TIMEOUT = 30  # Seconds to wait for RSS feed
    RSS_MAX_RETRIES = 3  # Number of times to retry fetching RSS feed
    
    # Memory monitoring
    MEMORY_ALERT_THRESHOLD = 500  # MB

    # Request timeouts
    REQUEST_TIMEOUT = 300  # 5 minutes

    # Episode processing
    MAX_EPISODES = 5  # Maximum number of episodes to process per podcast

    # Scoring weights
    SCORE_WEIGHTS = {
        'relevance': 0.35,
        'audience': 0.25,
        'guest_fit': 0.20,
        'recency': 0.10,
        'host_interest': 0.10
    }

    @staticmethod
    def init_app(app):
        """Initialize application with this configuration"""
        # Create upload folder if it doesn't exist
        os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
        
        # Create logs folder if it doesn't exist
        os.makedirs('logs', exist_ok=True)

        # Validate required environment variables
        required_vars = ['SUPABASE_URL', 'SUPABASE_KEY', 'OPENAI_API_KEY']
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

class DevelopmentConfig(Config):
    DEBUG = True
    TESTING = False

class TestingConfig(Config):
    DEBUG = False
    TESTING = True
    # Use smaller chunk sizes for testing
    CHUNK_SIZE = 5

class ProductionConfig(Config):
    DEBUG = False
    TESTING = False
    # Use larger chunk sizes for production
    CHUNK_SIZE = 20

# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}