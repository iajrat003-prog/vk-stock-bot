import os
import time
import logging
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import json
import ssl
from datetime import datetime, timedelta

# --- НАСТРОЙКИ ---
VK_TOKEN = os.environ.get("VK_TOKEN")
VK_GROUP_ID = "243236904"

TICKER_MAP = {
    "Сбер": "SBER", "Газпром": "GAZP", "Лукойл": "LKOH", 
    "Норникель": "GMKN", "Яндекс": "YDEX", "Тинькофф": "T",
    "ВТБ": "VTBR", "Роснефть": "ROSN", "Мосбиржа": "MOEX", 
    "Аэрофлот": "AFLT", "Магнит": "MGNT", "Полюс": "PLZL",
    "Сургутнефтегаз": "SNGS", "Татнефть": "TATN", "Новатэк": "NVTK"
}

IGNORE_WORDS = ["Space", "SpaceX", "Nvidia", "NVDA", "Apple", "Tesla", "AAPL", "TSLA", "Amazon", "Microsoft"]

RSS_FEEDS = [
    "https://rssexport.rbc.ru/rbcnews/news/30/full.rss",  
    "https://1prime.ru/export/rss2/index.xml",            
]

SEEN_NEWS_FILE = "seen_news.json"
SEEN_ALERTS_FILE = "seen_alerts.json"

# Текст призыва к действию (добавляется ко всем постам)
CALL_TO_ACTION = "\n\n👉 Больше аналитики и сигналов в нашем сообществе: @club243236904"
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

def load_json_set(filename):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except: return set()
    return set()

def save_json_set(filename, data_set):
    recent = list(data_set)[-100:]
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(recent, f, ensure_ascii=False)

def get_macro_info():
    try:
        context = ssl._create_unverified_context()
        url = "https://www.cbr-xml-daily.ru/daily_json.js"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5, context=context) as response:
            data = json.loads(response.read().decode('utf-8'))
            usd = data['Valute']['USD']['Value']
            eur = data['Valute']['EUR']['Value']
            return f"💱 Валютный рынок: доллар торгуется по {usd:.2f} ₽, евро — по {eur:.2f} ₽."
    except:
        return ""

def calculate_rsi(prices, periods=14):
    if len(prices) < periods + 1: return None
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-periods:]) / periods
    avg_loss = sum(losses[-periods:]) / periods
    if avg_loss == 0: return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def get_basic_price_info(ticker: str):
    context = ssl._create_unverified_context()
    url = f"https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/{ticker}.json?iss.meta=off"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5, context=context) as response:
            data = json.loads(response.read().decode('utf-8'))
            md_data = data.get('marketdata', {}).get('data', [])
            md_cols = data.get('marketdata', {}).get('columns', [])
            if md_data and 'LAST' in md_cols:
                price = round(md_data[0][md_cols.index('LAST')], 2)
                day_change = md_data[0][md_cols.index('LASTTOPREVPRICE')] if 'LASTTOPREVPRICE' in md_cols else None
                return price, day_change
    except: pass
    return None, None

def get_full_stock_info(ticker: str):
    context = ssl._create_unverified_context()
    current_price, day_change = get_basic_price_info(ticker)
    month_change, rsi, pe = None, None, None
    
    if current_price is None: return None, None, None, None, None

    date_till = datetime.now().strftime("%Y-%m-%d")
    date_from = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d")
    url_history = f"https://iss.moex.com/iss/history/engines/stock/markets/shares/boards/TQBR/securities/{ticker}.json?from={date_from}&till={date_till}&iss.meta=off"
    try:
        req = urllib.request.Request(url_history, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5, context=context) as response:
            data = json.loads(response.read().decode('utf-8'))
            hist_data = data.get('history', {}).get('data', [])
            hist_cols = data.get('history', {}).get('columns', [])
            closes = [row[hist_cols.index('CLOSE')] for row in hist_data if row[hist_cols.index('CLOSE')] is not None]
            if len(closes) >= 2 and closes[0] > 0:
                month_change = round(((closes[-1] - closes[0]) / closes[0]) * 100, 2)
            if len(closes) >= 15:
                rsi = round(calculate_rsi(closes), 1)
    except: pass

    url_stats = f"https://iss.moex.com/iss/statistics/engines/stock/markets/shares/securities/{ticker}.json?iss.meta=off"
    try:
        req = urllib.request.Request(url_stats, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5, context=context) as response:
            data = json.loads(response.read().decode('utf-8'))
            sec_data = data.get('securities', {}).get('data', [])
            sec_cols = data.get('securities', {}).get('columns', [])
            if sec_data and 'PE_RATIO' in sec_cols and sec_data[0][sec_cols.index('PE_RATIO')]:
                pe = round(sec_data[0][sec_cols.index('PE_RATIO')], 2)
    except: pass

    return current_price, day_change, month_change, rsi, pe

def fetch_russian_news():
    recent_news = []
    context = ssl._create_unverified_context()
    headers = {'User-Agent': 'Mozilla/5.0'}
    for feed_url in RSS_FEEDS:
        try:
            req = urllib.request.Request(feed_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10, context=context) as response:
                root = ET.fromstring(response.read())
            for item in root.findall('.//item'):
                title = item.find('title').text if item.find('title') is not None else ''
                link = item.find('link').text if item.find('link') is not None else ''
                summary = item.find('description').text if item.find('description') is not None else ''
                text_to_check = (title + " " + summary).lower()
                if any(kw.lower() in text_to_check for kw in TICKER_MAP.keys()) and not any(ig.lower() in text_to_check for ig in IGNORE_WORDS):
                    recent_news.append({"title": title, "link": link, "summary": summary})
        except: pass
    return list({v['title']: v for v in recent_news}.values())

def format_news_message(news_item: dict) -> str:
    title = news_item.get("title", "Без заголовка")
    link = news_item.get("link", "")
    text_to_check = (title + " " + news_item.get("summary", "")).lower()
    score = analyze_russian_sentiment(text_to_check)
    
    if score > 0: 
        intro = "Хорошие новости для рынка:"
    elif score < 0: 
        intro = "Неприятные вести для инвесторов:"
    else: 
        intro = "Свежие новости с рынка:"

    stock_info = ""
    for name, ticker in TICKER_MAP.items():
        if name.lower() in text_to_check:
            price, day_change, month_change, rsi, pe = get_full_stock_info(ticker)
            if price is not None:
                stock_info = f"\n📊 Как чувствует себя {name} ({ticker}):\n"
                stock_info += f"Цена сейчас — {price} ₽. "
                
                if day_change is not None:
                    if day_change > 0: stock_info += f"За день бумага подросла на {day_change:.2f}%. "
                    elif day_change < 0: stock_info += f"Днем акция просела на {abs(day_change):.2f}%. "
                    else: stock_info += "Днем цена почти не изменилась. "
                    
                if month_change is not None:
                    if month_change > 0: stock_info += f"За месяц рост составил {month_change:.2f}%. "
                    elif month_change < 0: stock_info += f"За месяц падение на {abs(month_change):.2f}%. "
                
                stock_info += "\n"
                
                if pe is not None: 
                    stock_info += f"Мультипликатор P/E: {pe}.\n"
                    
                if rsi is not None:
                    if rsi < 30: stock_info += f"Индекс RSI равен {rsi} — акция сильно перепродана, возможно скорое восстановление.\n"
                    elif rsi > 70: stock_info += f"Индекс RSI равен {rsi} — бумага перекуплена, стоит быть осторожнее с покупками.\n"
                    else: stock_info += f"Индекс RSI ({rsi}) находится в нейтральной зоне.\n"
            break
            
    macro_info = get_macro_info()
    macro_text = f"\n{macro_info}" if macro_info else ""
    
    # ДОБАВЛЯЕМ ПРИЗЫВ В КОНЕЦ
    return f"{intro}\n\n«{title}»\n{stock_info}{macro_text}\n\nПочитать подробнее: {link}{CALL_TO_ACTION}"

def check_market_alerts():
    logger.info("Проверка резких движений цен...")
    seen_alerts = load_json_set(SEEN_ALERTS_FILE)
    today = datetime.now().strftime('%Y-%m-%d')
    movers = []
    
    for name, ticker in TICKER_MAP.items():
        alert_key = f"alert_{ticker}_{today}"
        if alert_key in seen_alerts: continue
            
        price, day_change = get_basic_price_info(ticker)
        if price and day_change is not None and abs(day_change) >= 2.5: 
            movers.append((name, ticker, price, day_change, alert_key))
            
    if movers:
        text = "⚡️ Срочные движения на бирже!\n\n"
        for name, ticker, price, day_change, alert_key in movers:
            if day_change > 0:
                text += f"🟢 Бумаги «{name}» ({ticker}) показывают резкий рост — плюс {day_change:.2f}% за день. Сейчас торгуются по {price} ₽.\n"
            else:
                text += f"🔴 Акции «{name}» ({ticker}) заметно просели — минус {abs(day_change):.2f}% за день. Цена опустилась до {price} ₽.\n"
            seen_alerts.add(alert_key)
        
        # ДОБАВЛЯЕМ ПРИЗЫВ В КОНЕЦ
        text += CALL_TO_ACTION
        
        if post_to_vk_wall(text):
            logger.info(f"✅ Опубликованы алерты по {len(movers)} акциям.")
            save_json_set(SEEN_ALERTS_FILE, seen_alerts)

def publish_market_digest():
    logger.info("Сбор итогов торгового дня...")
    data = []
    for name, ticker in TICKER_MAP.items():
        price, day_change = get_basic_price_info(ticker)
        if price and day_change is not None:
            data.append((name, ticker, price, day_change))
            
    if not data: return
    
    data.sort(key=lambda x: x[3], reverse=True)
    gainers = data[:3]
    losers = data[-3:]
    losers.reverse()
    
    text = "📊 Подводим итоги торгового дня на Мосбирже.\n\n"
    
    text += "В лидерах роста сегодня:\n"
    for name, ticker, price, change in gainers:
        if change > 0: text += f"• {name} прибавил {change:.2f}% (до {price} ₽).\n"
            
    text += "\nХуже рынка торговались:\n"
    for name, ticker, price, change in losers:
        if change < 0: text += f"• {name} потерял {abs(change):.2f}% (цена опустилась до {price} ₽).\n"
            
    # ДОБАВЛЯЕМ ПРИЗЫВ В КОНЕЦ
    text += CALL_TO_ACTION
    
    if post_to_vk_wall(text):
        logger.info("✅ Вечерний дайджест опубликован.")

def post_to_vk_wall(text: str):
    url = "https://api.vk.com/method/wall.post"
    payload = {"owner_id": f"-{VK_GROUP_ID}", "from_group": 1, "message": text, "access_token": VK_TOKEN, "v": "5.199"}
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
        logger.error(f"Ошибка VK: {e}")
        return False

def main():
    logger.info("Бот запущен...")
    if not VK_TOKEN: os._exit(1)

    seen_news = load_json_set(SEEN_NEWS_FILE)
    new_news = [item for item in fetch_russian_news() if item['link'] not in seen_news]
    
    alerts_sent = 0
    for item in new_news:
        if post_to_vk_wall(format_news_message(item)):
            alerts_sent += 1
            seen_news.add(item['link'])
            time.sleep(1)
    if alerts_sent > 0: save_json_set(SEEN_NEWS_FILE, seen_news)

    check_market_alerts()

    now = datetime.utcnow()
    today_str = datetime.now().strftime('%Y-%m-%d')
    digest_key = f"digest_{today_str}"
    seen_alerts = load_json_set(SEEN_ALERTS_FILE)
    
    if now.hour == 18 and digest_key not in seen_alerts:
        publish_market_digest()
        seen_alerts.add(digest_key)
        save_json_set(SEEN_ALERTS_FILE, seen_alerts)
        alerts_sent += 1

    logger.info(f"Работа завершена. Опубликовано постов: {alerts_sent}")
    os._exit(0)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        os._exit(1)
