import re
import pytz
import requests
import gc
from datetime import datetime
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
import logging
from utils import create_embedding
import time
import psutil
from config import Config

logger = logging.getLogger(__name__)

def monitor_memory(func):
    """Decorator to monitor memory usage during function execution"""
    def wrapper(*args, **kwargs):
        process = psutil.Process()
        before_mem = process.memory_info().rss
        
        try:
            result = func(*args, **kwargs)
            
            after_mem = process.memory_info().rss
            memory_used = (after_mem - before_mem) / 1024 / 1024  # Convert to MB
            
            if memory_used > Config.MEMORY_ALERT_THRESHOLD:
                logger.warning(f"High memory usage detected in {func.__name__}: {memory_used:.2f}MB")
            
            return result
            
        except MemoryError:
            logger.error(f"Memory error in {func.__name__}")
            raise
            
    return wrapper

def new_york_time():
    """Get current time in New York timezone"""
    new_york_timezone = pytz.timezone('America/New_York')
    current_time_in_new_york = datetime.now(new_york_timezone)
    formatted_time = current_time_in_new_york.strftime('%m-%d-%Y')
    return formatted_time

def sanitize_filename(filename):
    """Remove invalid characters from filename"""
    if not filename:
        return ""
    # Remove invalid characters and limit length
    sanitized = re.sub(r'[\\/*?:"<>|]', "", filename)
    return sanitized[:255]  # Limit length to 255 characters

def convert_date(date_str):
    """Convert date string to standard format"""
    try:
        if not date_str:
            return None
        date_str = date_str.replace('GMT', '+0000')
        date_obj = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %z")
        formatted_date = date_obj.strftime("%m/%d/%y")
        return formatted_date
    except Exception as e:
        logger.error(f"Error converting date: {str(e)}")
        return None

def process_description(description_text, max_length=3000):
    """Process and truncate description text to prevent memory issues"""
    if not description_text:
        return ""
    
    try:
        # Use lxml parser for better memory efficiency
        soup = BeautifulSoup(description_text, 'lxml')
        clean_text = soup.get_text(strip=True)
        soup.decompose()  # Clear the soup object
        
        # Truncate if too long
        if len(clean_text) > max_length:
            clean_text = clean_text[:max_length] + "..."
        
        return clean_text
    except Exception as e:
        logger.error(f"Error processing description: {str(e)}")
        return ""

def stream_rss_content(url, chunk_size=1000):
    """Stream RSS feed content in chunks to manage memory"""
    ua = UserAgent()
    headers = {"User-Agent": ua.random}
    
    try:
        with requests.get(url, headers=headers, stream=True, timeout=Config.RSS_FETCH_TIMEOUT) as response:
            response.raise_for_status()
            content = []
            for chunk in response.iter_content(chunk_size=chunk_size, decode_unicode=True):
                if chunk:
                    content.append(chunk)
            return ''.join(content)
    except requests.RequestException as e:
        logger.error(f"Error streaming RSS content: {str(e)}")
        raise

def process_episodes(items, max_episodes=5):
    """Process podcast episodes with memory optimization"""
    episodes = []
    for item in items[:max_episodes]:
        try:
            episode = {
                'title': item.find('title').text[:500] if item.find('title') else '',
                'date': convert_date(item.find('pubDate').text) if item.find('pubDate') else '',
                'description': process_description(
                    item.find('description').text, 
                    max_length=2000
                ) if item.find('description') else ''
            }
            episodes.append(episode)
        except Exception as e:
            logger.error(f"Error processing episode: {str(e)}")
        finally:
            item.decompose()  # Clear processed item
    
    return episodes

@monitor_memory
def process_podcast(podcast, supabase):
    """Process podcast data with enhanced memory optimization"""
    try:
        result = {
            'title': '',
            'contact_name': '',
            'contact_email': '',
            'description': '',
            'categories': []
        }

        # Stream and process RSS content
        try:
            for attempt in range(Config.RSS_MAX_RETRIES):
                try:
                    rss_content = stream_rss_content(podcast['rss_feed'])
                    break
                except requests.RequestException as e:
                    if attempt == Config.RSS_MAX_RETRIES - 1:
                        raise
                    time.sleep(2 ** attempt)  # Exponential backoff

            # Use lxml parser for better memory efficiency
            soup = BeautifulSoup(rss_content, 'lxml-xml')
            rss_content = None  # Clear raw content
            gc.collect()

            # Extract basic metadata
            if title_elem := soup.find('title'):
                result['title'] = sanitize_filename(title_elem.text)

            if name_elem := soup.find('itunes:name'):
                result['contact_name'] = name_elem.text[:255]

            if email_elem := soup.find('itunes:email'):
                result['contact_email'] = email_elem.text[:255]

            if desc_elem := soup.find('description'):
                result['description'] = process_description(desc_elem.text)

            # Process categories
            categories = soup.find_all('itunes:category')
            result['categories'] = [cat.get('text', '') for cat in categories[:3] if cat.has_attr('text')]

            # Process episodes
            all_items = soup.find_all('item')
            episodes = process_episodes(all_items, max_episodes=Config.MAX_EPISODES)

            # Clear soup to free memory
            soup.decompose()
            gc.collect()

            # Create podcast embedding
            podcast_embedding = None
            if result['description']:
                podcast_embedding = create_embedding(result['description'])
                time.sleep(0.5)  # Rate limiting for API calls

            # Update podcast record
            podcast_update = {
                "status": 'Done',
                "filename": result['title'][:500],
                "last_updated": new_york_time(),
                "title": result['title'][:500],
                "description": result['description'],
                "contact_name": result['contact_name'],
                "contact_email": result['contact_email'],
                "categories": ', '.join(result['categories'])[:500],
                "embedding": podcast_embedding
            }

            # Update podcast first
            supabase.table('podcasts').update(podcast_update).eq('id', podcast['id']).execute()

            # Process episodes in smaller batches
            batch_size = 2
            for i in range(0, len(episodes), batch_size):
                batch = episodes[i:i + batch_size]
                for episode in batch:
                    try:
                        # Create embedding for episode
                        episode_embedding = None
                        if episode['description']:
                            episode_embedding = create_embedding(episode['description'])
                            time.sleep(0.5)  # Rate limiting for API calls

                        episode_record = {
                            "podcast_id": podcast['id'],
                            "client_id": podcast['client_id'],
                            "title": episode['title'],
                            "date": episode['date'],
                            "description": episode['description'],
                            "embedding": episode_embedding
                        }

                        supabase.table('episodes').insert(episode_record).execute()
                    except Exception as e:
                        logger.error(f"Error processing episode batch: {str(e)}")
                    finally:
                        episode_embedding = None
                        gc.collect()

                # Small delay between batches
                time.sleep(0.5)

            logger.info(f'Successfully processed podcast: {result["title"]}')

        except requests.RequestException as e:
            logger.error(f"Error fetching RSS feed: {str(e)}")
            raise

    except Exception as e:
        logger.error(f'Error processing podcast {podcast["rss_feed"]}: {str(e)}')
        raise

    finally:
        # Final cleanup
        result = None
        episodes = None
        podcast_embedding = None
        gc.collect()

def main():
    """Main function for testing"""
    try:
        logger.info("Starting podcast processing...")
        
        # Monitor initial memory usage
        process = psutil.Process()
        initial_memory = process.memory_info().rss / 1024 / 1024
        logger.info(f"Initial memory usage: {initial_memory:.2f}MB")
        
        # Add any test code here
        
        # Monitor final memory usage
        final_memory = process.memory_info().rss / 1024 / 1024
        logger.info(f"Final memory usage: {final_memory:.2f}MB")
        logger.info(f"Memory difference: {final_memory - initial_memory:.2f}MB")
        
        logger.info("Podcast processing completed")
        
    except Exception as e:
        logger.error(f"Error in main: {str(e)}")
    finally:
        gc.collect()

if __name__ == "__main__":
    main()