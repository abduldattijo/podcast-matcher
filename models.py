from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Client(db.Model):
    __tablename__ = 'client'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)

class ClientData(db.Model):
    __tablename__ = 'client_data'
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    filename = db.Column(db.String(500), nullable=False)
    transcription = db.Column(db.Text, nullable=True)
    embedding = db.Column(db.ARRAY(db.Float), nullable=True)

    client = db.relationship('Client', backref=db.backref('files', lazy=True))

class Podcast(db.Model):
    __tablename__ = 'podcast'
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    search_term = db.Column(db.String(100), nullable=False)
    listennotes_url = db.Column(db.String(255), nullable=False)
    listen_score = db.Column(db.Integer, nullable=False)
    global_rank = db.Column(db.Float, nullable=False)
    rss_feed = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), nullable=True)
    filename = db.Column(db.String(500), nullable=True)
    last_updated = db.Column(db.String(20), nullable=True)
    title = db.Column(db.String(500), nullable=True)
    description = db.Column(db.Text, nullable=True)
    contact_name = db.Column(db.String(255), nullable=True)
    contact_email = db.Column(db.String(255), nullable=True)
    categories = db.Column(db.String(500), nullable=True)
    embedding = db.Column(db.ARRAY(db.Float), nullable=True)

    client = db.relationship('Client', backref=db.backref('podcasts', lazy=True))

class Episode(db.Model):
    __tablename__ = 'episode'
    id = db.Column(db.Integer, primary_key=True)
    podcast_id = db.Column(db.Integer, db.ForeignKey('podcast.id'), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    title = db.Column(db.String(500), nullable=False)
    date = db.Column(db.String(20), nullable=False)
    description = db.Column(db.Text, nullable=True)
    embedding = db.Column(db.ARRAY(db.Float), nullable=True)

    podcast = db.relationship('Podcast', backref=db.backref('episodes', lazy=True))
    client = db.relationship('Client', backref=db.backref('episodes', lazy=True))