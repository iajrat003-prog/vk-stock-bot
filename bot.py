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
    "Сургутнефтегаз": "SNGS", "Татнефть": "TATN", "Новатэк": "NVTK",
    "МТС": "MTSS", "ДОМ.РФ": "DOMRF"
}

IGNORE_WORDS = ["Space", "SpaceX", "Nvidia", "NVDA", "Apple", "Tesla", "AAPL", "TSLA", "Amazon", "Microsoft"]

RSS_FEEDS = [
    "https://rssexport.rbc.ru/rbcnews/news/30/full.rss",  
    "https://1prime.ru/export/rss2/index.xml",            
]

SEEN_FILE = "seen_news.json"
IDEAS_SEEN_FILE = "seen_ideas.json"
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

def get_stock_info(ticker: str):
    context = ssl._create_unverified_context()
    url_current = f"https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/{ticker}.json?iss.meta=off"
    current_price, day_change = None, None
    try:
        req = urllib.request.Request(url_current, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5, context=context) as response:
            data = json.loads(response.read().decode('utf-8'))
            md_data = data.get('marketdata', {}).get('data', [])
            md_cols = data.get('marketdata', {}).get('columns', [])
            if md_data and 'LAST' in md_cols:
                current_price = round(md_data[0][md_cols.index('LAST')], 2)
            if md_data and 'LASTTOPREVPRICE' in md_cols:
                day_change = md_data[0][md_cols.index('LASTTOPREVPRICE')]
    except Exception as e:
        logger.error(f"Ошибка получения текущей цены {ticker}: {e}")

    month_change = None
    date_till = datetime.now().strftime("%Y-%m-%d")
    date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    url_history = f"https://iss.moex.com/iss/history/engines/stock/markets/shares/boards/TQBR/securities/{ticker}.json?from={date_from}&till={date_till}&iss.meta=off"
    try:
        req = urllib.request.Request(url_history, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5, context=context) as response:
            data = json.loads(response.read().decode('utf-8'))
            hist_data = data.get('history', {}).get('data', [])
            hist_cols = data.get('history', {}).get('columns', [])
            closes = []
            if hist_data and 'CLOSE' in hist_cols:
                close_idx = hist_cols.index('CLOSE')
                for row in hist_data:
                    if row[close_idx] is not None:
                        closes.append(row[close_idx])
            if len(closes) >= 2 and closes[0] > 0:
                month_change = round(((closes[-1] - closes[0]) / closes[0]) * 100, 2)
    except Exception as e:
        logger.error(f"Ошибка получения истории {ticker}: {e}")

    return current_price, day_change, month_change

def get_consensus_forecast(ticker: str):
    """Запрашивает консенсус-прогноз аналитиков с MOEX ISS."""
    context = ssl._create_unverified_context()
    url = f"https://iss.moex.com/iss/cci/consensus/shares-price/{ticker}.json?iss.meta=off"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5, context=context) as response:
            data = json.loads(response.read().decode('utf-8'))
            sec_data = data.get('securities', {}).get('data', [])
            sec_cols = data.get('securities', {}).get('columns', [])
            if sec_data and sec_cols:
                row = dict(zip(sec_cols, sec_data[0]))
                target_price = row.get('target_price')
                recommendation = row.get('recommendation', 'Держать')
                date_str = row.get('date', '')
                return target_price, recommendation, date_str
    except Exception as e:
        logger.error(f"Ошибка прогноза для {ticker}: {e}")
    return None, None, None

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
            for item in root.findall('.//item'):
                title = item.find('title').text if item.find('title') is not None else ''
                link = item.find('link').text if item.find('link') is not None else ''
                summary = item.find('description').text if item.find('description') is not None else ''
                text_to_check = (title + " " + summary).lower()
                has_keyword = any(kw.lower() in text_to_check for kw in TICKER_MAP.keys())
                has_ignored = any(ig.lower() in text_to_check for ig in IGNORE_WORDS)
                if has_keyword and not has_ignored:
                    recent_news.append({"title": title, "link": link, "summary": summary})
        except Exception as e:
            logger.error(f"Ошибка загрузки RSS {feed_url}: {e}")
    return list({v['title']: v for v in recent_news}.values())

def format_news_message(news_item: dict) -> str:
    title = news_item.get("title", "Без заголовка")
    link = news_item.get("link", "")
    text_to_check = (title + " " + news_item.get("summary", "")).lower()
    score = analyze_russian_sentiment(text_to_check)

    emoji = "🟢 Позитив" if score > 0 else "🔴 Негатив" if score < 0 else "⚪ Нейтрально"

    stock_info = ""
    for name, ticker in TICKER_MAP.items():
        if name.lower() in text_to_check:
            price, day_change, month_change = get_stock_info(ticker)
            if price is not None:
                stock_info = f"📈 **{name}** ({ticker}): {price} ₽\n"
                if day_change is not None:
                    stock_info += f"   День: {'↗️' if day_change > 0 else '↘️' if day_change < 0 else '➖'} {day_change:+.2f}%\n"
                if month_change is not None:
                    stock_info += f"   Месяц: {'↗️' if month_change > 0 else '↘️' if month_change < 0 else '➖'} {month_change:+.2f}%\n"
            break
    return f"{emoji}\n\n{title}\n\n{stock_info}\nПодробнее: {link}"

def format_idea_message(name: str, ticker: str, current_price: float, target_price: float, recommendation: str, date_str: str) -> str:
    """Форматирует пост-идею с расчетом потенциальной доходности."""
    upside = ((target_price - current_price) / current_price) * 100
    direction = "▲ На рост" if upside > 0 else "▼ На падение"
    status_emoji = "🟢" if upside > 5 else "🟡" if upside > 0 else "🔴"
    
    return (
        f"💡 **ИНВЕСТИЦИОННАЯ ИДЕЯ**\n\n"
        f"🏢 **{name}** ({ticker})\n"
        f"📊 Рекомендация: {recommendation}\n"
        f"🎯 Целевая цена: {target_price} ₽\n"
        f"💰 Текущая цена: {current_price} ₽\n"
        f"📈 Потенциал: {upside:+.2f}%\n"
        f"🧭 Направление: {direction}\n"
        f"📅 Дата прогноза: {date_str}\n"
        f"Статус: {status_emoji}"
    )

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

def publish_ideas_digest():
    """Раз в сутки собирает топ-3 идеи по потенциалу роста и публикует."""
    logger.info("Сбор ежедневного дайджеста идей...")
    ideas = []
    for name, ticker in TICKER_MAP.items():
        target, rec, date_str = get_consensus_forecast(ticker)
        if target:
            current, _, _ = get_stock_info(ticker)
            if current:
                upside = ((target - current) / current) * 100
                ideas.append((name, ticker, current, target, rec, date_str, upside))
    
    if not ideas:
        logger.info("Идеи не найдены (нет консенсус-прогнозов).")
        return

    # Сортируем по потенциалу роста
    ideas.sort(key=lambda x: x[6], reverse=True)
    top_ideas = ideas[:3]

    text = "🔥 **ТОП-3 ИДЕИ АНАЛИТИКОВ НА СЕГОДНЯ**\n\n"
    for i, (name, ticker, current, target, rec, date_str, upside) in enumerate(top_ideas, 1):
        direction = "↗️" if upside > 0 else "↘️"
        text += f"{i}. **{name}** ({ticker})\n"
        text += f"   Цена: {current} ₽ → Цель: {target} ₽ ({direction} {upside:+.1f}%)\n"
        text += f"   Рекомендация: {rec} (от {date_str})\n\n"
    text += "⚠️ _Не является индивидуальной инвестиционной рекомендацией._"
    
    if post_to_vk_wall(text):
        logger.info("✅ Дайджест идей опубликован.")

def main():
    logger.info("Бот запущен. Проверка новостей и идей...")

    if not VK_TOKEN:
        logger.error("КРИТИЧЕСКАЯ ОШИБКА: Переменная VK_TOKEN не найдена!")
        os._exit(1)

    # 1. Публикация новостей
    seen_news = load_json_set(SEEN_FILE)
    news_items = fetch_russian_news()
    new_news = [item for item in news_items if item['link'] not in seen_news]
    
    alerts_sent = 0
    for item in new_news:
        message = format_news_message(item)
        if post_to_vk_wall(message):
            alerts_sent += 1
            seen_news.add(item['link'])
            time.sleep(1)
    if alerts_sent > 0:
        save_json_set(SEEN_FILE, seen_news)

    # 2. Публикация инвестиционных идей для упомянутых компаний
    seen_ideas = load_json_set(IDEAS_SEEN_FILE)
    for item in new_news:
        text_check = (item['title'] + " " + item['summary']).lower()
        for name, ticker in TICKER_MAP.items():
            if name.lower() in text_check:
                idea_key = f"{ticker}_{datetime.now().strftime('%Y-%m-%d')}"
                if idea_key in seen_ideas:
                    continue # Уже публиковали идею по этой бумаге сегодня

                target, rec, date_str = get_consensus_forecast(ticker)
                current, _, _ = get_stock_info(ticker)
                if target and current and target > current:
                    idea_msg = format_idea_message(name, ticker, current, target, rec, date_str)
                    if post_to_vk_wall(idea_msg):
                        logger.info(f"✅ Идея опубликована: {name}")
                        seen_ideas.add(idea_key)
                        alerts_sent += 1
                        time.sleep(1)
                break # Берем только одну компанию из новости
    save_json_set(IDEAS_SEEN_FILE, seen_ideas)

    # 3. Ежедневный дайджест идей (запускается только в определенный час, например, в 10:00)
    current_hour = datetime.now().hour
    today_str = datetime.now().strftime('%Y-%m-%d')
    digest_key = f"digest_{today_str}"
    
    if current_hour == 10 and digest_key not in seen_ideas:
        publish_ideas_digest()
        seen_ideas.add(digest_key)
        save_json_set(IDEAS_SEEN_FILE, seen_ideas)
        alerts_sent += 1

    logger.info(f"Работа завершена. Опубликовано постов: {alerts_sent}")
    os._exit(0)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Непредвиденная ошибка: {e}")
        os._exit(1)
