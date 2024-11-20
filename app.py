from flask import Flask
from flask_migrate import Migrate
from sqlalchemy_utils import database_exists, create_database
import os
import logging
import openai
from models import db
from routes import init_routes
from dotenv import load_dotenv

load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set your OpenAI API key
os.environ["OPENAI_API_KEY"] = "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"

def create_app():
    app = Flask(__name__)

    # Database configuration
    #render production database
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'postgresql://podcast_db_n1bc_user:sKSceAGVCbVYN4QH4rWIi6CxdEqMFnUC@dpg-csuvrkd6l47c7383de6g-a/podcast_db_n1bc')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
     
    #railway production database
    #DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:axrjuGyXsVBvXDSxkKZVtpqAseqwPcTE@junction.proxy.rlwy.net:44492/railway")
    #app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
     #local database
    #DATABASE_URI = 'postgresql+psycopg2://postgres:podcast@localhost/podcast_db'
    #app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URI
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False   
    app.secret_key = 'your_secret_key'  

    # Configure upload folder  
    #app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
    #os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Check if database exists, if not create it
    if not database_exists(DATABASE_URI):
        create_database(DATABASE_URI)
        logger.info("Database created.")
    else:
        logger.info("Database already exists.")

    # Initialize extensions
    db.init_app(app)
    migrate = Migrate(app, db)

    # Create tables
    with app.app_context():
        db.create_all()
        logger.info("Tables created.")

    # Initialize routes
    init_routes(app)

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)    