from flask import render_template, request, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename
import os
import csv
from io import StringIO
from docx import Document
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import logging
import psutil
from functools import wraps
import time
import gc
from utils import create_embedding, generate_score_reason, generate_mismatch_explanation, calculate_recency_score
from database import supabase
from bs4 import BeautifulSoup


logger = logging.getLogger(__name__)

def clean_numeric_value(raw_score, default_value):
    return ''.join(filter(str.isdigit, raw_score)) or default_value

def validate_url(url):
    """Validate and clean URL"""
    if not url:
        return None
        
    url = url.strip()
    if not url:
        return None
        
    # Add scheme if missing
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
        
    try:
        from urllib.parse import urlparse
        result = urlparse(url)
        if not result.scheme or not result.netloc:
            return None
        return url
    except:
        return None

def read_csv_data(file_obj):
    """Read and pre-validate CSV data"""
    try:
        csv_data = file_obj.read().decode('utf-8')
        reader = csv.DictReader(StringIO(csv_data))
        
        # Verify required columns exist
        required_columns = {'RSS Feed', 'ListenScore', 'Global Rank'}
        columns = set(reader.fieldnames) if reader.fieldnames else set()
        missing_columns = required_columns - columns
        
        if missing_columns:
            logger.error(f"Missing required columns: {missing_columns}")
            return None, f"CSV is missing required columns: {', '.join(missing_columns)}"
            
        rows = list(reader)
        logger.info(f"Read {len(rows)} rows from CSV")
        return rows, None
        
    except Exception as e:
        logger.error(f"Error reading CSV: {str(e)}")
        return None, f"Error reading CSV file: {str(e)}"

def validate_url(url):
    """Validate and clean URL"""
    if not url:
        return None
        
    url = url.strip()
    if not url:
        return None
        
    # Handle URLs that might be wrapped in quotes
    url = url.strip('"\'')
    
    # Add scheme if missing
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
        
    try:
        from urllib.parse import urlparse, quote
        # Handle URLs with special characters
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return None
            
        # Reconstruct URL with proper encoding
        path = quote(parsed.path) if parsed.path else ''
        query = quote(parsed.query, safe='=&') if parsed.query else ''
        fragment = quote(parsed.fragment) if parsed.fragment else ''
        
        reconstructed = f"{parsed.scheme}://{parsed.netloc}{path}"
        if query:
            reconstructed += f"?{query}"
        if fragment:
            reconstructed += f"#{fragment}"
            
        return reconstructed
    except Exception as e:
        logger.warning(f"URL validation failed for '{url}': {str(e)}")
        return None

def validate_podcast_row(row, row_number):
    """Validate and clean podcast row data with enhanced error handling"""
    try:
        # Validate RSS Feed (required field)
        rss_feed = row.get('RSS Feed', '').strip()
        if not rss_feed:
            logger.warning(f"Row {row_number}: Empty RSS feed URL")
            return None, "Empty RSS feed URL"

        validated_url = validate_url(rss_feed)
        if not validated_url:
            logger.warning(f"Row {row_number}: Invalid RSS feed URL: {rss_feed}")
            return None, f"Invalid RSS feed URL: {rss_feed}"

        # Clean numeric values
        try:
            listen_score = int(clean_numeric_value(row.get('ListenScore', '0'), 0))
            listen_score = max(0, min(listen_score, 100))
        except ValueError as e:
            logger.warning(f"Row {row_number}: Invalid ListenScore: {row.get('ListenScore')}")
            listen_score = 0

        try:
            raw_rank = row.get('Global Rank', '0%')
            rank_value = clean_numeric_value(raw_rank.strip('%'), 0)
            global_rank = min(1.0, max(0.0, float(rank_value) / 100.0))
        except ValueError as e:
            logger.warning(f"Row {row_number}: Invalid Global Rank: {raw_rank}")
            global_rank = 0.0

        return {
            "search_term": (row.get('Search Term') or '').strip()[:100],
            "listennotes_url": validate_url(row.get('ListenNotes URL', '')) or '',
            "listen_score": listen_score,
            "global_rank": global_rank,
            "rss_feed": validated_url
        }, None

    except Exception as e:
        error_msg = f"Row {row_number}: {str(e)}"
        logger.error(error_msg)
        return None, error_msg

def summarize_validation_results(results):
    """Create a summary of validation results"""
    summary = {
        'total_rows': len(results['all_rows']),
        'valid_rows': len(results['valid_rows']),
        'invalid_rows': [],
        'error_types': {}
    }
    
    for row_num, error in results['errors']:
        summary['invalid_rows'].append((row_num, error))
        error_type = error.split(':')[0]
        summary['error_types'][error_type] = summary['error_types'].get(error_type, 0) + 1
        
    return summary

def compress_messages(podcasts, status):
    """Compress list of podcast names into a summary"""
    if not podcasts:
        return None
    count = len(podcasts)
    if count <= 3:
        names = ', '.join(podcasts)
    else:
        names = f"{', '.join(podcasts[:3])} and {count - 3} more"
    
    status_messages = {
        'new': f"Added {count} new podcasts: {names}",
        'updated': f"Updated {count} existing podcasts: {names}",
        'skipped': f"Skipped {count} podcasts",
        'error': f"Failed to process {count} podcasts"
    }
    return status_messages.get(status)

def validate_podcast_row(row):
    """Validate and clean podcast row data with enhanced error handling"""
    try:
        # Validate RSS Feed (required field)
        rss_feed = validate_url(row.get('RSS Feed', ''))
        if not rss_feed:
            logger.warning("Invalid or missing RSS feed URL")
            return None

        # Validate ListenNotes URL
        listennotes_url = validate_url(row.get('ListenNotes URL', ''))
        if not listennotes_url:
            listennotes_url = ''  # Optional field, can be empty

        # Clean listen score
        listen_score = 0
        raw_score = row.get('ListenScore', '0')
        if raw_score:
            try:
                listen_score = int(clean_numeric_value(raw_score, 0))
                listen_score = max(0, min(listen_score, 100))
            except ValueError:
                logger.warning(f"Invalid listen score format: {raw_score}, defaulting to 0")
                listen_score = 0

        # Clean global rank
        global_rank = 0.0
        raw_rank = row.get('Global Rank', '0%')
        if raw_rank:
            try:
                rank_value = clean_numeric_value(raw_rank.strip('%'), 0)
                global_rank = rank_value / 100.0
                global_rank = max(0.0, min(global_rank, 1.0))
            except ValueError:
                logger.warning(f"Invalid global rank format: {raw_rank}, defaulting to 0")
                global_rank = 0.0

        return {
            "search_term": (row.get('Search Term') or '').strip()[:100],
            "listennotes_url": listennotes_url[:255],
            "listen_score": listen_score,
            "global_rank": global_rank,
            "rss_feed": rss_feed[:255]
        }

    except Exception as e:
        logger.error(f"Error validating row data: {str(e)}")
        return None

def monitor_memory(func):
    """Decorator to monitor memory usage during function execution"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        process = psutil.Process()
        before_mem = process.memory_info().rss
        
        try:
            result = func(*args, **kwargs)
            
            after_mem = process.memory_info().rss
            memory_used = (after_mem - before_mem) / 1024 / 1024  # Convert to MB
            
            if memory_used > 500:  # Alert if using more than 500MB
                logger.warning(f"High memory usage detected in {func.__name__}: {memory_used:.2f}MB")
            
            return result
            
        except MemoryError:
            logger.error(f"Memory error in {func.__name__}")
            raise
            
    return wrapper

def chunked_iterable(iterable, size):
    """Helper function to chunk iterable into smaller pieces"""
    it = iter(iterable)
    while True:
        chunk = []
        try:
            for _ in range(size):
                chunk.append(next(it))
            yield chunk
        except StopIteration:
            if chunk:
                yield chunk
            break

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
    
def batch_check_existing_podcasts(supabase, rss_feeds):
    """Check for existing podcasts with valid RSS feeds"""
    try:
        # Filter out empty or invalid URLs
        valid_feeds = [feed for feed in rss_feeds if validate_url(feed)]
        
        if not valid_feeds:
            return {}
            
        # Query existing podcasts
        existing_podcasts = supabase.table('podcasts')\
            .select('*')\
            .in_('rss_feed', valid_feeds)\
            .execute()

        return {
            podcast['rss_feed']: podcast 
            for podcast in existing_podcasts.data
        }
    except Exception as e:
        logger.error(f"Error checking existing podcasts: {str(e)}")
        return {}    

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
    @monitor_memory
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
                            doc = None  # Clear document from memory
                        elif filename.endswith('.html'):
                            with open(filepath, 'r', encoding='utf-8') as f:
                                html_content = f.read()
                            transcription = extract_text_from_html(html_content)
                            html_content = None  # Clear HTML content from memory
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

                    # Clear variables from memory
                    transcription = None
                    embedding = None
                    embedding_list = None

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
    @monitor_memory
    def upload_podcast():
        processing_results = {
            'new': [],
            'updated': [],
            'skipped': [],
            'error': [],
            'invalid_urls': []
        }
        
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
                # Read and validate CSV data
                csv_data = file.read().decode('utf-8')
                csv_reader = csv.DictReader(StringIO(csv_data))
                rows = list(csv_reader)
                
                # Validate all rows first
                valid_rows = []
                for row in rows:
                    validated_data = validate_podcast_row(row)
                    if validated_data:
                        valid_rows.append(validated_data)
                    else:
                        rss_feed = row.get('RSS Feed', '')
                        if not validate_url(rss_feed):
                            processing_results['invalid_urls'].append(rss_feed)
                        else:
                            processing_results['error'].append(rss_feed)

                if not valid_rows:
                    flash("No valid podcast data found in CSV.")
                    return redirect(url_for('upload_combined'))

                # Process in chunks
                CHUNK_SIZE = 5
                for chunk in chunked_iterable(valid_rows, CHUNK_SIZE):
                    try:
                        # Get existing podcasts for this chunk
                        rss_feeds = [row['rss_feed'] for row in chunk]
                        existing_by_rss = batch_check_existing_podcasts(supabase, rss_feeds)

                        # Process each podcast in chunk
                        for validated_data in chunk:
                            try:
                                rss_feed = validated_data['rss_feed']
                                existing = existing_by_rss.get(rss_feed)

                                if existing:
                                    if existing['client_id'] == client_id:
                                        if existing['status'] != 'Done':
                                            process_podcast(existing, supabase)
                                            processing_results['updated'].append(existing['title'] or rss_feed)
                                        else:
                                            processing_results['skipped'].append(existing['title'] or rss_feed)
                                    continue

                                # Create new podcast
                                new_podcast = {
                                    "client_id": client_id,
                                    "search_term": validated_data["search_term"],
                                    "listennotes_url": validated_data["listennotes_url"],
                                    "listen_score": validated_data["listen_score"],
                                    "global_rank": validated_data["global_rank"],
                                    "rss_feed": validated_data["rss_feed"],
                                    "status": "New"
                                }

                                response = supabase.table('podcasts').insert(new_podcast).execute()
                                new_podcast_data = response.data[0]
                                
                                process_podcast(new_podcast_data, supabase)
                                processing_results['new'].append(new_podcast_data['title'] or rss_feed)

                            except Exception as e:
                                logger.error(f"Error processing podcast {rss_feed}: {str(e)}")
                                processing_results['error'].append(rss_feed)

                        # Memory cleanup after each chunk
                        gc.collect()
                        time.sleep(0.5)

                    except Exception as e:
                        logger.error(f"Error processing chunk: {str(e)}")
                        continue

                # Create summary messages
                messages = []
                
                if processing_results['invalid_urls']:
                    messages.append(f"Found {len(processing_results['invalid_urls'])} invalid RSS feed URLs")
                    
                if processing_results['new']:
                    messages.append(f"Added {len(processing_results['new'])} new podcasts")
                    
                if processing_results['updated']:
                    messages.append(f"Updated {len(processing_results['updated'])} existing podcasts")
                    
                if processing_results['skipped']:
                    messages.append(f"Skipped {len(processing_results['skipped'])} podcasts")
                    
                if processing_results['error']:
                    messages.append(f"Failed to process {len(processing_results['error'])} podcasts")

                # Flash messages individually to avoid cookie size issues
                for message in messages:
                    flash(message)

            return redirect(url_for('upload_combined'))

        except Exception as e:
            logger.error(f"Error in upload_podcast: {str(e)}")
            flash(f"Error processing podcasts: {str(e)}")
            return redirect(url_for('upload_combined'))

    @app.route('/match_podcasts')
    @monitor_memory
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

            # Get episodes for all valid podcasts in chunks
            episode_ids = [p['id'] for p in valid_podcasts]
            chunk_size = 50
            valid_episodes = []
            
            for i in range(0, len(episode_ids), chunk_size):
                chunk = episode_ids[i:i + chunk_size]
                episodes = supabase.table('episodes')\
                    .select('*')\
                    .in_('podcast_id', chunk)\
                    .execute()

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
                # Calculate guest fit score
                if podcast_episodes:
                    episode_embeddings = np.array([e['embedding'] for e in podcast_episodes])
                    episode_scores = cosine_similarity(client_embeddings, episode_embeddings)
                    guest_fit_score = float(episode_scores.mean()) * 100
                else:
                    guest_fit_score = 0.0

                # Clear episode data from memory
                episode_embeddings = None
                episode_scores = None

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

                # Clear variables from memory
                relevance_scores = None
                podcast_episodes = None

            # Sort by aggregate score
            final_scores.sort(key=lambda x: x["aggregate_score"], reverse=True)
            
            # Clear remaining large objects from memory
            client_embeddings = None
            podcast_embeddings = None
            valid_episodes = None
            valid_podcasts = None
            
            return jsonify(final_scores)
        
        except Exception as e:
            logger.error(f"Error in match_podcasts: {str(e)}")
            return jsonify({"error": f"An error occurred during matching: {str(e)}"}), 500

    @app.route('/get_podcast_stats')
    @monitor_memory
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

    @app.route('/export_matches')
    @monitor_memory
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

            # Write data in chunks
            chunk_size = 100
            for i in range(0, len(matches.data), chunk_size):
                chunk = matches.data[i:i + chunk_size]
                for match in chunk:
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

    return app