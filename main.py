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
            
            if memory_used > 500:  # Alert if using more than 500MB
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
    return re.sub(r'[\\/*?:"<>|]', "", filename)

def convert_date(date_str):
    """Convert date string to standard format"""
    try:
        date_str = date_str.replace('GMT', '+0000')
        date_obj = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %z")
        formatted_date = date_obj.strftime("%m/%d/%y")
        return formatted_date
    except Exception as e:
        logger.error(f"Error converting date: {str(e)}")
        return None

def process_description(description_text, max_length=5000):
    """Process and truncate description text to prevent memory issues"""
    if not description_text:
        return ""
    
    # Clean the text
    try:
        clean_text = BeautifulSoup(description_text, 'lxml').get_text(strip=True)
        # Truncate if too long
        if len(clean_text) > max_length:
            clean_text = clean_text[:max_length] + "..."
        return clean_text
    except Exception as e:
        logger.error(f"Error processing description: {str(e)}")
        return ""

def get_rss_feed_content(url, max_retries=3, timeout=30):
    """Get RSS feed content with retry logic and timeout"""
    ua = UserAgent()
    headers = {"User-Agent": ua.random}
    
    for attempt in range(max_retries):
        try:
            response = requests.get(url=url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            if attempt == max_retries - 1:
                logger.error(f"Failed to fetch RSS feed after {max_retries} attempts: {str(e)}")
                raise
            time.sleep(2 ** attempt)  # Exponential backoff

@monitor_memory
def process_podcast(podcast, supabase):
    """Process podcast data with memory optimization"""
    try:
        title = ''
        listennotes_url = f'ListenNotes URL: {podcast["listennotes_url"]}'
        contact_name = ''
        contact_email = ''
        description = ''
        last_5_episodes = []
        categories_str = ''

        # Fetch RSS feed content
        rss_content = get_rss_feed_content(podcast['rss_feed'])
        
        # Parse RSS feed
        soup = BeautifulSoup(rss_content, 'xml')
        
        # Get title
        title_element = soup.find('title')
        if title_element:
            file_name = sanitize_filename(title_element.text)
            title = file_name
        
        # Get contact info
        try:
            contact_name_elem = soup.find('itunes:name')
            if contact_name_elem:
                contact_name = contact_name_elem.text
        except Exception as e:
            logger.warning(f"Error getting contact name: {str(e)}")
            
        try:
            contact_email_elem = soup.find('itunes:email')
            if contact_email_elem:
                contact_email = contact_email_elem.text
        except Exception as e:
            logger.warning(f"Error getting contact email: {str(e)}")
            
        # Get description
        try:
            description_elem = soup.find('description')
            if description_elem:
                description = process_description(description_elem.text)
        except Exception as e:
            logger.warning(f"Error getting description: {str(e)}")

        # Process episodes
        items = soup.select('item')
        for item in items[:5]:  # Only process last 5 episodes
            episode_data = {}
            try:
                pub_date = item.find('pubDate')
                if pub_date:
                    episode_data['Date'] = convert_date(pub_date.text)
                else:
                    episode_data['Date'] = ''
            except Exception as e:
                logger.warning(f"Error processing episode date: {str(e)}")
                episode_data['Date'] = ''
                
            try:
                episode_title = item.find('title')
                if episode_title:
                    episode_data['Title'] = episode_title.text
                else:
                    episode_data['Title'] = ''
            except Exception as e:
                logger.warning(f"Error processing episode title: {str(e)}")
                episode_data['Title'] = ''
                
            try:
                episode_desc = item.find('description')
                if episode_desc:
                    episode_data['Description'] = process_description(episode_desc.text)
                else:
                    episode_data['Description'] = ''
            except Exception as e:
                logger.warning(f"Error processing episode description: {str(e)}")
                episode_data['Description'] = ''
            
            last_5_episodes.append(episode_data)

        # Get categories
        categories = soup.find_all('itunes:category')
        category_texts = [category.get('text', '') for category in categories if category.has_attr('text')]
        categories_str = ', '.join(category_texts[:3])  # Limit to top 3 categories

        # Create embedding for podcast description
        podcast_embedding = None
        if description:
            podcast_embedding = create_embedding(description)

        # Clear BeautifulSoup object to free memory
        soup.decompose()
        gc.collect()

        # Update podcast in Supabase
        podcast_update = {
            "status": 'Done',
            "filename": file_name[:500] if file_name else '',
            "last_updated": new_york_time(),
            "title": title[:500],
            "description": description,
            "contact_name": contact_name[:255],
            "contact_email": contact_email[:255],
            "categories": categories_str[:500],
            "embedding": podcast_embedding
        }

        supabase.table('podcasts').update(podcast_update).eq('id', podcast['id']).execute()

        # Add episodes with batch processing
        for episode_data in last_5_episodes:
            # Create embedding for episode description
            episode_embedding = None
            if episode_data['Description']:
                episode_embedding = create_embedding(episode_data['Description'])
            
            episode_record = {
                "podcast_id": podcast['id'],
                "client_id": podcast['client_id'],
                "title": episode_data['Title'][:500],
                "date": episode_data['Date'],
                "description": episode_data['Description'],
                "embedding": episode_embedding
            }
            
            supabase.table('episodes').insert(episode_record).execute()
            
            # Clear episode embedding from memory
            episode_embedding = None
        
        # Clear all large variables
        description = None
        last_5_episodes = None
        podcast_embedding = None
        gc.collect()

        logger.info(f'Successfully processed podcast: {title}')

    except Exception as e:
        logger.error(f'Error processing podcast {podcast["rss_feed"]}: {str(e)}')
        raise

def main():
    """Main function for testing"""
    try:
        logger.info("Starting podcast processing...")
        # Add any test code here
        logger.info("Podcast processing completed")
    except Exception as e:
        logger.error(f"Error in main: {str(e)}")

if __name__ == "__main__":
    main()