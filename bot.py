import time
import logging
import requests
import feedparser

# --- НАСТРОЙКИ ---
import os
# ... (остальные ваши импорты: time, logging, requests, feedparser)

# --- НАСТРОЙКИ ---
VK_TOKEN = os.environ.get("VK_TOKEN") # Токен будет браться из настроек GitHub
VK_GROUP_ID = "243236904"  
# ... (дальше идет ваш код без изменений)

# ТОЛЬКО российские компании (ищем эти слова)
KEYWORDS = [
    "Сбер", "Газпром", "Лукойл", "Норникель", "Яндекс", 
    "Тинькофф", "Т-Банк", "ВТБ", "Роснефть", "Мосбиржа", 
    "Аэрофлот", "Магнит", "Полюс", "Сургутнефтегаз", "Рубль", "ЦБ РФ",
]

# Слова-исключения (если новость содержит эти слова, бот её ПРОПУСТИТ)
IGNORE_WORDS = ["Space", "SpaceX", "Nvidia", "NVDA", "Apple", "Tesla", "AAPL", "TSLA", "Amazon", "Microsoft"]

# Ссылки на RSS-ленты российских новостей
RSS_FEEDS = [
    "https://rssexport.rbc.ru/rbcnews/news/30/full.rss",  
    "https://1prime.ru/export/rss2/index.xml",            
]

POLL_INTERVAL_SECONDS = 3600 # Проверка каждые 5 минут
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
    
    # Заголовки, чтобы сайты думали, что мы обычный браузер
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    for feed_url in RSS_FEEDS:
        try:
            # Скачиваем новости через requests
            response = requests.get(feed_url, headers=headers, timeout=10)
            
            # Парсим скачанный текст
            feed = feedparser.parse(response.content)
            
            print(f"[DEBUG] Скачано новостей из {feed_url}: {len(feed.entries)}")
            
            for entry in feed.entries:
                title = entry.get('title', '')
                summary = entry.get('summary', '')
                link = entry.get('link', '')
                
                text_to_check = (title + " " + summary).lower()
                
                # Для наглядности выведем первые 5 заголовков, которые мы скачали
                # print(f"[DEBUG] Проверяем: {title}") 
                
                has_keyword = any(kw.lower() in text_to_check for kw in KEYWORDS)
                has_ignored = any(ig.lower() in text_to_check for ig in IGNORE_WORDS)
                
                if has_keyword and not has_ignored:
                    recent_news.append({
                        "title": title,
                        "link": link,
                        "summary": summary,
                        "publisher": feed.feed.get('title', 'Российские новости'),
                    })
        except Exception as e:
            logger.error(f"Ошибка загрузки RSS {feed_url}: {e}")
            
    # Удаляем дубликаты
    unique_news = {v['title']: v for v in recent_news}.values()
    return list(unique_news)

def format_message(news_item: dict, score: float) -> str:
    title = news_item.get("title", "Без заголовка")
    link = news_item.get("link", "")
    publisher = news_item.get("publisher", "Неизвестно")

    if score > 0:
        emoji = "🟢 Позитив"
    elif score < 0:
        emoji = "🔴 Негатив"
    else:
        emoji = "⚪ Нейтрально"

    return (
        f"{emoji}\n\n"
        f"{title}\n\n"
        f"Источник: {publisher}\n"
        f"Подробнее: {link}"
    )

def post_to_vk_wall(text: str):
    url = "https://api.vk.com/method/wall.post"
    owner_id = f"-{VK_GROUP_ID}"
    
    payload = {
        "owner_id": owner_id,
        "from_group": 1, 
        "message": text,
        "access_token": VK_TOKEN,
        "v": "5.199"
    }
    
    try:
        response = requests.post(url, data=payload, timeout=10)
        data = response.json()
        if "error" in data:
            logger.error(f"❌ Ошибка VK API: {data['error'].get('error_msg')}")
            return False
        return True
    except Exception as e:
        logger.error(f"Ошибка соединения с VK: {e}")
        return False

def main():
    logger.info("Бот запущен. Публикация российских новостей на стену...")

    while True:
        logger.info("Начинаю проверку новостей...")
        alerts_sent = 0

        news_items = fetch_russian_news()
        logger.info(f"После фильтрации осталось новостей: {len(news_items)}")

        for item in news_items:
            title = item.get("title", "")
            score = analyze_russian_sentiment(title + " " + item.get("summary", ""))
            message = format_message(item, score)
            
            if post_to_vk_wall(message):
                logger.info(f"✅ Опубликовано: {title[:50]}...")
                alerts_sent += 1
                time.sleep(2) 

        logger.info(f"Проверка завершена. Опубликовано постов: {alerts_sent}")
        time.sleep(POLL_INTERVAL_SECONDS)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Программа остановлена.")