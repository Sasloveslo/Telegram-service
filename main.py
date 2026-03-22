import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

from telethon import TelegramClient, errors
from telethon.tl.types import Message

# ==================== НАСТРОЙКИ ====================
# Получить api_id и api_hash на https://my.telegram.org
API_ID = 123
API_HASH = '123'

# Файл со списком получателей (по одному на строку)
RECIPIENTS_FILE = 'recipients.txt'

# Источник сообщения, которое будем пересылать
# Можно указать:
#   - username (без @)
#   - ссылку t.me/...
#   - 'me' для избранного
#   - числовой ID чата
SOURCE_CHAT = 'me'                 # чат, где находится исходное сообщение
SOURCE_MESSAGE_ID = None           # ID сообщения (если None, используем авто-поиск)

# Если не знаете ID, установите AUTO_FIND_LAST_VIDEO_NOTE = True
# Тогда будет использовано последнее видеосообщение в SOURCE_CHAT
AUTO_FIND_LAST_VIDEO_NOTE = True   # если True, SOURCE_MESSAGE_ID игнорируется

# Настройки рассылки
DELAY_BETWEEN_SENDS = 360          # секунд (6 минут)
SCHEDULED_TIME = None              # например "2026-03-23 10:00:00"
LOG_FILE = 'mailing.log'

# ==================== ЛОГИРОВАНИЕ ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ==================== ФУНКЦИИ ====================
def load_recipients(file_path: str) -> list[str]:
    """Загружает список получателей из файла."""
    if not Path(file_path).exists():
        logger.error(f"Файл получателей не найден: {file_path}")
        return []

    with open(file_path, 'r', encoding='utf-8') as f:
        recipients = [line.strip() for line in f if line.strip()]

    logger.info(f"Загружено {len(recipients)} получателей из {file_path}")
    return recipients


async def get_source_message(client: TelegramClient, chat, message_id=None, auto_find=False):
    try:
        source_entity = await client.get_entity(chat)
    except Exception as e:
        logger.error(f"Не удалось получить сущность источника: {e}")
        return None

    if auto_find:
        logger.info(f"Поиск последнего видеокружка в {chat}...")
        async for msg in client.iter_messages(source_entity):
            if msg.video_note:
                logger.info(f"Найдено сообщение ID={msg.id}")
                return msg
        logger.error("Видеокружков в указанном чате не найдено.")
        return None
    else:
        if not message_id:
            logger.error("Не указан ID сообщения для пересылки")
            return None
        try:
            msg = await client.get_messages(source_entity, ids=message_id)
            if msg:
                if msg.video_note:
                    logger.info(f"Загружено сообщение ID={msg.id} (видеокружок)")
                else:
                    logger.warning(f"Сообщение ID={message_id} не является видеокружком, но будет переслано")
                return msg
            else:
                logger.error(f"Сообщение ID={message_id} не найдено в {chat}")
                return None
        except Exception as e:
            logger.error(f"Ошибка при получении сообщения: {e}")
            return None


async def forward_to_recipients(client, recipients, source_msg, delay):
    success_count = 0
    fail_count = 0

    for i, recipient in enumerate(recipients, start=1):
        logger.info(f"[{i}/{len(recipients)}] Обработка: {recipient}")

        try:
            entity = await client.get_entity(recipient)
            await client.forward_messages(
                entity,
                source_msg,
                drop_author=True   # убирает имя автора исходного сообщения
            )
            logger.info(f"Переслано -> {recipient} (ID: {entity.id})")
            success_count += 1

        except errors.FloodWaitError as e:
            logger.warning(f"Flood wait для {recipient}: нужно ждать {e.seconds} сек")
            await asyncio.sleep(e.seconds)
            # Повторяем отправку после ожидания
            try:
                entity = await client.get_entity(recipient)
                await client.forward_messages(entity, source_msg, drop_author=True)
                logger.info(f"Повторно переслано -> {recipient} (ID: {entity.id})")
                success_count += 1
            except Exception as e2:
                logger.error(f"Ошибка при повторной отправке {recipient}: {e2}")
                fail_count += 1

        except errors.RPCError as e:
            logger.error(f"Ошибка API для {recipient}: {e}")
            fail_count += 1
        except Exception as e:
            logger.error(f"Неизвестная ошибка для {recipient}: {e}")
            fail_count += 1

        # Интервал между отправками (кроме последнего)
        if i < len(recipients):
            logger.info(f"Ожидание {delay // 60} минут перед следующим...")
            await asyncio.sleep(delay)

    logger.info(f"Рассылка завершена. Успешно: {success_count}, Ошибок: {fail_count}")


async def scheduled_mailing(client, recipients, source_msg, delay, scheduled_time=None):

    if scheduled_time:
        now = datetime.now()
        if scheduled_time > now:
            wait_seconds = (scheduled_time - now).total_seconds()
            logger.info(f"Запланировано на {scheduled_time}. Ожидание {wait_seconds:.0f} секунд...")
            await asyncio.sleep(wait_seconds)
        else:
            logger.warning(f"Запланированное время {scheduled_time} уже прошло, начинаем немедленно.")

    await forward_to_recipients(client, recipients, source_msg, delay)


async def main():
    recipients = load_recipients(RECIPIENTS_FILE)
    if not recipients:
        logger.error("Нет получателей для рассылки.")
        return

    client = TelegramClient('user_session', API_ID, API_HASH)

    try:
        await client.start()
        logger.info("Авторизация успешна.")
        source_msg = await get_source_message(
            client,
            chat=SOURCE_CHAT,
            message_id=SOURCE_MESSAGE_ID,
            auto_find=AUTO_FIND_LAST_VIDEO_NOTE
        )
        if source_msg is None:
            logger.error("Не удалось получить сообщение для пересылки. Завершение.")
            return

        # Планирование времени
        start_time = None
        if SCHEDULED_TIME:
            try:
                start_time = datetime.strptime(SCHEDULED_TIME, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                logger.error("Неверный формат SCHEDULED_TIME. Ожидается YYYY-MM-DD HH:MM:SS")
                return

        # Запуск рассылки
        await scheduled_mailing(client, recipients, source_msg, DELAY_BETWEEN_SENDS, start_time)

    except errors.rpcerrorlist.ApiIdInvalidError:
        logger.error("Неверный API_ID или API_HASH. Проверьте настройки.")
    except Exception as e:
        logger.exception(f"Критическая ошибка: {e}")
    finally:
        await client.disconnect()
        logger.info("Сессия закрыта.")


if __name__ == '__main__':
    asyncio.run(main())