import requests
from bs4 import BeautifulSoup
import time
import os
import logging
import json
import html # Для экранирования HTML символов
import random

# --- НАСТРОЙКИ ---


# URL страницы поиска на Gumtree UK с вашими параметрами (товар, радиус, локация и т.д.)
# ОБЯЗАТЕЛЬНО ЗАМЕНИТЕ НА СВОЙ URL!
GUMTREE_SEARCH_URL = 'https://www.gumtree.com/search?search_location=Glasgow&search_category=accordians&q=accordion&distance=100&sort=date&search_distance=100'

# Файл для хранения ID уже увиденных объявлений
SEEN_ADS_FILE = 'seen_gumtree_ads.json'

# Заголовки для запроса, чтобы имитировать браузер
REQUEST_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}
# --- КОНЕЦ НАСТРОЕК ---

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Проверка chat_id (простая)
try:
    if not str(TELEGRAM_CHAT_ID).lstrip('-').isdigit():
         raise ValueError("TELEGRAM_CHAT_ID должен быть числом (в виде строки или int).")
    logging.info(f"Уведомления будут отправляться в чат ID: {TELEGRAM_CHAT_ID}")
except ValueError as e:
    logging.error(f"Ошибка в TELEGRAM_CHAT_ID: {e}")
    exit()

def load_seen_ads():
    """Загружает ID виденных объявлений из файла."""
    if os.path.exists(SEEN_ADS_FILE):
        try:
            with open(SEEN_ADS_FILE, 'r') as f:
                return set(json.load(f))
        except (json.JSONDecodeError, IOError) as e:
            logging.error(f"Ошибка загрузки файла {SEEN_ADS_FILE}: {e}. Начинаем с пустого списка.")
            return set()
    return set()

def save_seen_ads(seen_ads_set):
    """Сохраняет ID виденных объявлений в файл."""
    try:
        with open(SEEN_ADS_FILE, 'w') as f:
            json.dump(list(seen_ads_set), f) # Сохраняем как список в JSON
    except IOError as e:
        logging.error(f"Не удалось сохранить файл {SEEN_ADS_FILE}: {e}")

def send_telegram_message_http(bot_token, chat_id, ad):
    """Отправляет отформатированное сообщение в Telegram через HTTP API."""

    # Экранируем потенциально опасные символы HTML в данных объявления
    safe_title = html.escape(ad['title'])
    safe_price = html.escape(ad['price'])
    safe_location = html.escape(ad['location'])
    # Ссылку обычно экранировать не нужно, но для параноиков можно html.escape(ad['link'], quote=True)

    message = (
        f"✨ <b>Новое объявление на Gumtree!</b>\n\n"
        f"<b>{safe_title}</b>\n\n"
        f"💰 <b>Цена:</b> {safe_price}\n"
        f"📍 <b>Локация:</b> {safe_location}\n\n"
        f'🔗 <a href="{ad["link"]}">Смотреть объявление</a>' # Используем HTML тег для ссылки
    )

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True # Отключаем превью ссылки для компактности
    }

    try:
        response = requests.post(url, data=payload, timeout=10) # Таймаут 10 секунд
        response.raise_for_status() # Проверка на HTTP ошибки (4xx, 5xx)
        response_json = response.json()

        if response_json.get("ok"):
            logging.info(f"Уведомление успешно отправлено для: {ad['title']}")
            return True
        else:
            logging.error(f"Ошибка от Telegram API: {response_json.get('description')}")
            logging.error(f"Полный ответ: {response_json}")
            return False

    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка при отправке запроса в Telegram API: {e}")
        return False
    except json.JSONDecodeError:
        logging.error(f"Не удалось декодировать JSON ответ от Telegram API. Ответ: {response.text}")
        return False


def fetch_and_parse_gumtree():
    """Загружает и парсит страницу поиска Gumtree."""
    logging.info(f"Запрашиваю URL: {GUMTREE_SEARCH_URL}")
    try:
        response = requests.get(GUMTREE_SEARCH_URL, headers=REQUEST_HEADERS, timeout=20) # Таймаут 20 сек
        response.raise_for_status() # Проверка на ошибки HTTP (вроде 404, 500)
        logging.info(f"Страница получена (Статус: {response.status_code})")
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка при запросе к Gumtree: {e}")
        return [] # Возвращаем пустой список при ошибке сети

    soup = BeautifulSoup(response.text, 'html.parser')
    ads_found = []

    # --- ИЗВЛЕЧЕНИЕ ОБЪЯВЛЕНИЙ ---
    # ЭТО САМАЯ ХРУПКАЯ ЧАСТЬ - СЕЛЕКТОРЫ МОГУТ ИЗМЕНИТЬСЯ!
    ad_containers = soup.select('article.listing-maxi') # Пример 1
    if not ad_containers:
         ad_containers = soup.select("article[data-q='search-result']") # Пример 2
         # Добавьте другие возможные селекторы, если нужно

    logging.info(f"Найдено {len(ad_containers)} контейнеров объявлений на странице.")

    for ad_container in ad_containers:
        try:
            # Ищем ссылку
            link_element = ad_container.select_one("a[data-q='search-result-anchor']")
            if not link_element or not link_element.has_attr('href'):
                logging.warning("Не найдена ссылка в контейнере объявления, пропускаем.")
                continue

            ad_link = link_element['href']
            if ad_link.startswith('/'):
                ad_link = 'https://www.gumtree.com' + ad_link
            ad_id = ad_link

            # Ищем заголовок
            title_element = ad_container.select_one("div[data-q='tile-title']")
            ad_title = title_element.text.strip() if title_element else 'N/A'

            # Ищем цену
            price_element = ad_container.select_one("div[data-testid='price']")
            ad_price = price_element.text.strip().replace('\n', ' ') if price_element else 'N/A'

            # Ищем локацию
            location_element = ad_container.select_one("div[data-q='tile-location']")
            ad_location = location_element.text.strip() if location_element else 'N/A'

            ads_found.append({
                'id': ad_id,
                'title': ad_title,
                'price': ad_price,
                'location': ad_location,
                'link': ad_link
            })
        except Exception as e:
            logging.warning(f"Ошибка парсинга отдельного объявления: {e}. Пропускаем.")
            continue

    logging.info(f"Успешно извлечено {len(ads_found)} объявлений.")
    return ads_found

# --- Основной цикл ---
if __name__ == "__main__":
    logging.info("Запуск мониторинга Gumtree (HTTP API)...")
    seen_ads = load_seen_ads()
    logging.info(f"Загружено {len(seen_ads)} ID ранее виденных объявлений.")

    while True:
        logging.info("Начинаю проверку...")
        current_ads = fetch_and_parse_gumtree()
        new_ads_found_this_run = []

        if not current_ads:
            logging.warning("Не удалось получить объявления с Gumtree в этой проверке.")
        else:
            for ad in current_ads:
                if ad['id'] not in seen_ads:
                    logging.info(f"Найдено новое объявление: {ad['title']} ({ad['id']})")
                    new_ads_found_this_run.append(ad)
                    seen_ads.add(ad['id']) # Добавляем в множество увиденных

            if new_ads_found_this_run:
                logging.info(f"Найдено {len(new_ads_found_this_run)} новых объявлений. Отправка уведомлений...")
                success_count = 0
                for ad in new_ads_found_this_run:
                    if send_telegram_message_http(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ad):
                        success_count += 1
                    time.sleep(1) # Небольшая пауза между отправками сообщений

                if success_count == len(new_ads_found_this_run):
                     logging.info("Все новые уведомления успешно отправлены.")
                else:
                     logging.warning(f"Успешно отправлено {success_count} из {len(new_ads_found_this_run)} уведомлений.")

                save_seen_ads(seen_ads) # Сохраняем обновленный список увиденных
            else:
                logging.info("Новых объявлений не найдено в этой проверке.")

        random_interval = random.randint(300, 1000) # Генерируем случайное число
        logging.info(f"Проверка завершена. Следующая проверка через {random_interval} секунд.")
        time.sleep(random_interval) # Используем случайное число для ожидания