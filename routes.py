from flask import render_template, request, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename
import os
import csv
from io import StringIO
from docx import Document
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import logging
import time
from typing import Generator, List, Dict
from utils import (
    create_embedding, 
    generate_score_reason, 
    generate_mismatch_explanation, 
    calculate_recency_score,
    extract_text_content
)
from database import supabase
from bs4 import BeautifulSoup
from matching import calculate_relevance_score
from flask import Response

from matching import calculate_guest_fit_score

logger = logging.getLogger(__name__)

def process_file_in_chunks(file, chunk_size: int = 4096) -> Generator[str, None, None]:
    """Process large files in chunks."""
    for chunk in iter(lambda: file.read(chunk_size), b''):
        yield chunk.decode('utf-8')

def batch_db_operations(items: List, batch_size: int = 5) -> Generator[List, None, None]:
    """Process database operations in small batches."""
    for i in range(0, len(items), batch_size):
        yield items[i:i + batch_size]

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
        for script in soup(["script", "style"]):
            script.decompose()
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = ' '.join(chunk for chunk in chunks if chunk)
        return text
    except Exception as e:
        logger.error(f"Error extracting text from HTML: {str(e)}")
        return None

def safe_cleanup(obj=None):
    """Safe memory cleanup without gc."""
    if obj:
        try:
            del obj
        except:
            pass

def process_single_podcast(podcast: Dict):
    """Process single podcast with safe memory handling."""
    try:
        from main import process_podcast
        return process_podcast(podcast, supabase)
    except Exception as e:
        logger.error(f"Single podcast error: {str(e)}")
        return None

def process_podcast_batch(podcasts: List[Dict], batch_size: int = 5):
    """Process podcasts in small batches with safety checks."""
    results = []
    for i in range(0, len(podcasts), batch_size):
        batch = podcasts[i:i + batch_size]
        for podcast in batch:
            try:
                response = supabase.table('podcasts').insert(podcast).execute()
                if response.data:
                    result = process_single_podcast(response.data[0])
                    if result:
                        results.append(result)
            except Exception as e:
                logger.error(f"Podcast processing error: {str(e)}")
            finally:
                safe_cleanup(response)

        time.sleep(1)  # Allow system to stabilize
    
    return results

def process_podcast_scores(client_embeddings: List, podcast_batch: List[Dict], batch_size: int):
    """Process podcast scoring with safe memory management."""
    scores = []
    for podcast in podcast_batch:
        try:
            if not podcast.get('embedding'):
                continue

            embedding = parse_embedding_string(podcast['embedding'])
            if not embedding:
                continue

            # Calculate scores
            relevance_score = calculate_relevance_score(
                client_embeddings, 
                embedding, 
                podcast.get('categories', '')
            )
            
            audience_score = float(podcast['listen_score']) if podcast.get('listen_score') else 0.0
            recency_score = calculate_recency_score(podcast.get('last_updated'))
            host_interest_score = 100.0 * (1 - podcast['global_rank'])

            # Get episodes in batches
            episode_embeddings = []
            offset = 0
            while True:
                episodes = supabase.table('episodes')\
                    .select('embedding')\
                    .eq('podcast_id', podcast['id'])\
                    .range(offset, offset + batch_size - 1)\
                    .execute()
                
                if not episodes.data:
                    break
                    
                for episode in episodes.data:
                    if embedding := parse_embedding_string(episode.get('embedding')):
                        episode_embeddings.append(embedding)
                
                offset += batch_size
                safe_cleanup(episodes)
                
                if len(episodes.data) < batch_size:
                    break

            # Calculate guest fit score
            guest_fit_score = calculate_guest_fit_score(
                client_embeddings,
                episode_embeddings
            )

            # Calculate aggregate score
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

            scores.append({
                "podcast_name": podcast['title'] or f"Podcast {podcast['id']}",
                "relevance_score": round(relevance_score, 1),
                "audience_score": round(audience_score, 1),
                "guest_fit_score": round(guest_fit_score, 1),
                "recency_score": round(recency_score, 1),
                "host_interest_score": round(host_interest_score, 1),
                "aggregate_score": round(aggregate_score, 1),
                "reason": generate_score_reason(podcast, relevance_score, audience_score, recency_score),
                "potential_mismatch": generate_mismatch_explanation(podcast, relevance_score, audience_score, recency_score)
            })

            safe_cleanup(episode_embeddings)

        except Exception as e:
            logger.error(f"Error processing podcast {podcast.get('id')}: {str(e)}")
            continue

    return scores

def init_routes(app):
    @app.route('/')
    def index():
        return redirect(url_for('upload_combined'))

    @app.route('/upload_combined')
    def upload_combined():
        try:
            response = supabase.table('clients').select('*').execute()
            clients = response.data
            safe_cleanup(response)
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
            chunk_size = app.config['UPLOAD_CHUNK_SIZE']

            if client_id == 'new':
                client_name = request.form.get("newClientNameInput")
                if client_name:
                    response = supabase.table('clients').insert({
                        "name": client_name
                    }).execute()
                    client_id = response.data[0]['id']
                    logger.info(f"Added new client {client_name}")
                    safe_cleanup(response)
                else:
                    flash("Client name missing.")
                    return redirect(url_for('upload_combined'))
            else:
                client_id = int(client_id) if client_id else None
                if not client_id:
                    flash("Invalid client selected.")
                    return redirect(url_for('upload_combined'))

            for file in request.files.getlist('files'):
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    
                    with open(filepath, 'wb') as f:
                        while True:
                            chunk = file.stream.read(chunk_size)
                            if not chunk:
                                break
                            f.write(chunk)
                            time.sleep(0.1)  # Prevent timeout

                    try:
                        transcription = extract_text_content(filepath, filename.split('.')[-1].lower())
                        if not transcription:
                            transcription = "Error processing file"
                    except Exception as e:
                        logger.error(f"Error processing {filename}: {str(e)}")
                        transcription = f"Error processing file: {str(e)}"

                    # Process embedding in smaller chunks
                    if len(transcription) > 8000:
                        chunks = [transcription[i:i+8000] for i in range(0, len(transcription), 8000)]
                        embeddings = []
                        for chunk in chunks:
                            chunk_embedding = create_embedding(chunk)
                            if chunk_embedding is not None:
                                embeddings.append(chunk_embedding)
                            time.sleep(0.1)  # Prevent timeout
                        if embeddings:
                            embedding = np.mean(embeddings, axis=0)
                        else:
                            embedding = None
                    else:
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

                    time.sleep(0.1)  # Prevent timeout

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
                return jsonify({"error": "Client ID required"}), 400

            if 'file' not in request.files:
                return jsonify({"error": "No file uploaded"}), 400

            file = request.files['file']
            if not file.filename:
                return jsonify({"error": "No file selected"}), 400

            # Stream process the CSV
            stream = StringIO()
            chunk_size = 4096  # 4KB chunks
            while True:
                chunk = file.read(chunk_size).decode('utf-8')
                if not chunk:
                    break
                stream.write(chunk)
                time.sleep(0.1)  # Prevent timeout

            stream.seek(0)
            reader = csv.DictReader(stream)
            podcasts = []
            batch_size = 5  # Process 5 podcasts at a time

            for row in reader:
                try:
                    podcasts.append({
                        "client_id": client_id,
                        "search_term": row['Search Term'][:100],
                        "listennotes_url": row['ListenNotes URL'][:255],
                        "listen_score": int(row['ListenScore']),
                        "global_rank": float(row['Global Rank'].strip('%')) / 100,
                        "rss_feed": row['RSS Feed'][:255],
                        "status": "New"
                    })

                    if len(podcasts) >= batch_size:
                        process_podcast_batch(podcasts, batch_size)
                        podcasts = []
                        time.sleep(1)  # Pause between batches

                except (ValueError, KeyError) as e:
                    logger.error(f"Error parsing row: {str(e)}")
                    continue

            # Process remaining podcasts
            if podcasts:
                process_podcast_batch(podcasts, batch_size)

            safe_cleanup(stream)
            return jsonify({"success": True})

        except Exception as e:
            logger.error(f"Upload error: {str(e)}")
            return jsonify({"error": str(e)}), 500

    @app.route('/match_podcasts')
    def match_podcasts():
        try:
            client_id = request.args.get("client_id")
            min_score = float(request.args.get("min_score", 20))
            max_score = float(request.args.get("max_score", 100))
            include_blank = request.args.get("include_blank", "false").lower() == "true"
            batch_size = 5  # Smaller batch size

            if not client_id:
                return jsonify({"error": "Client ID is missing."}), 400

            # Get client data in batches
            client_embeddings = []
            offset = 0
            while True:
                batch = supabase.table('client_data')\
                    .select('embedding')\
                    .eq('client_id', client_id)\
                    .range(offset, offset + batch_size - 1)\
                    .execute()
                
                if not batch.data:
                    break
                    
                for data in batch.data:
                    if embedding := parse_embedding_string(data.get('embedding')):
                        client_embeddings.append(embedding)
                
                offset += batch_size
                safe_cleanup(batch)
                time.sleep(0.1)  # Prevent timeout
                
                if len(batch.data) < batch_size:
                    break

            if not client_embeddings:
                return jsonify({"error": "No valid client embeddings found."}), 400

            # Get podcasts in batches
            valid_podcasts = []
            offset = 0
            while True:
                batch = supabase.table('podcasts')\
                    .select('*')\
                    .eq('client_id', client_id)\
                    .range(offset, offset + batch_size - 1)\
                    .execute()
                
                if not batch.data:
                    break

                for podcast in batch.data:
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
                
                offset += batch_size
                safe_cleanup(batch)
                time.sleep(0.1)  # Prevent timeout
                
                if len(batch.data) < batch_size:
                    break

            if not valid_podcasts:
                return jsonify({"error": "No valid podcast matches found with the selected filters."}), 400

            # Process matches in batches
            final_scores = []
            for podcast_batch in batch_db_operations(valid_podcasts, batch_size):
                batch_scores = process_podcast_scores(
                    client_embeddings, 
                    podcast_batch,
                    batch_size
                )
                final_scores.extend(batch_scores)
                time.sleep(0.1)  # Prevent timeout

            safe_cleanup(valid_podcasts)
            return jsonify(sorted(final_scores, key=lambda x: x["aggregate_score"], reverse=True))

        except Exception as e:
            logger.error(f"Error in match_podcasts: {str(e)}")
            return jsonify({"error": str(e)}), 500

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

            from datetime import datetime, timedelta
            recent_cutoff = datetime.now() - timedelta(days=30)
            
            total_podcasts = len(podcasts.data)
            valid_scores = [p['listen_score'] for p in podcasts.data if p.get('listen_score') is not None]
            avg_listen_score = sum(valid_scores) / len(valid_scores) if valid_scores else 0
            high_performing = len([s for s in valid_scores if s >= 80])
            recently_active = len([
                p for p in podcasts.data 
                if p.get('last_updated') and 
                datetime.strptime(p['last_updated'], '%m-%d-%Y') > recent_cutoff
            ])

            safe_cleanup(podcasts)
            return jsonify({
                "total_podcasts": total_podcasts,
                "avg_listen_score": round(avg_listen_score, 1),
                "high_performing": high_performing,
                "recently_active": recently_active
            })

        except Exception as e:
            logger.error(f"Error getting podcast stats: {str(e)}")
            return jsonify({"error": str(e)}), 500

    @app.route('/export_matches', methods=['GET'])
    def export_matches():
        try:
            client_id = request.args.get("client_id")
            if not client_id:
                return jsonify({"error": "Client ID is required"}), 400

            client = supabase.table('clients')\
                .select('name')\
                .eq('id', client_id)\
                .execute()
            
            client_name = client.data[0]['name'] if client.data else "Unknown Client"
            safe_cleanup(client)

            matches = []
            offset = 0
            batch_size = 5
            
            while True:
                batch = supabase.table('podcasts')\
                    .select('*')\
                    .eq('client_id', client_id)\
                    .range(offset, offset + batch_size - 1)\
                    .execute()
                
                if not batch.data:
                    break
                    
                matches.extend(batch.data)
                offset += batch_size
                safe_cleanup(batch)
                time.sleep(0.1)  # Prevent timeout
                
                if len(batch.data) < batch_size:
                    break

            if not matches:
                return jsonify({"error": "No matches found"}), 404

            output = StringIO()
            writer = csv.writer(output)
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

            for batch in batch_db_operations(matches, batch_size):
                for match in batch:
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
                time.sleep(0.1)  # Prevent timeout

            safe_cleanup(matches)
            output.seek(0)
            response = Response(
                output.getvalue(),
                mimetype='text/csv',
                headers={
                    "Content-Disposition": f"attachment;filename=podcast_matches_{client_name}.csv"
                }
            )
            
            safe_cleanup(output)
            return response

        except Exception as e:
            logger.error(f"Error exporting matches: {str(e)}")
            return jsonify({"error": str(e)}), 500

    return app