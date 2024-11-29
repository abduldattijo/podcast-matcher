from flask import render_template, request, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename
import os
import csv
from io import StringIO
from docx import Document
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import logging
from utils import create_embedding
from database import supabase
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

def parse_embedding_string(embedding_str):
    try:
        if isinstance(embedding_str, list):
            return embedding_str
        if isinstance(embedding_str, str):
            embedding_str = embedding_str.strip('[]')
            return [float(x.strip()) for x in embedding_str.split(',')]
        return None
    except Exception as e:
        logger.error(f"Error parsing embedding: {str(e)}")
        return None

def parse_listen_score_ranges(ls_ranges_str):
    try:
        if not ls_ranges_str:
            return []
        
        ranges = []
        for range_str in ls_ranges_str.split(','):
            if range_str == "80-100":
                ranges.append((80, 100))
            else:
                start, end = map(int, range_str.split('-'))
                ranges.append((start, end))
        return ranges
    except Exception as e:
        logger.error(f"Error parsing listen score ranges: {str(e)}")
        return []

def is_in_listen_score_range(score, ranges):
    if not ranges:
        return True
    for start, end in ranges:
        if start <= score <= end:
            return True
    return False

def extract_text_from_html(html_content):
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()
        # Get text
        text = soup.get_text()
        # Clean up whitespace
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = ' '.join(chunk for chunk in chunks if chunk)
        return text
    except Exception as e:
        logger.error(f"Error extracting text from HTML: {str(e)}")
        return None

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

            flash("Client data uploaded successfully.")
            return redirect(url_for('upload_combined'))

        except Exception as e:
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
                                updated_podcasts.append(podcast['title'] or row['RSS Feed'])
                            else:
                                skipped_podcasts.append(podcast['title'] or row['RSS Feed'])
                        else:
                            new_podcast = {
                                "client_id": client_id,
                                "search_term": row['Search Term'][:100],
                                "listennotes_url": row['ListenNotes URL'][:255],
                                "listen_score": int(row['ListenScore']),
                                "global_rank": float(row['Global Rank'].strip('%')) / 100,
                                "rss_feed": row['RSS Feed'][:255],
                                "status": "New"
                            }
                            
                            response = supabase.table('podcasts').insert(new_podcast).execute()
                            new_podcast_data = response.data[0]
                            
                            process_podcast(new_podcast_data, supabase)
                            new_podcasts.append(new_podcast_data['title'] or row['RSS Feed'])

                            if other_client_podcast.data:
                                flash(f"Note: Podcast '{row['RSS Feed']}' also exists for another client")

                    except Exception as e:
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
            logger.error(f"Error in upload_podcast: {str(e)}")
            flash(f"Error: {str(e)}")
            return redirect(url_for('upload_combined'))

    @app.route('/match_podcasts')
    def match_podcasts():
        try:
            client_id = request.args.get("client_id")
            ls_ranges_str = request.args.get("ls_ranges", "")

            if not client_id:
                return jsonify({"error": "Client ID is missing."}), 400

            # Parse listen score ranges
            ls_ranges = parse_listen_score_ranges(ls_ranges_str)
            logger.info(f"Applying listen score ranges: {ls_ranges}")

            # Get client data from Supabase
            client_data = supabase.table('client_data')\
                .select('*')\
                .eq('client_id', client_id)\
                .execute()

            if not client_data.data:
                return jsonify({"error": "No client data found."}), 400

            # Parse embeddings from strings to float arrays
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

            # Get podcasts from Supabase
            podcasts = supabase.table('podcasts')\
                .select('*')\
                .eq('client_id', client_id)\
                .execute()

            if not podcasts.data:
                return jsonify({"error": "No podcasts found."}), 400

            # Apply listen score filter and parse embeddings
            valid_podcasts = []
            for p in podcasts.data:
                try:
                    listen_score = float(p['listen_score'])
                    if p.get('embedding') and (not ls_ranges or is_in_listen_score_range(listen_score, ls_ranges)):
                        embedding = parse_embedding_string(p['embedding'])
                        if embedding:
                            p['embedding'] = embedding
                            valid_podcasts.append(p)
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid listen score for podcast {p.get('id')}: {e}")
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
            for e in episodes.data:
                if e.get('embedding'):
                    embedding = parse_embedding_string(e['embedding'])
                    if embedding:
                        e['embedding'] = embedding
                        valid_episodes.append(e)

            final_scores = []
            for podcast in valid_podcasts:
                # Get podcast's episodes
                podcast_episodes = [e for e in valid_episodes if e['podcast_id'] == podcast['id']]
                
                # Calculate relevance score
                relevance_scores = cosine_similarity([podcast['embedding']], client_embeddings)
                relevance_score = float(relevance_scores.mean()) * 100

                # Calculate guest fit score
                if podcast_episodes:
                    episode_embeddings = np.array([e['embedding'] for e in podcast_episodes])
                    episode_scores = cosine_similarity(client_embeddings, episode_embeddings)
                    guest_fit_score = float(episode_scores.mean()) * 100
                else:
                    guest_fit_score = 0.0

                # Get audience score from listen_score
                audience_score = float(podcast['listen_score'])

                # Calculate host interest score
                host_interest_score = 100.0 * (1 - podcast['global_rank'])

                # Calculate recency score
                if podcast.get('last_updated'):
                    from datetime import datetime
                    last_update = datetime.strptime(podcast['last_updated'], '%m-%d-%Y')
                    days_difference = (datetime.now() - last_update).days
                    if days_difference <= 7:
                        recency_score = 100.0
                    elif days_difference <= 14:
                        recency_score = 85.0
                    elif days_difference <= 30:
                        recency_score = 70.0
                    elif days_difference <= 60:
                        recency_score = 55.0
                    else:
                        recency_score = 40.0
                else:
                    recency_score = 0.0

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
                reasons = []
                mismatches = []

                # Relevance explanation
                if relevance_score >= 90:
                    reasons.append("Exceptional content match")
                elif relevance_score >= 75:
                    reasons.append("Strong content alignment")
                elif relevance_score >= 60:
                    reasons.append("Good content fit")
                else:
                    reasons.append("Moderate content match")
                    mismatches.append("Content alignment could be stronger")

                # Audience explanation
                if audience_score >= 90:
                    reasons.append("Exceptional listener engagement")
                elif audience_score >= 75:
                    reasons.append("Strong audience base")
                elif audience_score >= 60:
                    reasons.append("Good listener base")
                else:
                    reasons.append("Moderate audience reach")
                    mismatches.append("Limited audience reach")

                # Recency explanation
                if recency_score >= 90:
                    reasons.append("Very actively publishing")
                elif recency_score >= 75:
                    reasons.append("Recently active")
                elif recency_score >= 60:
                    reasons.append("Moderately active")
                else:
                    reasons.append("Less recent activity")
                    mismatches.append("Publishing frequency could be more consistent")

                if podcast.get('categories'):
                    reasons.append(f"Topics: {podcast['categories']}")

                logger.info(f"""
                Podcast: {podcast['title']}
                Detailed Scores:
                - Relevance: {relevance_score:.1f}
                - Audience: {audience_score:.1f}
                - Guest Fit: {guest_fit_score:.1f}
                - Recency: {recency_score:.1f}
                - Host Interest: {host_interest_score:.1f}
                - Aggregate: {aggregate_score:.1f}
                """)

                final_scores.append({
                    "podcast_name": podcast['title'] or f"Podcast {podcast['id']}",
                    "relevance_score": round(relevance_score, 1),
                    "audience_score": round(audience_score, 1),
                    "guest_fit_score": round(guest_fit_score, 1),
                    "recency_score": round(recency_score, 1),
                    "host_interest_score": round(host_interest_score, 1),
                    "aggregate_score": round(aggregate_score, 1),
                    "reason": " | ".join(reasons),
                    "potential_mismatch": " | ".join(mismatches) if mismatches else "No significant concerns identified"
                })

            # Sort by aggregate score
            final_scores.sort(key=lambda x: x["aggregate_score"], reverse=True)
            return jsonify(final_scores)

        except Exception as e:
            logger.error(f"Error in match_podcasts: {str(e)}")
            return jsonify({"error": f"An error occurred during matching: {str(e)}"}), 500

    return app