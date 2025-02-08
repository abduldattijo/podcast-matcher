# app.py
import streamlit as st
import os
import logging
import openai
import psutil
import gc
import time
from dotenv import load_dotenv
from database import supabase
from datetime import datetime
from werkzeug.utils import secure_filename
import pandas as pd
from utils import (
    create_embedding,
    extract_text_content,
    calculate_recency_score,
    generate_score_reason,
    generate_mismatch_explanation
)
from matching import (
    calculate_relevance_score,
    calculate_guest_fit_score
)

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
    log_memory_usage()

def init_app():
    """Initialize application settings and verify connections."""
    try:
        # Set OpenAI API key
        openai.api_key = os.getenv("OPENAI_API_KEY")
        if not openai.api_key:
            st.error("OpenAI API key not found in environment variables")
            raise ValueError("OpenAI API key not configured")

        # Verify Supabase connection
        response = supabase.table('clients').select("*").limit(1).execute()
        logger.info("Successfully connected to Supabase")
        
        log_memory_usage()
        return True

    except Exception as e:
        logger.error(f"Error initializing application: {str(e)}")
        st.error(f"Error initializing application: {str(e)}")
        return False

def upload_page():
    st.title("Upload Data")
    
    try:
        # Get clients
        response = supabase.table('clients').select('*').execute()
        clients = response.data
        
        # Client selection
        col1, col2 = st.columns([2, 1])
        with col1:
            client_options = ["New Client"] + [client['name'] for client in clients]
            client_choice = st.selectbox("Select Client", client_options)
            
        if client_choice == "New Client":
            with col2:
                new_client_name = st.text_input("New Client Name")
                if new_client_name and st.button("Create Client"):
                    response = supabase.table('clients').insert({"name": new_client_name}).execute()
                    st.success(f"Created new client: {new_client_name}")
                    st.session_state.client_id = response.data[0]['id']
                    time.sleep(1)
                    st.rerun()
        else:
            st.session_state.client_id = next(
                client['id'] for client in clients 
                if client['name'] == client_choice
            )
        
        # File Upload Sections
        st.subheader("Upload Client Files")
        client_files = st.file_uploader(
            "Upload client documents (txt, docx, html)",
            type=['txt', 'docx', 'html'],
            accept_multiple_files=True
        )
        
        if client_files:
            if st.button("Process Client Files"):
                with st.spinner("Processing client files..."):
                    for file in client_files:
                        try:
                            content = extract_text_content(file.read(), file.name.split('.')[-1])
                            if content:
                                embedding = create_embedding(content)
                                if embedding:
                                    supabase.table('client_data').insert({
                                        "client_id": st.session_state.client_id,
                                        "filename": secure_filename(file.name),
                                        "transcription": content,
                                        "embedding": embedding
                                    }).execute()
                                    st.success(f"Processed {file.name}")
                                else:
                                    st.warning(f"Could not create embedding for {file.name}")
                            else:
                                st.warning(f"Could not extract content from {file.name}")
                        except Exception as e:
                            st.error(f"Error processing {file.name}: {str(e)}")
                            logger.error(f"File processing error: {str(e)}")
                            
        st.subheader("Upload Podcast Data")
        podcast_file = st.file_uploader(
            "Upload podcast CSV file",
            type=['csv']
        )
        
        if podcast_file:
            if st.button("Process Podcast Data"):
                with st.spinner("Processing podcast data..."):
                    try:
                        df = pd.read_csv(podcast_file)
                        for _, row in df.iterrows():
                            try:
                                podcast_data = {
                                    "client_id": st.session_state.client_id,
                                    "search_term": row['Search Term'][:100],
                                    "listennotes_url": row['ListenNotes URL'][:255],
                                    "listen_score": int(row['ListenScore']),
                                    "global_rank": float(row['Global Rank'].strip('%')) / 100,
                                    "rss_feed": row['RSS Feed'][:255],
                                    "status": "New"
                                }
                                supabase.table('podcasts').insert(podcast_data).execute()
                            except Exception as e:
                                logger.error(f"Error processing podcast row: {str(e)}")
                                continue
                        st.success("Podcast data processed successfully")
                    except Exception as e:
                        st.error(f"Error processing podcast file: {str(e)}")
                        logger.error(f"Podcast file processing error: {str(e)}")
                        
    except Exception as e:
        st.error(f"Error: {str(e)}")
        logger.error(f"Upload page error: {str(e)}")

def match_page():
    st.title("Match Podcasts")
    
    try:
        # Get clients
        response = supabase.table('clients').select('*').execute()
        clients = response.data
        
        # Client selection
        client_options = [client['name'] for client in clients]
        client_choice = st.selectbox("Select Client", client_options)
        client_id = next(
            client['id'] for client in clients 
            if client['name'] == client_choice
        )
        
        # Matching controls
        col1, col2, col3 = st.columns(3)
        with col1:
            min_score = st.slider("Minimum Listen Score", 0, 100, 20)
        with col2:
            max_score = st.slider("Maximum Listen Score", 0, 100, 100)
        with col3:
            include_blank = st.checkbox("Include podcasts without scores")
            
        if st.button("Find Matches"):
            with st.spinner("Finding matches..."):
                # Get client embeddings
                client_data = supabase.table('client_data')\
                    .select('embedding')\
                    .eq('client_id', client_id)\
                    .execute()
                    
                client_embeddings = [
                    eval(data['embedding']) 
                    for data in client_data.data 
                    if data.get('embedding')
                ]
                
                if not client_embeddings:
                    st.warning("No client data found for matching")
                    return
                
                # Get and process podcasts
                podcasts = supabase.table('podcasts')\
                    .select('*')\
                    .eq('client_id', client_id)\
                    .execute()
                
                results = []
                for podcast in podcasts.data:
                    try:
                        if not podcast.get('embedding'):
                            continue
                            
                        embedding = eval(podcast['embedding'])
                        
                        # Calculate scores
                        relevance_score = calculate_relevance_score(
                            client_embeddings, 
                            embedding,
                            podcast.get('categories', '')
                        )
                        
                        listen_score = float(podcast['listen_score']) if podcast.get('listen_score') else 0.0
                        recency_score = calculate_recency_score(podcast.get('last_updated'))
                        host_interest_score = 100.0 * (1 - podcast['global_rank'])
                        
                        # Get episode embeddings
                        episodes = supabase.table('episodes')\
                            .select('embedding')\
                            .eq('podcast_id', podcast['id'])\
                            .execute()
                            
                        episode_embeddings = [
                            eval(ep['embedding']) 
                            for ep in episodes.data 
                            if ep.get('embedding')
                        ]
                        
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
                            listen_score * weights['audience'] +
                            guest_fit_score * weights['guest_fit'] +
                            recency_score * weights['recency'] +
                            host_interest_score * weights['host_interest']
                        )
                        
                        results.append({
                            "podcast_name": podcast['title'] or f"Podcast {podcast['id']}",
                            "relevance_score": round(relevance_score, 1),
                            "audience_score": round(listen_score, 1),
                            "guest_fit_score": round(guest_fit_score, 1),
                            "recency_score": round(recency_score, 1),
                            "host_interest_score": round(host_interest_score, 1),
                            "aggregate_score": round(aggregate_score, 1),
                            "reason": generate_score_reason(
                                podcast, 
                                relevance_score, 
                                listen_score, 
                                recency_score
                            ),
                            "potential_mismatch": generate_mismatch_explanation(
                                podcast, 
                                relevance_score, 
                                listen_score, 
                                recency_score
                            )
                        })
                        
                    except Exception as e:
                        logger.error(f"Error processing podcast {podcast.get('id')}: {str(e)}")
                        continue
                
                # Display results
                if results:
                    results.sort(key=lambda x: x["aggregate_score"], reverse=True)
                    st.subheader("Match Results")
                    
                    for result in results:
                        with st.expander(f"{result['podcast_name']} - Score: {result['aggregate_score']}"):
                            col1, col2 = st.columns(2)
                            with col1:
                                st.write("Scores:")
                                st.write(f"- Relevance: {result['relevance_score']}")
                                st.write(f"- Audience: {result['audience_score']}")
                                st.write(f"- Guest Fit: {result['guest_fit_score']}")
                                st.write(f"- Recency: {result['recency_score']}")
                                st.write(f"- Host Interest: {result['host_interest_score']}")
                            with col2:
                                st.write("Analysis:")
                                st.write(result['reason'])
                                if result['potential_mismatch']:
                                    st.warning(result['potential_mismatch'])
                else:
                    st.warning("No matches found with current criteria")
                    
    except Exception as e:
        st.error(f"Error: {str(e)}")
        logger.error(f"Match page error: {str(e)}")

def main():
    st.set_page_config(
        page_title="Podcast Matcher",
        page_icon="🎙️",
        layout="wide"
    )
    
    # Initialize session state
    if 'client_id' not in st.session_state:
        st.session_state.client_id = None
        
    # Initialize app
    if not init_app():
        return
        
    # Navigation
    pages = {
        "Upload Data": upload_page,
        "Match Podcasts": match_page
    }
    
    # Sidebar navigation
    st.sidebar.title("Navigation")
    selection = st.sidebar.radio("Go to", list(pages.keys()))
    
    # Display selected page
    pages[selection]()

if __name__ == '__main__':
    main()