import requests
from bs4 import BeautifulSoup
import re
import os
import time
from concurrent.futures import ThreadPoolExecutor
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from ebooklib import epub
import urllib.parse

def clean_xml_string(text):
    """Удаляет невалидные XML-символы из строки."""
    if not text:
        return ""
    # Удаляем управляющие символы (0x00–0x1F, кроме 0x09, 0x0A, 0x0D)
    return re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', text)

def get_page_content(url, cookies=None):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers, cookies=cookies, timeout=10)
        response.raise_for_status()
        print(f"Успешно загружена страница: {url}")
        return response.text
    except requests.RequestException as e:
        print(f"Ошибка загрузки страницы {url}: {e}")
        return None

def download_image(url, output_dir, filename):
    if not url:
        return None
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'wb') as f:
            f.write(response.content)
        print(f"Изображение сохранено в {filepath}")
        return filepath
    except requests.RequestException as e:
        print(f"Ошибка загрузки изображения {url}: {e}")
        return None

def parse_story_metadata(soup, output_dir):
    metadata = {}
    
    # Извлечение названия
    title_tag = soup.find('div', class_='gF-N5')
    metadata['title'] = clean_xml_string(title_tag.text.strip() if title_tag else "Без названия")
    
    # Извлечение автора
    author_tag = soup.find('a', href=re.compile(r'/user/'))
    metadata['author'] = clean_xml_string(author_tag.text.strip() if author_tag else "Неизвестный автор")
    
    # Извлечение описания
    description_tag = soup.find('div', class_='glL-c').find('pre', class_='mpshL _6pPkw') if soup.find('div', class_='glL-c') else None
    if description_tag:
        for copyright in description_tag.find_all('div', class_='DxZKg'):
            copyright.decompose()
        metadata['description'] = clean_xml_string(description_tag.get_text(strip=True))
    else:
        metadata['description'] = "Описание отсутствует"
    
    # Извлечение тегов
    tags = []
    tags_container = soup.find('div', class_='F8LJw')
    if tags_container:
        for tag in tags_container.find_all('a', class_='XZbAz'):
            tag_text = tag.find('span', class_='typography-label-small-semi')
            if tag_text:
                tags.append(clean_xml_string(tag_text.text.strip()))
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
                if i == 0:
                    stats['views'] = value
                elif i == 1:
                    stats['votes'] = value
    
    # Извлечение и скачивание обложки
    cover_tag = soup.find('div', class_='coverWrapper__t2Ve8').find('img', class_='cover__BlyZa') if soup.find('div', class_='coverWrapper__t2Ve8') else None
    metadata['cover_url'] = cover_tag['src'] if cover_tag and 'src' in cover_tag.attrs else None
    metadata['cover_path'] = download_image(metadata['cover_url'], output_dir, "cover.jpg") if metadata['cover_url'] else None
    
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
                chapter_title = clean_xml_string(chapter_link.find('div').text.strip() if chapter_link.find('div') else "Без названия")
                chapters.append({'title': chapter_title, 'url': chapter_url})
    return chapters

def parse_chapter_content(soup, chapter_index, output_dir):
    content_div = soup.find('div', class_='panel-reading')
    content = []
    image_counter = 1
    if content_div:
        print(f"DEBUG: Найден <div class='panel-reading'> для главы {chapter_index}")
        pre_tag = content_div.find('pre')
        if pre_tag:
            print(f"DEBUG: Найден <pre> в главе {chapter_index}")
            # Парсим <p> и <figure> последовательно
            for element in pre_tag.find_all(['p', 'figure'], recursive=False):
                if element.name == 'p':
                    # Удаляем ненужные элементы (комментарии, кнопки)
                    for unwanted in element.find_all(['button', 'div'], class_=re.compile(r'comment-marker|component-wrapper')):
                        unwanted.decompose()
                    text = clean_xml_string(element.get_text(strip=True))
                    print(f"DEBUG: Текст из <p> (data-p-id={element.get('data-p-id', 'N/A')}): {text[:100]}...")
                    if text:
                        content.append({'type': 'text', 'value': text})
                elif element.name == 'figure':
                    img_tag = element.find('img')
                    if img_tag and 'src' in img_tag.attrs:
                        img_url = img_tag['src']
                        img_alt = clean_xml_string(img_tag.get('alt', ''))
                        print(f"DEBUG: Изображение найдено в <figure>: {img_url}, alt: {img_alt}")
                        img_filename = f"chapter_{chapter_index}_image_{image_counter}.jpg"
                        img_path = download_image(img_url, output_dir, img_filename)
                        if img_path:
                            content.append({'type': 'image', 'path': os.path.basename(img_path), 'alt': img_alt})
                            image_counter += 1
        else:
            print(f"DEBUG: <pre> не найден, ищем <p> и <img> в главе {chapter_index}")
            # Обрабатываем <p> и <img> в <div class="panel-reading">
            for element in content_div.find_all(['p', 'img'], recursive=False):
                if element.name == 'p':
                    for unwanted in element.find_all(['button', 'div'], class_=re.compile(r'comment-marker|component-wrapper')):
                        unwanted.decompose()
                    text = clean_xml_string(element.get_text(strip=True))
                    print(f"DEBUG: Текст из <p>: {text[:100]}...")
                    if text:
                        content.append({'type': 'text', 'value': text})
                elif element.name == 'img' and 'src' in element.attrs:
                    img_url = element['src']
                    img_alt = clean_xml_string(element.get('alt', ''))
                    print(f"DEBUG: Изображение найдено: {img_url}, alt: {img_alt}")
                    img_filename = f"chapter_{chapter_index}_image_{image_counter}.jpg"
                    img_path = download_image(img_url, output_dir, img_filename)
                    if img_path:
                        content.append({'type': 'image', 'path': os.path.basename(img_path), 'alt': img_alt})
                        image_counter += 1
        
        print(f"DEBUG: Найдено {image_counter-1} изображений в главе {chapter_index}")
        if not content:
            print(f"DEBUG: Содержимое <div class='panel-reading'>: {str(content_div)[:200]}...")
    else:
        print(f"DEBUG: <div class='panel-reading'> не найден в главе {chapter_index}")
    return content if content else [{'type': 'text', 'value': "Текст главы отсутствует"}]

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
        comments_span = soup.find('span', class_='comments on-comments')
        if comments_span:
            stats['comments'] = int(re.sub(r'\D', '', comments_span.get_text(strip=True)) or 0)
    return stats

def process_chapter(chapter, index, output_dir):
    chapter_html = get_page_content(chapter['url'])
    if chapter_html:
        chapter_soup = BeautifulSoup(chapter_html, 'html.parser')
        content = parse_chapter_content(chapter_soup, index + 1, output_dir)
        stats = parse_chapter_stats(chapter_soup)
        return {'title': chapter['title'], 'url': chapter['url'], 'content': content, 'stats': stats, 'index': index}
    return None

def save_to_markdown(metadata, chapters_data, output_file):
    output_dir = os.path.dirname(output_file) or "."
    with open(output_file, 'w', encoding='utf-8') as f:
        # Только обложка в начале
        if metadata['cover_path']:
            f.write(f"![Обложка]({os.path.basename(metadata['cover_path'])})\n\n")
        
        # Метаданные и оглавление
        f.write(f"# {metadata['title']}\n\n")
        f.write(f"**Автор**: {metadata['author']}\n\n")
        f.write(f"**Описание**: {metadata['description']}\n\n")
        f.write(f"**Теги**: {metadata['tags']}\n\n")
        f.write(f"**Статистика**: Просмотры={metadata['stats']['views']}, Голоса={metadata['stats']['votes']}, Главы={metadata['stats']['chapters']}\n\n")
        f.write("## Оглавление\n")
        for i, chapter in enumerate(chapters_data, 1):
            f.write(f"{i}. [{chapter['title']}]({chapter['url']})\n")
        f.write("\n")
        
        # Главы
        for chapter in chapters_data:
            if chapter:
                f.write(f"## {chapter['title']}\n\n")
                f.write(f"**Статистика главы**: Просмотры={chapter['stats']['views']}, Голоса={chapter['stats']['votes']}, Комментарии={chapter['stats']['comments']}\n\n")
                for item in chapter['content']:
                    if item['type'] == 'text':
                        f.write(f"{item['value']}\n\n")
                    elif item['type'] == 'image':
                        f.write(f"![{item['alt']}]({item['path']})\n\n")
    
    print(f"Содержимое книги сохранено в {output_file}")

def save_to_txt(metadata, chapters_data, output_file):
    output_dir = os.path.dirname(output_file) or "."
    with open(output_file, 'w', encoding='utf-8') as f:
        # Только обложка в начале
        if metadata['cover_path']:
            f.write(f"Обложка: {os.path.basename(metadata['cover_path'])}\n\n")
        
        # Метаданные и оглавление
        f.write(f"{metadata['title']}\n\n")
        f.write(f"Автор: {metadata['author']}\n\n")
        f.write(f"Описание: {metadata['description']}\n\n")
        f.write(f"Теги: {metadata['tags']}\n\n")
        f.write(f"Статистика: Просмотры={metadata['stats']['views']}, Голоса={metadata['stats']['votes']}, Главы={metadata['stats']['chapters']}\n\n")
        f.write("Оглавление\n")
        for i, chapter in enumerate(chapters_data, 1):
            f.write(f"{i}. {chapter['title']} ({chapter['url']})\n")
        f.write("\n")
        
        # Главы
        for chapter in chapters_data:
            if chapter:
                f.write(f"{chapter['title']}\n\n")
                f.write(f"Статистика главы: Просмотры={chapter['stats']['views']}, Голоса={chapter['stats']['votes']}, Комментарии={chapter['stats']['comments']}\n\n")
                for item in chapter['content']:
                    if item['type'] == 'text':
                        f.write(f"{item['value']}\n\n")
                    elif item['type'] == 'image':
                        f.write(f"Изображение: {item['path']} ({item['alt']})\n\n")
    
    print(f"Содержимое книги сохранено в {output_file}")

def save_to_pdf(metadata, chapters_data, output_file):
    output_dir = os.path.dirname(output_file) or "."
    # Пытаемся зарегистрировать DejaVuSans из папки font
    font_name = 'Times-Roman'  # Запасной шрифт
    font_dir = os.path.join(output_dir, 'font')
    try:
        pdfmetrics.registerFont(TTFont('DejaVuSans', os.path.join(font_dir, 'DejaVuSans.ttf')))
        font_name = 'DejaVuSans'
        print("Шрифт DejaVuSans успешно зарегистрирован для PDF")
    except:
        try:
            pdfmetrics.registerFont(TTFont('LiberationSerif', os.path.join(font_dir, 'LiberationSerif-Regular.ttf')))
            font_name = 'LiberationSerif'
            print("Шрифт LiberationSerif успешно зарегистрирован для PDF")
        except:
            print(f"Предупреждение: Файлы шрифтов DejaVuSans.ttf и LiberationSerif-Regular.ttf не найдены в папке {font_dir}. Используется Times-Roman (ограниченная поддержка кириллицы).")
            print("Скачайте DejaVuSans.ttf или LiberationSerif-Regular.ttf с https://www.fontsquirrel.com/fonts/dejavu-sans или https://www.fontsquirrel.com/fonts/liberation-serif и поместите в папку font.")
    
    doc = SimpleDocTemplate(output_file, pagesize=letter)
    styles = getSampleStyleSheet()
    styles['Title'].fontName = font_name
    styles['Normal'].fontName = font_name
    styles['Heading2'].fontName = font_name
    story = []
    
    # Только обложка в начале
    if metadata['cover_path']:
        story.append(Image(metadata['cover_path'], width=200, height=200))
        story.append(Spacer(1, 12))
    
    # Метаданные и оглавление
    story.append(Paragraph(clean_xml_string(metadata['title']), styles['Title']))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"Автор: {clean_xml_string(metadata['author'])}", styles['Normal']))
    story.append(Paragraph(f"Описание: {clean_xml_string(metadata['description'])}", styles['Normal']))
    story.append(Paragraph(f"Теги: {clean_xml_string(metadata['tags'])}", styles['Normal']))
    story.append(Paragraph(f"Статистика: Просмотры={metadata['stats']['views']}, Голоса={metadata['stats']['votes']}, Главы={metadata['stats']['chapters']}", styles['Normal']))
    story.append(Spacer(1, 12))
    story.append(Paragraph("Оглавление", styles['Heading2']))
    for i, chapter in enumerate(chapters_data, 1):
        story.append(Paragraph(f"{i}. {clean_xml_string(chapter['title'])}", styles['Normal']))
    story.append(Spacer(1, 12))
    
    # Главы
    for chapter in chapters_data:
        if chapter:
            story.append(Paragraph(clean_xml_string(chapter['title']), styles['Heading2']))
            story.append(Paragraph(f"Статистика главы: Просмотры={chapter['stats']['views']}, Голоса={chapter['stats']['votes']}, Комментарии={chapter['stats']['comments']}", styles['Normal']))
            story.append(Spacer(1, 12))
            for item in chapter['content']:
                if item['type'] == 'text':
                    story.append(Paragraph(clean_xml_string(item['value']), styles['Normal']))
                    story.append(Spacer(1, 12))
                elif item['type'] == 'image':
                    img_path = os.path.join(output_dir, item['path'])
                    story.append(Image(img_path, width=200, height=200))
                    if item['alt']:
                        story.append(Paragraph(clean_xml_string(item['alt']), styles['Normal']))
                    story.append(Spacer(1, 12))
    
    doc.build(story)
    print(f"Содержимое книги сохранено в {output_file}")

def save_to_epub(metadata, chapters_data, output_file):
    output_dir = os.path.dirname(output_file) or "."
    book = epub.EpubBook()
    book.set_identifier(f"wattpad_{clean_xml_string(metadata['title'])}")
    book.set_title(clean_xml_string(metadata['title']))
    book.set_language('ru')
    book.add_author(clean_xml_string(metadata['author']))

    # Обложка
    # cover_page = None
    # if metadata['cover_path']:
    #     with open(metadata['cover_path'], 'rb') as f:
    #         book.set_cover('cover.jpg', f.read())
    #     cover_page = epub.EpubHtml(title='Обложка', file_name='cover_page.xhtml', lang='ru')
    #     cover_page.content = f'<h1>{clean_xml_string(metadata["title"])}</h1><img src="cover.jpg" alt="Обложка" />'.encode('utf-8')
    #     book.add_item(cover_page)

    # Метаданные
    meta_chapter = epub.EpubHtml(title='Метаданные', file_name='meta.xhtml', lang='ru')
    meta_content = f"""
    <h1 style="text-align: center;">{clean_xml_string(metadata['title'])}</h1>
    <p><b>Автор:</b> {clean_xml_string(metadata['author'])}</p>
    <p><b>Описание:</b> {clean_xml_string(metadata['description'])}</p>
    <p><b>Теги:</b> {clean_xml_string(metadata['tags'])}</p>
    <p><b>Статистика:</b> Просмотры={metadata['stats']['views']}, Голоса={metadata['stats']['votes']}, Главы={metadata['stats']['chapters']}</p>
    """
    meta_chapter.content = clean_xml_string(meta_content).encode('utf-8')
    book.add_item(meta_chapter)

    # Оглавление на новой странице
    toc_chapter = epub.EpubHtml(title='Оглавление', file_name='toc.xhtml', lang='ru')
    toc_content = f"""
    <h2 style="page-break-before: always; text-align: center;">Оглавление</h2>
    <ul>
    """
    for i, chapter in enumerate(chapters_data, 1):
        toc_content += f"<li><a href='chapter_{i}.xhtml'>{clean_xml_string(chapter['title'])}</a></li>"
    toc_content += "</ul>"
    toc_chapter.content = clean_xml_string(toc_content).encode('utf-8')
    book.add_item(toc_chapter)

    # Главы
    chapter_items = []
    for i, chapter in enumerate(chapters_data, 1):
        chapter_html = epub.EpubHtml(title=clean_xml_string(chapter['title']), file_name=f'chapter_{i}.xhtml', lang='ru')
        content = f"<h1>{clean_xml_string(chapter['title'])}</h1>"
        content += f"<p><b>Статистика главы:</b> Просмотры={chapter['stats']['views']}, Голоса={chapter['stats']['votes']}, Комментарии={chapter['stats']['comments']}</p>"
        for item in chapter['content']:
            if item['type'] == 'text':
                content += f"<p>{clean_xml_string(item['value'])}</p>"
            elif item['type'] == 'image':
                img_filename = item['path']
                with open(os.path.join(output_dir, img_filename), 'rb') as f:
                    img_item = epub.EpubImage()
                    img_item.file_name = img_filename
                    img_item.content = f.read()
                    book.add_item(img_item)
                content += f"<p><img src='{img_filename}' alt='{clean_xml_string(item['alt'])}' /></p>"
        chapter_html.content = clean_xml_string(content).encode('utf-8')
        book.add_item(chapter_html)
        chapter_items.append(chapter_html)

    # TOC и spine
    toc = []
    spine = []
    # if cover_page:
    #     toc.append(cover_page)
    #     spine.append(cover_page)
    toc.append(meta_chapter)
    toc.append(toc_chapter)
    spine.append(meta_chapter)
    spine.append(toc_chapter)
    toc.extend(chapter_items)
    spine.extend(chapter_items)

    book.toc = toc
    book.spine = [] + spine
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    epub.write_epub(output_file, book)
    print(f"Содержимое книги сохранено в {output_file}")


def main():
    story_url = "https://www.wattpad.com/story/400248520"
    output_base = "wattpad_book"
    output_dir = os.path.dirname(output_base) or "."
    
    # Для авторизации (если требуется)
    cookies = None  # Замените на {'session_id': 'your_session_id', ...} при необходимости
    html_content = get_page_content(story_url, cookies=cookies)
    if not html_content:
        print("Ошибка: Не удалось загрузить главную страницу. Проверьте URL или добавьте cookies для авторизации.")
        return
    
    soup = BeautifulSoup(html_content, 'html.parser')
    metadata = parse_story_metadata(soup, output_dir)
    
    print(f"Название: {metadata['title']}")
    print(f"Автор: {metadata['author']}")
    print(f"Описание: {metadata['description']}")
    print(f"Теги: {metadata['tags']}")
    print(f"Статистика: Просмотры={metadata['stats']['views']}, Голоса={metadata['stats']['votes']}, Главы={metadata['stats']['chapters']}")
    
    chapters = parse_chapter_list(soup)
    print(f"Найдено глав: {len(chapters)}")
    metadata['stats']['chapters'] = len(chapters)
    
    chapters_data = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_chapter = {executor.submit(process_chapter, chapter, i, output_dir): i for i, chapter in enumerate(chapters)}
        for future in future_to_chapter:
            result = future.result()
            if result:
                chapters_data.append(result)
    
    # Сортировка chapters_data по индексу
    chapters_data.sort(key=lambda x: x['index'])
    
    save_to_markdown(metadata, chapters_data, f"{output_base}.md")
    save_to_txt(metadata, chapters_data, f"{output_base}.txt")
    save_to_pdf(metadata, chapters_data, f"{output_base}.pdf")
    save_to_epub(metadata, chapters_data, f"{output_base}.epub")

if __name__ == "__main__":
    main()