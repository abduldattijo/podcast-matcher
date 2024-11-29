import openai
import numpy as np
from datetime import datetime
import logging
from typing import Optional, List, Dict, Union
import re
# Add to utils.py
import psutil
import gc
import torch
logger = logging.getLogger(__name__)




def log_memory_usage():
    process = psutil.Process()
    logger.info(f"Memory usage: {process.memory_info().rss / 1024 / 1024:.2f} MB")
    
def cleanup_embeddings():
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()    

def create_embedding(text: str) -> Optional[List[float]]:
    """
    Create embedding for text using OpenAI's API with proper chunking for long texts.
    
    Args:
        text (str): The text to create an embedding for
        
    Returns:
        Optional[List[float]]: The embedding vector or None if there's an error
    """
    try:
        max_tokens = 8000
        chunk_size = max_tokens

        # Split text into chunks if it's too long
        chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]

        embeddings = []
        for chunk in chunks:
            response = openai.Embedding.create(
                model="text-embedding-ada-002",
                input=chunk
            )
            embedding = response['data'][0]['embedding']
            embeddings.append(embedding)

        # Combine chunk embeddings by taking their mean
        combined_embedding = np.mean(embeddings, axis=0)

        return combined_embedding.tolist()
    except Exception as e:
        logger.error(f"Error creating embedding: {str(e)}")
        return None

def format_date(date_str: str) -> str:
    """
    Format date string consistently.
    
    Args:
        date_str (str): Date string in mm-dd-yyyy format
        
    Returns:
        str: Formatted date string in yyyy-mm-dd format
    """
    try:
        date_obj = datetime.strptime(date_str, '%m-%d-%Y')
        return date_obj.strftime('%Y-%m-%d')
    except Exception as e:
        logger.error(f"Error formatting date: {str(e)}")
        return date_str

def clean_filename(filename: str) -> str:
    """
    Clean filename for safe usage.
    
    Args:
        filename (str): Original filename
        
    Returns:
        str: Cleaned filename
    """
    # Remove invalid characters
    cleaned = re.sub(r'[\\/*?:"<>|]', "", filename)
    # Replace spaces with underscores
    cleaned = cleaned.replace(' ', '_')
    # Ensure filename is not too long
    return cleaned[:255]

def format_percentage(value: Union[float, str, None]) -> str:
    """
    Format float as percentage string.
    
    Args:
        value (Union[float, str, None]): Number to format
        
    Returns:
        str: Formatted percentage string
    """
    try:
        if value is None:
            return "0.0%"
        return f"{float(value):.1f}%"
    except (ValueError, TypeError):
        return "0.0%"

def calculate_recency_score(last_updated: Optional[str]) -> float:
    """
    Calculate recency score based on last update date.
    
    Args:
        last_updated (Optional[str]): Last update date string
        
    Returns:
        float: Recency score from 0 to 100
    """
    try:
        if not last_updated:
            return 20.0

        last_update = datetime.strptime(last_updated, '%m-%d-%Y')
        days_difference = (datetime.now() - last_update).days
        
        if days_difference <= 7:       # Within week
            return 100.0
        elif days_difference <= 14:    # Within 2 weeks
            return 90.0
        elif days_difference <= 30:    # Within month
            return 80.0
        elif days_difference <= 60:    # Within 2 months
            return 70.0
        elif days_difference <= 90:    # Within 3 months
            return 60.0
        else:
            return 40.0
    except Exception as e:
        logger.error(f"Error calculating recency score: {str(e)}")
        return 20.0

def generate_score_reason(podcast: Dict, relevance_score: float, audience_score: float, recency_score: float) -> str:
    """
    Generate explanation for podcast scores.
    
    Args:
        podcast (Dict): Podcast data
        relevance_score (float): Content relevance score
        audience_score (float): Audience score
        recency_score (float): Recency score
        
    Returns:
        str: Detailed explanation of scores
    """
    reasons = []
    
    # Content relevance explanation
    if relevance_score >= 90:
        reasons.append("Exceptional content match")
    elif relevance_score >= 75:
        reasons.append("Strong content alignment")
    elif relevance_score >= 60:
        reasons.append("Good content fit")
    else:
        reasons.append("Moderate content relevance")
    
    # Audience explanation
    if audience_score >= 90:
        reasons.append("Exceptional listener engagement")
    elif audience_score >= 75:
        reasons.append("Strong audience base")
    elif audience_score >= 60:
        reasons.append("Good listener base")
    else:
        reasons.append("Moderate audience reach")
    
    # Recency explanation
    if recency_score >= 90:
        reasons.append("Very actively publishing")
    elif recency_score >= 75:
        reasons.append("Recently active")
    elif recency_score >= 60:
        reasons.append("Moderately active")
    else:
        reasons.append("Less recent activity")
    
    # Add categories if available
    if podcast.get('categories'):
        reasons.append(f"Topics: {podcast['categories']}")
    
    return " | ".join(reasons)

def generate_mismatch_explanation(podcast: Dict, relevance_score: float, audience_score: float, recency_score: float) -> str:
    """
    Generate explanation for potential mismatches.
    
    Args:
        podcast (Dict): Podcast data
        relevance_score (float): Content relevance score
        audience_score (float): Audience score
        recency_score (float): Recency score
        
    Returns:
        str: Explanation of potential mismatches
    """
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

def extract_text_content(file_path: str, file_type: str) -> Optional[str]:
    """
    Extract text content from various file types.
    
    Args:
        file_path (str): Path to the file
        file_type (str): Type of file ('txt', 'docx', 'html')
        
    Returns:
        Optional[str]: Extracted text content or None if extraction fails
    """
    try:
        if file_type == 'txt':
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        elif file_type == 'docx':
            from docx import Document
            doc = Document(file_path)
            return '\n'.join([paragraph.text for paragraph in doc.paragraphs])
        elif file_type == 'html':
            from bs4 import BeautifulSoup
            with open(file_path, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f.read(), 'html.parser')
                # Remove script and style elements
                for script in soup(["script", "style"]):
                    script.decompose()
                return soup.get_text()
        else:
            logger.warning(f"Unsupported file type: {file_type}")
            return None
    except Exception as e:
        logger.error(f"Error extracting text from {file_path}: {str(e)}")
        return None

def validate_file_type(filename: str) -> bool:
    """
    Validate if file type is supported.
    
    Args:
        filename (str): Name of the file
        
    Returns:
        bool: True if file type is supported, False otherwise
    """
    allowed_extensions = {'txt', 'docx', 'html', 'csv'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

def get_file_stats(file_path: str) -> Dict:
    """
    Get basic file statistics.
    
    Args:
        file_path (str): Path to the file
        
    Returns:
        Dict: Dictionary containing file statistics
    """
    try:
        import os
        stats = os.stat(file_path)
        return {
            'size': stats.st_size,
            'created': datetime.fromtimestamp(stats.st_ctime).strftime('%Y-%m-%d %H:%M:%S'),
            'modified': datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        }
    except Exception as e:
        logger.error(f"Error getting file stats: {str(e)}")
        return {}

# Export all functions for use in other modules
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