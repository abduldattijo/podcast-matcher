import openai
import numpy as np
from datetime import datetime
import logging
from typing import Optional, List, Dict, Union
import re
import time
import backoff
from docx import Document
from bs4 import BeautifulSoup
import os

logger = logging.getLogger(__name__)

@backoff.on_exception(
    backoff.expo,
    (openai.error.Timeout, openai.error.APIError, openai.error.RateLimitError),
    max_tries=3,
    max_time=30
)
def create_embedding(text: str) -> Optional[List[float]]:
    """Create embedding with retries and chunking."""
    try:
        if not text:
            return None
            
        max_tokens = 4000
        chunk_size = max_tokens

        chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
        embeddings = []

        for chunk in chunks:
            try:
                response = openai.Embedding.create(
                    model="text-embedding-ada-002",
                    input=chunk,
                    timeout=10
                )
                embedding = response['data'][0]['embedding']
                embeddings.append(embedding)
                time.sleep(0.1)  # Rate limiting pause
            except Exception as e:
                logger.error(f"Chunk embedding error: {str(e)}")
                continue

        if not embeddings:
            return None

        combined_embedding = np.mean(embeddings, axis=0)
        return combined_embedding.tolist()
        
    except Exception as e:
        logger.error(f"Error creating embedding: {str(e)}")
        return None

def format_date(date_str: str) -> str:
    """Format date string consistently."""
    try:
        date_obj = datetime.strptime(date_str, '%m-%d-%Y')
        return date_obj.strftime('%Y-%m-%d')
    except Exception as e:
        logger.error(f"Error formatting date: {str(e)}")
        return date_str

def clean_filename(filename: str) -> str:
    """Clean filename for safe usage."""
    try:
        cleaned = re.sub(r'[\\/*?:"<>|]', "", filename)
        cleaned = cleaned.replace(' ', '_')
        return cleaned[:255]
    except Exception as e:
        logger.error(f"Error cleaning filename: {str(e)}")
        return filename

def format_percentage(value: Union[float, str, None]) -> str:
    """Format float as percentage string."""
    try:
        if value is None:
            return "0.0%"
        return f"{float(value):.1f}%"
    except (ValueError, TypeError) as e:
        logger.error(f"Error formatting percentage: {str(e)}")
        return "0.0%"

def calculate_recency_score(last_updated: Optional[str]) -> float:
    """Calculate recency score with error handling."""
    try:
        if not last_updated:
            return 20.0

        last_update = datetime.strptime(last_updated, '%m-%d-%Y')
        days_difference = (datetime.now() - last_update).days
        
        if days_difference <= 7:
            return 100.0
        elif days_difference <= 14:
            return 90.0
        elif days_difference <= 30:
            return 80.0
        elif days_difference <= 60:
            return 70.0
        elif days_difference <= 90:
            return 60.0
        else:
            return 40.0
    except Exception as e:
        logger.error(f"Error calculating recency score: {str(e)}")
        return 20.0

def generate_score_reason(podcast: Dict, relevance_score: float, audience_score: float, recency_score: float) -> str:
    """Generate reason for scores with error handling."""
    try:
        reasons = []
        
        if relevance_score >= 90:
            reasons.append("Exceptional content match")
        elif relevance_score >= 75:
            reasons.append("Strong content alignment")
        elif relevance_score >= 60:
            reasons.append("Good content fit")
        else:
            reasons.append("Moderate content relevance")
        
        if audience_score >= 90:
            reasons.append("Exceptional listener engagement")
        elif audience_score >= 75:
            reasons.append("Strong audience base")
        elif audience_score >= 60:
            reasons.append("Good listener base")
        else:
            reasons.append("Moderate audience reach")
        
        if recency_score >= 90:
            reasons.append("Very actively publishing")
        elif recency_score >= 75:
            reasons.append("Recently active")
        elif recency_score >= 60:
            reasons.append("Moderately active")
        else:
            reasons.append("Less recent activity")
        
        if podcast.get('categories'):
            reasons.append(f"Topics: {podcast['categories']}")
        
        return " | ".join(reasons)
    except Exception as e:
        logger.error(f"Error generating score reason: {str(e)}")
        return "Error generating reason"

def generate_mismatch_explanation(podcast: Dict, relevance_score: float, audience_score: float, recency_score: float) -> str:
    """Generate mismatch explanation with error handling."""
    try:
        mismatches = []
        
        if relevance_score < 60:
            mismatches.append("Content alignment could be stronger")
        
        if audience_score < 60:
            mismatches.append("Limited audience reach")
            
        if recency_score < 60:
            mismatches.append("Publishing frequency could be more consistent")
        
        if not podcast.get('categories'):
            mismatches.append("Podcast focus unclear")

        if not podcast.get('contact_email') and not podcast.get('contact_name'):
            mismatches.append("Contact information unavailable")
            
        return " | ".join(mismatches) if mismatches else "No significant concerns identified"
    except Exception as e:
        logger.error(f"Error generating mismatch explanation: {str(e)}")
        return "Error generating explanation"

def extract_text_content(file_path: str, file_type: str) -> Optional[str]:
    """Extract text content safely with error handling and timeouts."""
    try:
        if file_type == 'txt':
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except UnicodeDecodeError:
                with open(file_path, 'r', encoding='latin-1') as f:
                    return f.read()
        elif file_type == 'docx':
            try:
                doc = Document(file_path)
                return '\n'.join([paragraph.text for paragraph in doc.paragraphs])
            except Exception as e:
                logger.error(f"Error processing docx: {str(e)}")
                return None
        elif file_type == 'html':
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    soup = BeautifulSoup(f.read(), 'html.parser')
                    # Remove script and style elements
                    for script in soup(["script", "style"]):
                        script.decompose()
                    return soup.get_text(separator=' ', strip=True)
            except Exception as e:
                logger.error(f"Error processing html: {str(e)}")
                return None
        else:
            logger.warning(f"Unsupported file type: {file_type}")
            return None
    except Exception as e:
        logger.error(f"Error extracting text from {file_path}: {str(e)}")
        return None

def validate_file_type(filename: str) -> bool:
    """Validate if file type is supported."""
    allowed_extensions = {'txt', 'docx', 'html', 'csv'}
    try:
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions
    except Exception as e:
        logger.error(f"Error validating file type: {str(e)}")
        return False

def get_file_stats(file_path: str) -> Dict:
    """Get basic file statistics with error handling."""
    try:
        stats = os.stat(file_path)
        return {
            'size': stats.st_size,
            'created': datetime.fromtimestamp(stats.st_ctime).strftime('%Y-%m-%d %H:%M:%S'),
            'modified': datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        }
    except Exception as e:
        logger.error(f"Error getting file stats: {str(e)}")
        return {}

# Export all functions
__all__ = [
    'create_embedding',
    'format_date',
    'clean_filename',
    'format_percentage',
    'calculate_recency_score',
    'generate_score_reason',
    'generate_mismatch_explanation',
    'extract_text_content',
    'validate_file_type',
    'get_file_stats'
]