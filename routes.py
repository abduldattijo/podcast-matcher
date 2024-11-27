from flask import render_template, request, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename
import os
import csv
from io import StringIO
from docx import Document
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import logging
from utils import create_embedding, generate_score_reason, generate_mismatch_explanation
from database import supabase
from bs4 import BeautifulSoup
from utils import (
    extract_text_from_html,
    parse_embedding_string,
    calculate_recency_score
)
import time

logger = logging.getLogger(__name__)

def process_batch(batch, client_id, supabase):
    """Process a batch of podcasts."""
    from main import process_podcast
    processed_count = 0
    
    for row in batch:
        try:
            # Check if podcast exists for this client
            existing_podcast = supabase.table('podcasts')\
                .select('*')\
                .eq('rss_feed', row['RSS Feed'])\
                .eq('client_id', client_id)\
                .execute()

            # Check if podcast exists for other clients
            other_client_podcast = supabase.table('podcasts')\
                .select('*')\
                .eq('rss_feed', row['RSS Feed'])\
                .neq('client_id', client_id)\
                .execute()

            if existing_podcast.data:
                podcast = existing_podcast.data[0]
                if podcast['status'] != 'Done':
                    process_podcast(podcast, supabase)
                    processed_count += 1
                    logger.info(f"Updated existing podcast: {podcast['title'] or row['RSS Feed']}")
            else:
                new_podcast = {
                    "client_id": client_id,
                    "search_term": row['Search Term'][:100],
                    "listennotes_url": row['ListenNotes URL'][:255],
                    "listen_score": int(row['ListenScore']) if row['ListenScore'] else 0,
                    "global_rank": float(row['Global Rank'].strip('%'))/100 if row['Global Rank'] else 1.0,
                    "rss_feed": row['RSS Feed'][:255],
                    "status": "New"
                }
                
                response = supabase.table('podcasts').insert(new_podcast).execute()
                new_podcast_data = response.data[0]
                
                process_podcast(new_podcast_data, supabase)
                processed_count += 1
                logger.info(f"Added new podcast: {row['RSS Feed']}")

                if other_client_podcast.data:
                    logger.info(f"Note: Podcast '{row['RSS Feed']}' exists for another client")

        except Exception as e:
            logger.error(f"Error processing podcast row: {str(e)}")
            continue
            
    return processed_count

def init_routes(app):
    @app.route('/')
    def index():
        return redirect(url_for('upload_combined'))

    @app.route('/upload_combined')
    def upload_combined():
        try:
            response = supabase.table('clients').select('*').execute()
            clients = response.data
            return render_template('upload.html', clients=clients)
        except Exception as e:
            logger.error(f"Error fetching clients: {str(e)}")
            flash("Error loading clients")
            return render_template('upload.html', clients=[])

    @app.route('/get_clients')
    def get_clients():
        try:
            response = supabase.table('clients').select('*').execute()
            return jsonify(response.data)
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
                    response = supabase.table('clients').insert({
                        "name": client_name
                    }).execute()
                    client_id = response.data[0]['id']
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
                        elif filename.endswith('.html'):
                            with open(filepath, 'r', encoding='utf-8') as f:
                                html_content = f.read()
                            transcription = extract_text_from_html(html_content)
                            if not transcription:
                                transcription = "Error processing HTML file"
                        else:
                            transcription = "Unsupported file type"
                            logger.warning(f"Unsupported file type: {filename}")
                    except Exception as e:
                        logger.error(f"Error processing {filename}: {str(e)}")
                        transcription = f"Error processing file: {str(e)}"

                    embedding = create_embedding(transcription)
                    if embedding is not None:
                        embedding_list = embedding.tolist() if isinstance(embedding, np.ndarray) else embedding
                        supabase.table('client_data').insert({
                            "client_id": client_id,
                            "filename": filename[:500],
                            "transcription": transcription,
                            "embedding": str(embedding_list)
                        }).execute()

                    try:
                        os.remove(filepath)
                    except Exception as e:
                        logger.error(f"Error removing temporary file {filepath}: {str(e)}")

            flash("Client data uploaded successfully.")
            return redirect(url_for('upload_combined'))

        except Exception as e:
            logger.error(f"Error in upload_client: {str(e)}")
            flash(f"Error uploading client data: {str(e)}")
            return redirect(url_for('upload_combined'))

    @app.route('/upload_podcast', methods=['POST'])
    def upload_podcast():
        try:
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
                rows = list(csv_reader)
                
                # Process in smaller batches with delay
                batch_size = 2
                total_rows = len(rows)
                total_processed = 0
                
                for i in range(0, total_rows, batch_size):
                    batch = rows[i:i + batch_size]
                    batch_processed = process_batch(batch, client_id, supabase)
                    total_processed += batch_processed
                    
                    # Log progress
                    progress = (i + len(batch)) / total_rows * 100
                    logger.info(f"Progress: {progress:.1f}% ({total_processed}/{total_rows} podcasts processed)")
                    
                    # Add delay between batches
                    if i + batch_size < total_rows:
                        time.sleep(1)
                
                flash(f"Successfully processed {total_processed} podcasts")
                return redirect(url_for('upload_combined'))

        except Exception as e:
            logger.error(f"Error in upload_podcast: {str(e)}")
            flash(f"Error: {str(e)}")
            return redirect(url_for('upload_combined'))

    @app.route('/match_podcasts')
    def match_podcasts():
        try:
            client_id = request.args.get("client_id")
            min_score = float(request.args.get("min_score", 20))
            max_score = float(request.args.get("max_score", 100))
            include_blank = request.args.get("include_blank", "false").lower() == "true"

            if not client_id:
                return jsonify({"error": "Client ID is missing."}), 400

            # Get client data
            client_data = supabase.table('client_data')\
                .select('*')\
                .eq('client_id', client_id)\
                .execute()

            if not client_data.data:
                return jsonify({"error": "No client data found."}), 400

            # Parse embeddings
            valid_client_files = []
            for data in client_data.data:
                if data.get('embedding'):
                    embedding = parse_embedding_string(data['embedding'])
                    if embedding:
                        data['embedding'] = embedding
                        valid_client_files.append(data)

            if not valid_client_files:
                return jsonify({"error": "No valid client embeddings found."}), 400
            
            client_embeddings = np.array([data['embedding'] for data in valid_client_files])

            # Get podcasts with listen score filter
            podcasts = supabase.table('podcasts')\
                .select('*')\
                .eq('client_id', client_id)\
                .execute()

            if not podcasts.data:
                return jsonify({"error": "No podcasts found."}), 400

            # Apply listen score filter and parse embeddings
            valid_podcasts = []
            for podcast in podcasts.data:
                try:
                    if podcast.get('embedding'):
                        embedding = parse_embedding_string(podcast['embedding'])
                        if embedding:
                            listen_score = podcast.get('listen_score')
                            
                            if listen_score is None:
                                if include_blank:
                                    podcast['embedding'] = embedding
                                    valid_podcasts.append(podcast)
                            else:
                                score = float(listen_score)
                                if min_score <= score <= max_score:
                                    podcast['embedding'] = embedding
                                    valid_podcasts.append(podcast)
                                    
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid listen score for podcast {podcast.get('id')}: {e}")
                    continue

            if not valid_podcasts:
                return jsonify({"error": "No valid podcast matches found with the selected filters."}), 400

            podcast_embeddings = np.array([p['embedding'] for p in valid_podcasts])

            # Get episodes
            episode_ids = [p['id'] for p in valid_podcasts]
            episodes = supabase.table('episodes')\
                .select('*')\
                .in_('podcast_id', episode_ids)\
                .execute()

            valid_episodes = []
            for episode in episodes.data:
                if episode.get('embedding'):
                    embedding = parse_embedding_string(episode['embedding'])
                    if embedding:
                        episode['embedding'] = embedding
                        valid_episodes.append(episode)

            final_scores = []
            for podcast in valid_podcasts:
                # Get podcast's episodes
                podcast_episodes = [e for e in valid_episodes if e['podcast_id'] == podcast['id']]
                
                # Calculate scores
                relevance_scores = cosine_similarity([podcast['embedding']], client_embeddings)
                relevance_score = float(relevance_scores.mean()) * 100

                if podcast_episodes:
                    episode_embeddings = np.array([e['embedding'] for e in podcast_episodes])
                    episode_scores = cosine_similarity(client_embeddings, episode_embeddings)
                    guest_fit_score = float(episode_scores.mean()) * 100
                else:
                    guest_fit_score = 0.0

                audience_score = float(podcast['listen_score']) if podcast.get('listen_score') is not None else 0.0
                host_interest_score = 100.0 * (1 - podcast['global_rank'])
                recency_score = calculate_recency_score(podcast.get('last_updated'))

                # Calculate weighted aggregate score
                weights = {
                    'relevance': 0.35,
                    'audience': 0.25,
                    'guest_fit': 0.20,
                    'recency': 0.10,
                    'host_interest': 0.10
                }

                aggregate_score = (
                    relevance_score * weights['relevance'] +
                    audience_score * weights['audience'] +
                    guest_fit_score * weights['guest_fit'] +
                    recency_score * weights['recency'] +
                    host_interest_score * weights['host_interest']
                )

                # Generate explanations
                reason = generate_score_reason(podcast, relevance_score, audience_score, recency_score)
                potential_mismatch = generate_mismatch_explanation(podcast, relevance_score, audience_score, recency_score)

                final_scores.append({
                    "podcast_name": podcast['title'] or f"Podcast {podcast['id']}",
                    "relevance_score": round(relevance_score, 1),
                    "audience_score": round(audience_score, 1),
                    "guest_fit_score": round(guest_fit_score, 1),
                    "recency_score": round(recency_score, 1),
                    "host_interest_score": round(host_interest_score, 1),
                    "aggregate_score": round(aggregate_score, 1),
                    "reason": reason,
                    "potential_mismatch": potential_mismatch
                })

            # Sort by aggregate score
            final_scores.sort(key=lambda x: x["aggregate_score"], reverse=True)
            return jsonify(final_scores)

        except Exception as e:
            logger.error(f"Error in match_podcasts: {str(e)}")
            return jsonify({"error": str(e)}), 500

    return app