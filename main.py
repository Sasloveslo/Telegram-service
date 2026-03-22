import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from telethon import TelegramClient, errors
from telethon.tl.types import Message

# Получить api_id и api_hash на https://my.telegram.org
API_ID = 123456  # замените на свой
API_HASH = 'your_api_hash_here'  # замените на свой

# Файлы
RECIPIENTS_FILE = 'recipients.txt'   # список получателей (по одному на строку)
VOICE_FILE = 'voice.ogg'             # путь к голосовому файлу
LOG_FILE = 'mailing.log'             # файл логов


DELAY_BETWEEN_SENDS = 360  # секунд (6 минут)
SCHEDULED_TIME = None 

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def load_recipients(file_path: str) -> list[str]:
    if not Path(file_path).exists():
        logger.error(f"Файл получателей не найден: {file_path}")
        return []

    with open(file_path, 'r', encoding='utf-8') as f:
        # Убираем пустые строки и пробелы
        recipients = [line.strip() for line in f if line.strip()]

    logger.info(f"Загружено {len(recipients)} получателей из {file_path}")
    return recipients

async def send_voice(client: TelegramClient, recipient: str, voice_path: str) -> bool:
    try:
        entity = await client.get_entity(recipient)
        await client.send_file(
            entity,
            voice_path,
            voice_note=True,
            caption=f"Голосовое сообщение от {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        logger.info(f"Отправлено -> {recipient} (ID: {entity.id})")
        return True
    except errors.FloodWaitError as e:
        logger.warning(f"Flood wait для {recipient}: нужно ждать {e.seconds} сек")
        await asyncio.sleep(e.seconds)
        return await send_voice(client, recipient, voice_path)
    except errors.RPCError as e:
        logger.error(f"Ошибка API для {recipient}: {e}")
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка для {recipient}: {e}")
        return False

async def scheduled_mailing(client: TelegramClient, recipients: list[str], voice_path: str,
                            delay: int, scheduled_time: datetime = None):
    if scheduled_time:
        now = datetime.now()
        if scheduled_time > now:
            wait_seconds = (scheduled_time - now).total_seconds()
            logger.info(f"Запланировано на {scheduled_time}. Ожидание {wait_seconds:.0f} секунд...")
            await asyncio.sleep(wait_seconds)
        else:
            logger.warning(f"Запланированное время {scheduled_time} уже прошло, начинаем немедленно.")

    success_count = 0
    fail_count = 0

    for i, recipient in enumerate(recipients, start=1):
        logger.info(f"[{i}/{len(recipients)}] Обработка: {recipient}")

        success = await send_voice(client, recipient, voice_path)
        if success:
            success_count += 1
        else:
            fail_count += 1
        if i < len(recipients):
            logger.info(f"Ожидание {delay // 60} минут перед следующим...")
            await asyncio.sleep(delay)

    logger.info(f"Рассылка завершена. Успешно: {success_count}, Ошибок: {fail_count}")

async def main():
    if not Path(VOICE_FILE).exists():
        logger.error(f"Голосовой файл не найден: {VOICE_FILE}")
        return

    recipients = load_recipients(RECIPIENTS_FILE)
    if not recipients:
        logger.error("Нет получателей для рассылки.")
        return

    client = TelegramClient('user_session', API_ID, API_HASH)

    try:
        await client.start()
        logger.info("Авторизация успешна.")

        start_time = None
        if SCHEDULED_TIME:
            try:
                start_time = datetime.strptime(SCHEDULED_TIME, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                logger.error("Неверный формат SCHEDULED_TIME. Ожидается YYYY-MM-DD HH:MM:SS")
                return

        await scheduled_mailing(client, recipients, VOICE_FILE,
                                DELAY_BETWEEN_SENDS, start_time)

    except errors.rpcerrorlist.ApiIdInvalidError:
        logger.error("Неверный API_ID или API_HASH. Проверьте настройки.")
    except Exception as e:
        logger.exception(f"Критическая ошибка: {e}")
    finally:
        await client.disconnect()
        logger.info("Сессия закрыта.")

if __name__ == '__main__':
    asyncio.run(main())