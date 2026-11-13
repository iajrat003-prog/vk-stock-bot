import os
import time
import logging
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import json
import ssl

# --- НАСТРОЙКИ ---
VK_TOKEN = os.environ.get("VK_TOKEN") 
VK_GROUP_ID = "243236904"  

KEYWORDS = [
    "Сбер", "Газпром", "Лукойл", "Норникель", "Яндекс", 
    "Тинькофф", "Т-Банк", "ВТБ", "Роснефть", "Мосбиржа", 
    "Аэрофлот", "Магнит", "Полюс", "Сургутнефтегаз", "Рубль", "ЦБ РФ"
]

IGNORE_WORDS = ["Space", "SpaceX", "Nvidia", "NVDA", "Apple", "Tesla", "AAPL", "TSLA", "Amazon", "Microsoft"]

RSS_FEEDS = [
    "https://rssexport.rbc.ru/rbcnews/news/30/full.rss",  
    "https://1prime.ru/export/rss2/index.xml",            
]
# -----------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

POSITIVE_WORDS = ["рост", "прибыль", "дивиденды", "увеличение", "рекорд", "подорожал", "позитив", "вырос"]
NEGATIVE_WORDS = ["падение", "убыток", "санкции", "снижение", "обвал", "подешевел", "негатив", "упал", "риск"]

def analyze_russian_sentiment(text: str) -> float:
    text = text.lower()
    score = 0.0
    for word in POSITIVE_WORDS:
        if word in text: score += 0.5
    for word in NEGATIVE_WORDS:
        if word in text: score -= 0.5
    return score

def fetch_russian_news():
    recent_news = []
    # Отключаем проверку SSL (иногда на серверах GitHub бывают проблемы с сертификатами)
    context = ssl._create_unverified_context()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    for feed_url in RSS_FEEDS:
        try:
            req = urllib.request.Request(feed_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10, context=context) as response:
                xml_data = response.read()
            
            root = ET.fromstring(xml_data)
            items = root.findall('.//item')
            
            print(f"[DEBUG] Скачано новостей из {feed_url}: {len(items)}")
            
            for item in items:
                title = item.find('title').text if item.find('title') is not None else ''
                link = item.find('link').text if item.find('link') is not None else ''
                summary = item.find('description').text if item.find('description') is not None else ''
                
                text_to_check = (title + " " + summary).lower()
                
                has_keyword = any(kw.lower() in text_to_check for kw in KEYWORDS)
                has_ignored = any(ig.lower() in text_to_check for ig in IGNORE_WORDS)
                
                if has_keyword and not has_ignored:
                    recent_news.append({
                        "title": title,
                        "link": link,
                        "summary": summary,
                        "publisher": "RSS"
                    })
        except Exception as e:
            logger.error(f"Ошибка загрузки RSS {feed_url}: {e}")
            
    unique_news = {v['title']: v for v in recent_news}.values()
    return list(unique_news)

def format_message(news_item: dict, score: float) -> str:
    title = news_item.get("title", "Без заголовка")
    link = news_item.get("link", "")

    if score > 0: emoji = "🟢 Позитив"
    elif score < 0: emoji = "🔴 Негатив"
    else: emoji = "⚪ Нейтрально"

    return f"{emoji}\n\n{title}\n\nПодробнее: {link}"

def post_to_vk_wall(text: str):
    url = "https://api.vk.com/method/wall.post"
    payload = {
        "owner_id": f"-{VK_GROUP_ID}",
        "from_group": 1, 
        "message": text,
        "access_token": VK_TOKEN,
        "v": "5.199"
    }
    data = urllib.parse.urlencode(payload).encode('utf-8')
    
    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            if "error" in res_data:
                logger.error(f"❌ Ошибка VK API: {res_data['error'].get('error_msg')}")
                return False
            return True
    except Exception as e:
        logger.error(f"Ошибка соединения с VK: {e}")
        return False

def main():
    logger.info("Бот запущен. Проверка новостей...")

    if not VK_TOKEN:
        logger.error("КРИТИЧЕСКАЯ ОШИБКА: Переменная VK_TOKEN не найдена!")
        os._exit(1)

    news_items = fetch_russian_news()
    logger.info(f"После фильтрации осталось новостей: {len(news_items)}")

    alerts_sent = 0
    for item in news_items:
        title = item.get("title", "")
        score = analyze_russian_sentiment(title + " " + item.get("summary", ""))
        message = format_message(item, score)
        
        if post_to_vk_wall(message):
            logger.info(f"✅ Опубликовано: {title[:50]}...")
            alerts_sent += 1
            time.sleep(1)

    logger.info(f"Проверка завершена. Опубликовано постов: {alerts_sent}")
    
    # Мгновенное завершение
    os._exit(0)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Непредвиденная ошибка: {e}")
        os._exit(1)
