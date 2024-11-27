import re
import pytz
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
import logging
from utils import create_embedding
import time

logger = logging.getLogger(__name__)

def new_york_time():
    new_york_timezone = pytz.timezone('America/New_York')
    current_time_in_new_york = datetime.now(new_york_timezone)
    formatted_time = current_time_in_new_york.strftime('%m-%d-%Y')
    return formatted_time

def sanitize_filename(filename):
    return re.sub(r'[\\/*?:"<>|]', "", filename)

def convert_date(date_str):
    try:
        date_str = date_str.replace('GMT', '+0000')
        date_obj = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %z")
        formatted_date = date_obj.strftime("%m/%d/%y")
        return formatted_date
    except Exception as e:
        logger.error(f"Error converting date {date_str}: {str(e)}")
        return datetime.now().strftime("%m/%d/%y")

def process_podcast(podcast, supabase):
    try:
        title = ''
        listennotes_url = f'ListenNotes URL: {podcast["listennotes_url"]}'
        contact_name = ''
        contact_email = ''
        description = ''
        last_5_episodes = []

        # Add retries for RSS feed fetching
        max_retries = 3
        retry_delay = 1  # seconds

        for attempt in range(max_retries):
            try:
                ua = UserAgent()
                user_agent = ua.random
                headers = {
                    "User-Agent": user_agent,
                    "Accept": "application/rss+xml"
                }

                res = requests.get(
                    url=podcast['rss_feed'], 
                    headers=headers,
                    timeout=30  # 30 second timeout
                )
                res.raise_for_status()
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                logger.warning(f"RSS fetch attempt {attempt + 1} failed: {str(e)}")
                time.sleep(retry_delay)
                continue

        soup = BeautifulSoup(res.text, 'xml')
        
        file_name = soup.find('title')
        if file_name:
            file_name = file_name.text
            file_name = sanitize_filename(file_name)
            title += file_name
        
        try:
            contact_name += soup.find('itunes:name').text
        except:
            pass
            
        try:
            contact_email += soup.find('itunes:email').text
        except:
            pass
            
        try:
            description += BeautifulSoup(soup.find('description').text, 'lxml').get_text(strip=True)
        except:
            pass

        items = soup.select('item')

        for item in items[:5]:
            episode_data = {}
            try:
                episode_data['Date'] = convert_date(item.find('pubDate').text)
            except:
                episode_data['Date'] = ''
                
            try:
                episode_data['Title'] = item.find('title').text
            except:
                episode_data['Title'] = ''
                
            try:
                episode_data['Description'] = BeautifulSoup(item.find('description').text, 'lxml').get_text(strip=True)
            except:
                episode_data['Description'] = ''
            
            last_5_episodes.append(episode_data)

        # Get categories
        categories = soup.find_all('itunes:category')
        category_texts = [category['text'] for category in categories if category.has_attr('text')]
        categories_str = ', '.join(category_texts[:3])

        # Create embedding for podcast description with retries
        podcast_embedding = None
        if description:
            podcast_embedding = create_embedding(description)
            if podcast_embedding is None:
                logger.warning(f"Failed to create embedding for podcast {podcast['id']}")

        # Update podcast in Supabase
        update_data = {
            "status": 'Done',
            "filename": file_name[:500] if file_name else '',
            "last_updated": new_york_time(),
            "title": title[:500],
            "description": description,
            "contact_name": contact_name[:255],
            "contact_email": contact_email[:255],
            "categories": categories_str[:500]
        }
        
        if podcast_embedding is not None:
            update_data["embedding"] = podcast_embedding

        supabase.table('podcasts').update(update_data).eq('id', podcast['id']).execute()

        # Add episodes with error handling for each
        for episode_data in last_5_episodes:
            try:
                # Create embedding for episode description
                episode_embedding = None
                if episode_data['Description']:
                    episode_embedding = create_embedding(episode_data['Description'])
                    if episode_embedding is None:
                        logger.warning(f"Failed to create embedding for episode of podcast {podcast['id']}")
                        continue

                episode_insert = {
                    "podcast_id": podcast['id'],
                    "client_id": podcast['client_id'],
                    "title": episode_data['Title'][:500],
                    "date": episode_data['Date'],
                    "description": episode_data['Description']
                }

                if episode_embedding is not None:
                    episode_insert["embedding"] = episode_embedding

                supabase.table('episodes').insert(episode_insert).execute()

            except Exception as e:
                logger.error(f"Error processing episode for podcast {podcast['id']}: {str(e)}")
                continue

        logger.info(f'Processed podcast: {title}')

    except Exception as e:
        logger.error(f'Error processing podcast {podcast["rss_feed"]}: {str(e)}')
        # Update status to error
        supabase.table('podcasts').update({
            "status": 'Error',
            "last_updated": new_york_time()
        }).eq('id', podcast['id']).execute()
        raise

def main():
    try:
        # Example usage or testing code here
        pass
    except Exception as e:
        logger.error(f"Error in main: {str(e)}")

if __name__ == "__main__":
    main()