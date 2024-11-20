import re
import pytz
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from utils import create_embedding
import logging

logger = logging.getLogger(__name__)

def new_york_time():
    new_york_timezone = pytz.timezone('America/New_York')
    current_time_in_new_york = datetime.now(new_york_timezone)
    formatted_time = current_time_in_new_york.strftime('%m-%d-%Y')
    return formatted_time

def sanitize_filename(filename):
    return re.sub(r'[\\/*?:"<>|]', "", filename)

def convert_date(date_str):
    date_str = date_str.replace('GMT', '+0000')
    date_obj = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %z")
    formatted_date = date_obj.strftime("%m/%d/%y")
    return formatted_date

def process_podcast(podcast, db, Episode):
    try:
        title = ''
        listennotes_url = f'ListenNotes URL: {podcast.listennotes_url}'
        contact_name = ''
        contact_email = ''
        description = ''
        last_5_episodes = []

        ua = UserAgent()
        user_agent = ua.random
        headers = {
            "User-Agent": user_agent
        }

        res = requests.get(url=podcast.rss_feed, headers=headers)
        soup = BeautifulSoup(res.text, 'xml')
        
        file_name = soup.find('title').text
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

        # Update podcast information
        podcast.status = 'Done'
        podcast.filename = file_name[:500]
        podcast.last_updated = new_york_time()
        podcast.title = title[:500]
        podcast.description = description
        podcast.contact_name = contact_name[:255]
        podcast.contact_email = contact_email[:255]

        categories = soup.find_all('itunes:category')
        category_texts = [category['text'] for category in categories if category.has_attr('text')]
        podcast.categories = ', '.join(category_texts[:3])[:500]

        # Create embedding for podcast description
        podcast_embedding = create_embedding(description)
        podcast.embedding = podcast_embedding

        # Add episodes
        for episode_data in last_5_episodes:
            episode = Episode(
                podcast_id=podcast.id,
                client_id=podcast.client_id,
                title=episode_data['Title'][:500],
                date=episode_data['Date'],
                description=episode_data['Description']
            )
            
            # Create embedding for episode description
            episode_embedding = create_embedding(episode_data['Description'])
            episode.embedding = episode_embedding
            
            db.session.add(episode)

        # Commit all changes
        db.session.commit()
        logger.info(f'Processed podcast: {title}')

    except Exception as e:
        logger.error(f'Error processing podcast {podcast.rss_feed}: {str(e)}')
        db.session.rollback()
        raise