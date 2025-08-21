import requests
from bs4 import BeautifulSoup
import re
import os
import time

def get_page_content(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        print(f"Успешно загружена страница: {url}")
        return response.text
    except requests.RequestException as e:
        print(f"Ошибка загрузки страницы {url}: {e}")
        return None

def parse_story_metadata(soup):
    metadata = {}
    
    # Извлечение названия
    title_tag = soup.find('div', class_='gF-N5')
    metadata['title'] = title_tag.text.strip() if title_tag else "Без названия"
    
    # Извлечение автора
    author_tag = soup.find('a', href=re.compile(r'/user/'))
    metadata['author'] = author_tag.text.strip() if author_tag else "Неизвестный автор"
    
    # Извлечение описания
    description_tag = soup.find('div', class_='glL-c').find('pre', class_='mpshL _6pPkw') if soup.find('div', class_='glL-c') else None
    if description_tag:
        for copyright in description_tag.find_all('div', class_='DxZKg'):
            copyright.decompose()
        metadata['description'] = description_tag.get_text(strip=True)
    else:
        metadata['description'] = "Описание отсутствует"
    
    # Извлечение тегов
    tags = []
    tags_container = soup.find('div', class_='F8LJw')
    if tags_container:
        for tag in tags_container.find_all('a', class_='XZbAz'):
            tag_text = tag.find('span', class_='typography-label-small-semi')
            if tag_text:
                tags.append(tag_text.text.strip())
    metadata['tags'] = ', '.join(tags) if tags else "Теги отсутствуют"
    
    # Извлечение общей статистики
    stats = {'views': 0, 'votes': 0, 'chapters': 0}
    stats_container = soup.find('ul', class_='n0iXe')
    if stats_container:
        stat_items = stats_container.find_all('li', class_='_0jt-y')
        for i, stat in enumerate(stat_items):
            stat_value = stat.find('div', attrs={'data-tip': True})
            if stat_value and 'data-tip' in stat_value.attrs:
                value = int(re.sub(r'\D', '', stat_value['data-tip']) or 0)
                if i == 0:  # Первый элемент — просмотры
                    stats['views'] = value
                elif i == 1:  # Второй элемент — голоса
                    stats['votes'] = value
                # Третий элемент (главы) игнорируется, так как используется len(chapters)
    metadata['stats'] = stats
    
    return metadata

def parse_chapter_list(soup):
    chapters = []
    toc = soup.find('div', attrs={'data-testid': 'toc'})
    if toc:
        for li in toc.find_all('li'):
            chapter_link = li.find('a', href=re.compile(r'/[0-9]+-'))
            if chapter_link:
                chapter_url = chapter_link['href']
                if not chapter_url.startswith('https://'):
                    chapter_url = 'https://www.wattpad.com' + chapter_url
                chapter_title = chapter_link.find('div').text.strip() if chapter_link.find('div') else "Без названия"
                chapters.append({'title': chapter_title, 'url': chapter_url})
    return chapters

def parse_chapter_content(soup):
    content_div = soup.find('div', class_='panel-reading')
    if content_div:
        paragraphs = content_div.find_all('p')
        content = []
        for p in paragraphs:
            for unwanted in p.find_all(['button', 'div'], class_=re.compile(r'comment-marker|component-wrapper')):
                unwanted.decompose()
            text = p.get_text(strip=True)
            if text:
                content.append(text)
        return '\n\n'.join(content) if content else "Текст главы отсутствует"
    return "Текст главы отсутствует"

def parse_chapter_stats(soup):
    stats = {'views': 0, 'votes': 0, 'comments': 0}
    stats_container = soup.find('div', class_='story-stats')
    if stats_container:
        reads_span = stats_container.find('span', class_='reads')
        if reads_span:
            stats['views'] = int(re.sub(r'\D', '', reads_span.get_text(strip=True)) or 0)
        
        votes_span = stats_container.find('span', class_='votes')
        if votes_span:
            stats['votes'] = int(re.sub(r'\D', '', votes_span.get_text(strip=True)) or 0)
        
        comments_span = stats_container.find('span', class_='comments on-comments')
        if comments_span:
            stats['comments'] = int(re.sub(r'\D', '', comments_span.get_text(strip=True)) or 0)
    
    return stats

def save_to_markdown(metadata, chapters, output_file):
    # Устанавливаем количество глав на основе списка
    metadata['stats']['chapters'] = len(chapters)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"# {metadata['title']}\n\n")
        f.write(f"**Автор**: {metadata['author']}\n\n")
        f.write(f"**Описание**: {metadata['description']}\n\n")
        f.write(f"**Теги**: {metadata['tags']}\n\n")
        f.write(f"**Статистика**: Просмотры={metadata['stats']['views']}, Голоса={metadata['stats']['votes']}, Главы={metadata['stats']['chapters']}\n\n")
        
        f.write("## Оглавление\n")
        for i, chapter in enumerate(chapters, 1):
            f.write(f"{i}. [{chapter['title']}]({chapter['url']})\n")
        f.write("\n")
        
        for i, chapter in enumerate(chapters, 1):
            print(f"Загрузка главы: {chapter['title']}")
            chapter_html = get_page_content(chapter['url'])
            if chapter_html:
                chapter_soup = BeautifulSoup(chapter_html, 'html.parser')
                chapter_content = parse_chapter_content(chapter_soup)
                chapter_stats = parse_chapter_stats(chapter_soup)
                f.write(f"## {chapter['title']}\n\n")
                f.write(f"**Статистика главы**: Просмотры={chapter_stats['views']}, Голоса={chapter_stats['votes']}, Комментарии={chapter_stats['comments']}\n\n")
                f.write(f"{chapter_content}\n\n")
            time.sleep(1)
    
    print(f"Содержимое книги сохранено в {output_file}")

def main():
    story_url = "https://www.wattpad.com/story/400248520"
    output_file = "wattpad_book.md"
    
    html_content = get_page_content(story_url)
    if not html_content:
        return
    
    soup = BeautifulSoup(html_content, 'html.parser')
    metadata = parse_story_metadata(soup)
    
    print(f"Название: {metadata['title']}")
    print(f"Автор: {metadata['author']}")
    print(f"Описание: {metadata['description']}")
    print(f"Теги: {metadata['tags']}")
    print(f"Статистика: Просмотры={metadata['stats']['views']}, Голоса={metadata['stats']['votes']}, Главы={metadata['stats']['chapters']}")
    
    chapters = parse_chapter_list(soup)
    print(f"Найдено глав: {len(chapters)}")
    
    save_to_markdown(metadata, chapters, output_file)

if __name__ == "__main__":
    main()