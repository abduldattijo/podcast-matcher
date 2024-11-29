from flask import render_template, request, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename
import os
import csv
from io import StringIO
from docx import Document
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import logging
from utils import create_embedding, generate_score_reason, generate_mismatch_explanation, calculate_recency_score
from database import supabase
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

def parse_embedding_string(embedding_str):
    """Parse embedding string into a list of floats."""
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

def extract_text_from_html(html_content):
    """Extract clean text from HTML content."""
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

                    # Clean up uploaded file
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
            from main import process_podcast

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
                        existing_podcast = supabase.table('podcasts')\
                            .select('*')\
                            .eq('rss_feed', row['RSS Feed'])\
                            .eq('client_id', client_id)\
                            .execute()

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
            min_score = float(request.args.get("min_score", 20))
            max_score = float(request.args.get("max_score", 100))
            include_blank = request.args.get("include_blank", "false").lower() == "true"

            if not client_id:
                return jsonify({"error": "Client ID is missing."}), 400

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

            # Get podcasts from Supabase with listen score filtering
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
                            
                            # Handle listen score filtering
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

            # Get episodes for all valid podcasts
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
                audience_score = float(podcast['listen_score']) if podcast.get('listen_score') is not None else 0.0

                # Calculate host interest score
                host_interest_score = 100.0 * (1 - podcast['global_rank'])

                # Calculate recency score
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
            return jsonify({"error": f"An error occurred during matching: {str(e)}"}), 500

    @app.route('/get_podcast_stats')
    def get_podcast_stats():
        try:
            client_id = request.args.get("client_id")
            if not client_id:
                return jsonify({"error": "Client ID is missing."}), 400

            podcasts = supabase.table('podcasts')\
                .select('listen_score,global_rank,last_updated')\
                .eq('client_id', client_id)\
                .execute()

            if not podcasts.data:
                return jsonify({
                    "total_podcasts": 0,
                    "avg_listen_score": 0,
                    "high_performing": 0,
                    "recently_active": 0
                })

            total_podcasts = len(podcasts.data)
            valid_scores = [p['listen_score'] for p in podcasts.data if p.get('listen_score') is not None]
            avg_listen_score = sum(valid_scores) / len(valid_scores) if valid_scores else 0
            high_performing = len([s for s in valid_scores if s >= 80])
            
            from datetime import datetime, timedelta
            recent_cutoff = datetime.now() - timedelta(days=30)
            recently_active = len([
                p for p in podcasts.data 
                if p.get('last_updated') and 
                datetime.strptime(p['last_updated'], '%m-%d-%Y') > recent_cutoff
            ])

            return jsonify({
                "total_podcasts": total_podcasts,
                "avg_listen_score": round(avg_listen_score, 1),
                "high_performing": high_performing,
                "recently_active": recently_active
            })

        except Exception as e:
            logger.error(f"Error getting podcast stats: {str(e)}")
            return jsonify({"error": str(e)}), 500

    @app.route('/update_podcast_status', methods=['POST'])
    def update_podcast_status():
        try:
            data = request.get_json()
            podcast_id = data.get('podcast_id')
            new_status = data.get('status')

            if not podcast_id or not new_status:
                return jsonify({"error": "Missing required fields"}), 400

            supabase.table('podcasts')\
                .update({"status": new_status})\
                .eq('id', podcast_id)\
                .execute()

            return jsonify({"success": True, "message": "Status updated successfully"})

        except Exception as e:
            logger.error(f"Error updating podcast status: {str(e)}")
            return jsonify({"error": str(e)}), 500

    @app.route('/delete_podcast', methods=['POST'])
    def delete_podcast():
        try:
            data = request.get_json()
            podcast_id = data.get('podcast_id')

            if not podcast_id:
                return jsonify({"error": "Podcast ID is required"}), 400

            # Delete associated episodes first
            supabase.table('episodes')\
                .delete()\
                .eq('podcast_id', podcast_id)\
                .execute()

            # Then delete the podcast
            supabase.table('podcasts')\
                .delete()\
                .eq('id', podcast_id)\
                .execute()

            return jsonify({
                "success": True, 
                "message": "Podcast and associated episodes deleted successfully"
            })

        except Exception as e:
            logger.error(f"Error deleting podcast: {str(e)}")
            return jsonify({"error": str(e)}), 500

    @app.route('/clear_client_data', methods=['POST'])
    def clear_client_data():
        try:
            data = request.get_json()
            client_id = data.get('client_id')

            if not client_id:
                return jsonify({"error": "Client ID is required"}), 400

            # Delete all client data
            supabase.table('client_data')\
                .delete()\
                .eq('client_id', client_id)\
                .execute()

            return jsonify({
                "success": True,
                "message": "Client data cleared successfully"
            })

        except Exception as e:
            logger.error(f"Error clearing client data: {str(e)}")
            return jsonify({"error": str(e)}), 500

    @app.route('/export_matches', methods=['GET'])
    def export_matches():
        try:
            client_id = request.args.get("client_id")
            if not client_id:
                return jsonify({"error": "Client ID is required"}), 400

            # Get client name
            client = supabase.table('clients')\
                .select('name')\
                .eq('id', client_id)\
                .execute()
            
            client_name = client.data[0]['name'] if client.data else "Unknown Client"

            # Get matched podcasts
            matches = supabase.table('podcasts')\
                .select('*')\
                .eq('client_id', client_id)\
                .execute()

            if not matches.data:
                return jsonify({"error": "No matches found"}), 404

            # Create CSV content
            output = StringIO()
            writer = csv.writer(output)
            
            # Write headers
            writer.writerow([
                'Podcast Name',
                'Listen Score',
                'Global Rank',
                'Categories',
                'Contact Name',
                'Contact Email',
                'ListenNotes URL',
                'RSS Feed',
                'Last Updated'
            ])

            # Write data
            for match in matches.data:
                writer.writerow([
                    match.get('title', ''),
                    match.get('listen_score', ''),
                    f"{(match.get('global_rank', 0) * 100):.1f}%",
                    match.get('categories', ''),
                    match.get('contact_name', ''),
                    match.get('contact_email', ''),
                    match.get('listennotes_url', ''),
                    match.get('rss_feed', ''),
                    match.get('last_updated', '')
                ])

            # Create response
            from flask import Response
            output.seek(0)
            return Response(
                output.getvalue(),
                mimetype='text/csv',
                headers={
                    "Content-Disposition": f"attachment;filename=podcast_matches_{client_name}.csv"
                }
            )

        except Exception as e:
            logger.error(f"Error exporting matches: {str(e)}")
            return jsonify({"error": str(e)}), 500

    @app.errorhandler(404)
    def not_found_error(error):
        return jsonify({"error": "Resource not found"}), 404

    @app.errorhandler(500)
    def internal_error(error):
        logger.error(f"Internal server error: {str(error)}")
        return jsonify({"error": "Internal server error"}), 500
       
    @app.route('/upload_status')
    def upload_status():
        return jsonify({"status": "complete"})

    return app