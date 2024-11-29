import openai
import numpy as np
from datetime import datetime
import logging


logger = logging.getLogger(__name__)

def create_embedding(text):
    try:
        max_tokens = 8000
        chunk_size = max_tokens

        chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]

        embeddings = []
        for chunk in chunks:
            response = openai.Embedding.create(
                model="text-embedding-ada-002",
                input=chunk
            )
            embedding = response['data'][0]['embedding']
            embeddings.append(embedding)

        combined_embedding = np.mean(embeddings, axis=0)

        return combined_embedding.tolist()
    except Exception as e:
        logger.error(f"Error creating embedding: {str(e)}")
        return None

def generate_score_reason(podcast, relevance_score, audience_score, recency_score):
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
    
    if podcast.categories:
        reasons.append(f"Topics: {podcast.categories}")
    
    return " | ".join(reasons)

def generate_mismatch_explanation(podcast, relevance_score, audience_score, recency_score):
    mismatches = []
    
    if relevance_score < 60:
        mismatches.append("Content alignment could be stronger")
    
    if audience_score < 60:
        mismatches.append("Limited audience reach")
        
    if recency_score < 60:
        mismatches.append("Publishing frequency could be more consistent")
    
    if not podcast.categories:
        mismatches.append("Podcast focus unclear")
        
    return " | ".join(mismatches) if mismatches else "No significant concerns identified"

def calculate_recency_score(last_updated):
    try:
        if last_updated:
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
        return 20.0
    except Exception as e:
        logger.error(f"Error calculating recency score: {str(e)}")
        return 20.0