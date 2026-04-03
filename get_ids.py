from telethon import TelegramClient
from telethon.tl.types import DocumentAttributeVideo, DocumentAttributeAudio

api_id = 34531129 # 34531129 - LKS 
api_hash = 'afcccc31d4a493b7035809b5dfc09386' # afcccc31d4a493b7035809b5dfc09386 - LKS
chat_input = 'https://t.me/arteeeeimKokaraev'  # укажите ваш канал
limit = 50

client = TelegramClient('session', api_id, api_hash)

def get_message_type(message):
    if message.text:
        return "Текст"
    if message.video_note:
        return "Кружок"
    if message.video:
        return "Видео"
    if message.voice:
        return "Голосовое"
    if message.photo:
        return "Фото"
    if message.document:
        for attr in message.document.attributes:
            if isinstance(attr, DocumentAttributeVideo):
                if attr.round_message:
                    return "Кружок (документ)"
                else:
                    return "Видео (документ)"
            if isinstance(attr, DocumentAttributeAudio):
                if attr.voice:
                    return "Голосовое (документ)"
                else:
                    return "Аудио (музыка)"
        return "Документ"
    if message.sticker:
        return "Стикер"
    if message.poll:
        return "Опрос"
    if message.geo:
        return "Геопозиция"
    if message.contact:
        return "Контакт"
    return "Неизвестный тип"

async def main():
    await client.start()
    try:
        entity = await client.get_entity(chat_input)
    except Exception as e:
        print(f"Не удалось найти чат: {e}")
        return

    print(f"=== Последние {limit} сообщений из {chat_input} ===\n")
    async for msg in client.iter_messages(entity, limit=limit):
        msg_type = get_message_type(msg)
        content = msg.text or getattr(msg.file, 'name', '—')
        print(f"ID: {msg.id} | Тип: {msg_type} | Содержание: {content}")

with client:
    client.loop.run_until_complete(main())