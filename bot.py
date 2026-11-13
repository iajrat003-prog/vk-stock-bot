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

# Ключевые слова и их тикеры на Московской Бирже (MOEX)
TICKER_MAP = {
    "Сбер": "SBER", "Газпром": "GAZP", "Лукойл": "LKOH", 
    "Норникель": "GMKN", "Яндекс": "YDEX", "Тинькофф": "T",
    "ВТБ": "VTBR", "Роснефть": "ROSN", "Мосбиржа": "MOEX", 
    "Аэрофлот": "AFLT", "Магнит": "MGNT", "Полюс": "PLZL",
    "Сургутнефтегаз": "SNGS"
}

IGNORE_WORDS = ["Space", "SpaceX", "Nvidia", "NVDA", "Apple", "Tesla", "AAPL", "TSLA", "Amazon", "Microsoft"]

RSS_FEEDS = [
    "https://rssexport.rbc.ru/rbcnews/news/30/full.rss",  
    "https://1prime.ru/export/rss2/index.xml",            
]

SEEN_FILE = "seen_news.json" # Файл для защиты от дубликатов
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

def load_seen_news():
    """Загружает список уже опубликованных ссылок."""
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except: return set()
    return set()

def save_seen_news(seen_set):
    """Сохраняет ссылки (храним только последние 100, чтобы файл не рос бесконечно)."""
    recent_links = list(seen_set)[-100:]
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(recent_links, f, ensure_ascii=False)

def get_stock_price(ticker: str):
    """Получает текущую цену акции с Московской Биржи (MOEX)."""
    url = f"https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/{ticker}.json?iss.meta=off"
    try:
        context = ssl._create_unverified_context()
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5, context=context) as response:
            data = json.loads(response.read().decode('utf-8'))
            marketdata = data.get('marketdata', {}).get('data', [])
            columns = data.get('marketdata', {}).get('columns', [])
            
            if marketdata and 'LAST' in columns:
                price_idx = columns.index('LAST')
                price = marketdata[0][price_idx]
                if price: return round(price, 2)
    except Exception as e:
        logger.error(f"Не удалось получить цену для {ticker}: {e}")
    return None

def fetch_russian_news():
    recent_news = []
    context = ssl._create_unverified_context()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    for feed_url in RSS_FEEDS:
        try:
            req = urllib.request.Request(feed_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10, context=context) as response:
                xml_data = response.read()
            
            root = ET.fromstring(xml_data)
            items = root.findall('.//item')
            
            for item in items:
                title = item.find('title').text if item.find('title') is not None else ''
                link = item.find('link').text if item.find('link') is not None else ''
                summary = item.find('description').text if item.find('description') is not None else ''
                
                text_to_check = (title + " " + summary).lower()
                
                has_keyword = any(kw.lower() in text_to_check for kw in TICKER_MAP.keys())
                has_ignored = any(ig.lower() in text_to_check for ig in IGNORE_WORDS)
                
                if has_keyword and not has_ignored:
                    recent_news.append({
                        "title": title,
                        "link": link,
                        "summary": summary,
                    })
        except Exception as e:
            logger.error(f"Ошибка загрузки RSS {feed_url}: {e}")
            
    unique_news = {v['title']: v for v in recent_news}.values()
    return list(unique_news)

def format_message(news_item: dict) -> str:
    title = news_item.get("title", "Без заголовка")
    link = news_item.get("link", "")
    text_to_check = (title + " " + news_item.get("summary", "")).lower()
    score = analyze_russian_sentiment(text_to_check)

    if score > 0: emoji = "🟢 Позитив"
    elif score < 0: emoji = "🔴 Негатив"
    else: emoji = "⚪ Нейтрально"

    # Ищем, про какую компанию новость, чтобы подтянуть цену
    stock_info = ""
    for name, ticker in TICKER_MAP.items():
        if name.lower() in text_to_check:
            price = get_stock_price(ticker)
            if price:
                stock_info = f"📈 {name} ({ticker}): {price} ₽\n"
                break # Берем первую найденную компанию

    return f"{emoji}\n\n{title}\n\n{stock_info}Подробнее: {link}"

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

    seen_news = load_seen_news()
    news_items = fetch_russian_news()
    
    # Фильтруем те, что уже видели
    new_items = [item for item in news_items if item['link'] not in seen_news]
    logger.info(f"Всего новостей: {len(news_items)}. Новых: {len(new_items)}")

    alerts_sent = 0
    for item in new_items:
        message = format_message(item)
        
        if post_to_vk_wall(message):
            logger.info(f"✅ Опубликовано: {item['title'][:50]}...")
            alerts_sent += 1
            seen_news.add(item['link'])
            time.sleep(1)

    if alerts_sent > 0:
        save_seen_news(seen_news)
    
    logger.info(f"Проверка завершена. Опубликовано постов: {alerts_sent}")
    os._exit(0)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Непредвиденная ошибка: {e}")
        os._exit(1)
