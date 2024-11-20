from flask import render_template, request, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename
import os
import csv
from io import StringIO
from docx import Document
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import logging
from models import db, Client, ClientData, Podcast, Episode
from utils import create_embedding, generate_score_reason, generate_mismatch_explanation
from matching import (
    calculate_relevance_score, 
    calculate_guest_fit_score,
    calculate_recency_score,
    calculate_host_interest_score,
    calculate_aggregate_score
)

logger = logging.getLogger(__name__)

def init_routes(app):
    @app.route('/')
    def index():
        return redirect(url_for('upload_combined'))

    @app.route('/upload_combined')
    def upload_combined():
        clients = Client.query.all()
        return render_template('upload.html', clients=clients)

    @app.route('/get_clients')
    def get_clients():
        try:
            clients = Client.query.all()
            return jsonify([{'id': client.id, 'name': client.name} for client in clients])
        except Exception as e:
            logger.error(f"Error fetching clients: {str(e)}")
            return jsonify({"error": str(e)}), 500

    @app.route('/upload_client', methods=['POST'])
    def upload_client():
        try:
            client_id = request.form.get("client_id")

            if client_id == 'new':
                client_name = request.form.get("newClientNameInput")
                if client_name:
                    new_client = Client(name=client_name)
                    db.session.add(new_client)
                    db.session.commit()
                    client_id = new_client.id
                    logger.info(f"Added new client {client_name}")
                else:
                    flash("Client name missing.")
                    return redirect(url_for('upload_combined'))
            else:
                client_id = int(client_id) if client_id else None
                if not client_id:
                    flash("Invalid client selected.")
                    return redirect(url_for('upload_combined'))

            if 'files' not in request.files:
                flash('No files selected.')
                return redirect(url_for('upload_combined'))

            for file in request.files.getlist('files'):
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(filepath)

                    try:
                        if filename.endswith('.txt'):
                            with open(filepath, 'r', encoding='utf-8') as f:
                                transcription = f.read()
                        elif filename.endswith('.docx'):
                            doc = Document(filepath)
                            transcription = '\n'.join([paragraph.text for paragraph in doc.paragraphs])
                        else:
                            transcription = "Unsupported file type"
                            logger.warning(f"Unsupported file type: {filename}")
                    except Exception as e:
                        logger.error(f"Error processing {filename}: {str(e)}")
                        transcription = f"Error processing file: {str(e)}"

                    embedding = create_embedding(transcription)

                    client_data = ClientData(
                        client_id=client_id,
                        filename=filename[:500],
                        transcription=transcription,
                        embedding=embedding
                    )
                    db.session.add(client_data)

            db.session.commit()
            flash("Client data uploaded successfully.")
            return redirect(url_for('upload_combined'))

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error in upload_client: {str(e)}")
            flash(f"Error uploading client data: {str(e)}")
            return redirect(url_for('upload_combined'))

    @app.route('/upload_podcast', methods=['POST'])
    def upload_podcast():
        try:
            from scripts.main import process_podcast

            client_id = request.form.get("client_id")
            if not client_id:
                flash("Please select a client.")
                return redirect(url_for('upload_combined'))

            if 'file' not in request.files:
                flash('No file selected.')
                return redirect(url_for('upload_combined'))

            file = request.files['file']
            if file.filename == '':
                flash('No file selected.')
                return redirect(url_for('upload_combined'))

            if file:
                csv_data = file.read().decode('utf-8')
                csv_reader = csv.DictReader(StringIO(csv_data))
                
                new_podcasts = []
                updated_podcasts = []
                skipped_podcasts = []

                for row in csv_reader:
                    try:
                        # Check if podcast exists for this specific client
                        existing_podcast = Podcast.query.filter_by(
                            rss_feed=row['RSS Feed'],
                            client_id=client_id
                        ).first()

                        # Check if podcast exists for other clients
                        other_client_podcast = Podcast.query.filter(
                            Podcast.rss_feed==row['RSS Feed'],
                            Podcast.client_id!=client_id
                        ).first()

                        if existing_podcast:
                            if existing_podcast.status != 'Done':
                                process_podcast(existing_podcast, db, Episode)
                                updated_podcasts.append(existing_podcast.title or row['RSS Feed'])
                            else:
                                skipped_podcasts.append(existing_podcast.title or row['RSS Feed'])
                        else:
                            new_podcast = Podcast(
                                client_id=client_id,
                                search_term=row['Search Term'][:100],
                                listennotes_url=row['ListenNotes URL'][:255],
                                listen_score=row['ListenScore'],
                                global_rank=float(row['Global Rank'].strip('%')) / 100,
                                rss_feed=row['RSS Feed'][:255]
                            )
                            db.session.add(new_podcast)
                            db.session.commit()
                            
                            process_podcast(new_podcast, db, Episode)
                            new_podcasts.append(new_podcast.title or row['RSS Feed'])

                            if other_client_podcast:
                                flash(f"Note: Podcast '{row['RSS Feed']}' also exists for another client")

                    except Exception as e:
                        db.session.rollback()
                        logger.error(f"Error processing podcast row: {str(e)}")
                        flash(f"Error processing podcast: {row['RSS Feed']}")

                if new_podcasts:
                    flash(f"Added {len(new_podcasts)} new podcasts: {', '.join(new_podcasts)}")
                if updated_podcasts:
                    flash(f"Updated {len(updated_podcasts)} existing podcasts: {', '.join(updated_podcasts)}")
                if skipped_podcasts:
                    flash(f"Skipped {len(skipped_podcasts)} already processed podcasts: {', '.join(skipped_podcasts)}")

            return redirect(url_for('upload_combined'))

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error in upload_podcast: {str(e)}")
            flash(f"Error: {str(e)}")
            return redirect(url_for('upload_combined'))

    @app.route('/match_podcasts')
    def match_podcasts():
        try:
            client_id = request.args.get("client_id")

            if not client_id:
                return jsonify({"error": "Client ID is missing."}), 400

            client = db.session.get(Client, client_id)
            if not client:
                return jsonify({"error": "Invalid client ID."}), 400

            valid_client_files = [data for data in client.files if data.embedding is not None]
            if not valid_client_files:
                return jsonify({"error": "No valid client embeddings found."}), 400
            
            client_embeddings = np.array([data.embedding for data in valid_client_files])

            podcasts = Podcast.query.filter_by(client_id=client_id).all()
            valid_podcasts = [p for p in podcasts if p.embedding is not None]
            
            if not valid_podcasts:
                return jsonify({"error": "No valid podcast embeddings found."}), 400

            valid_episodes = []
            episode_to_podcast = {}
            for podcast in valid_podcasts:
                for episode in podcast.episodes:
                    if episode.embedding is not None:
                        valid_episodes.append(episode)
                        episode_to_podcast[episode.id] = podcast

            final_scores = []
            for podcast in valid_podcasts:
                # Calculate individual scores with improved algorithms
                relevance_score = calculate_relevance_score(
                    client_embeddings,
                    podcast.embedding,
                    podcast.categories
                )

                audience_score = float(podcast.listen_score)
                
                podcast_episodes = [e for e in valid_episodes if e.podcast_id == podcast.id]
                guest_fit_score = calculate_guest_fit_score(
                    client_embeddings,
                    [e.embedding for e in podcast_episodes]
                )
                
                recency_score = calculate_recency_score(podcast.last_updated)
                
                host_interest_score = calculate_host_interest_score(
                    podcast.global_rank,
                    podcast.listen_score
                )

                # Define weights
                weights = {
                    'relevance': 0.35,
                    'audience': 0.25,
                    'guest_fit': 0.20,
                    'recency': 0.10,
                    'host_interest': 0.10
                }

                # Calculate aggregate score
                scores = [
                    relevance_score,
                    audience_score,
                    guest_fit_score,
                    recency_score,
                    host_interest_score
                ]
                
                aggregate_score = calculate_aggregate_score(scores, weights)

                logger.info(f"""
                Podcast: {podcast.title}
                Detailed Scores:
                - Relevance: {relevance_score:.1f}
                - Audience: {audience_score:.1f}
                - Guest Fit: {guest_fit_score:.1f}
                - Recency: {recency_score:.1f}
                - Host Interest: {host_interest_score:.1f}
                - Aggregate: {aggregate_score:.1f}
                """)
                
                final_scores.append({
                    "podcast_name": podcast.title or f"Podcast {podcast.id}",
                    "relevance_score": round(relevance_score, 1),
                    "audience_score": round(audience_score, 1),
                    "guest_fit_score": round(guest_fit_score, 1),
                    "recency_score": round(recency_score, 1),
                    "host_interest_score": round(host_interest_score, 1),
                    "aggregate_score": round(aggregate_score, 1),
                    "reason": generate_score_reason(podcast, relevance_score, audience_score, recency_score),
                    "potential_mismatch": generate_mismatch_explanation(podcast, relevance_score, audience_score, recency_score)
                })

            final_scores.sort(key=lambda x: x["aggregate_score"], reverse=True)
            return jsonify(final_scores)

        except Exception as e:
            logger.error(f"Error in match_podcasts: {str(e)}")
            return jsonify({"error": f"An error occurred during matching: {str(e)}"}), 500

    return app 