# matching.py
import numpy as np
from datetime import datetime
from sklearn.metrics.pairwise import cosine_similarity
import logging

logger = logging.getLogger(__name__)

def calculate_relevance_score(client_embeddings, podcast_embedding, podcast_categories):
    try:
        # Base similarity score
        similarity = cosine_similarity([podcast_embedding], client_embeddings).mean()
        
        # Scale more strictly
        scaled_score = similarity * 150  # Reduce multiplier to make 100 harder to achieve
        
        # Add category weight
        if podcast_categories:
            categories = set(podcast_categories.lower().split(','))
            category_score = min(30, len(categories) * 10)  # Up to 30 points for categories
        else:
            category_score = 0
        
        final_score = min(100, scaled_score + category_score)
        return final_score

    except Exception as e:
        logger.error(f"Error calculating relevance score: {str(e)}")
        return 0.0

def calculate_guest_fit_score(client_embeddings, episode_embeddings):
    try:
        if not episode_embeddings or len(episode_embeddings) == 0:
            return 0.0

        # Calculate similarity scores for all episodes
        episode_scores = cosine_similarity(client_embeddings, episode_embeddings)
        
        # Take mean of top 3 episode scores
        top_scores = np.sort(episode_scores.mean(axis=0))[-3:]
        
        # Scale more strictly
        final_score = min(100, np.mean(top_scores) * 150)
        return final_score

    except Exception as e:
        logger.error(f"Error calculating guest fit score: {str(e)}")
        return 0.0

def calculate_recency_score(last_updated):
    try:
        if not last_updated:
            return 20.0

        last_update = datetime.strptime(last_updated, '%m-%d-%Y')
        days_difference = (datetime.now() - last_update).days
        
        if days_difference <= 7:
            base_score = 100.0
        elif days_difference <= 14:
            base_score = 85.0
        elif days_difference <= 30:
            base_score = 70.0
        elif days_difference <= 60:
            base_score = 55.0
        elif days_difference <= 90:
            base_score = 40.0
        else:
            base_score = 25.0

        return base_score
            
    except Exception as e:
        logger.error(f"Error calculating recency score: {str(e)}")
        return 20.0

def calculate_host_interest_score(global_rank, listen_score):
    try:
        # Base score from global rank
        if global_rank <= 0.1:    # Top 10%
            rank_score = 100.0
        elif global_rank <= 0.25:  # Top 25%
            rank_score = 85.0
        elif global_rank <= 0.5:   # Top 50%
            rank_score = 70.0
        elif global_rank <= 0.75:  # Top 75%
            rank_score = 55.0
        else:
            rank_score = 40.0
        
        # Consider listen score
        listen_score_weight = min(100, float(listen_score))
        
        # Weighted combination
        final_score = (rank_score * 0.7) + (listen_score_weight * 0.3)
        
        return final_score

    except Exception as e:
        logger.error(f"Error calculating host interest score: {str(e)}")
        return 0.0

def calculate_aggregate_score(scores, weights):
    try:
        aggregate = sum(score * weight for score, weight in zip(scores, weights.values()))
        return min(100, aggregate)
    except Exception as e:
        logger.error(f"Error calculating aggregate score: {str(e)}")
        return 0.0