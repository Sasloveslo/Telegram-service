from telethon import TelegramClient

api_id = 
api_hash = ''
channel = 'https://t.me/'          # укажите username вашего канала

client = TelegramClient('session', api_id, api_hash)

async def main():
    await client.start()
    entity = await client.get_entity(channel)
    print(f"Видеокружки в канале {channel}:")
    async for msg in client.iter_messages(entity, limit=50):
        if msg.video_note:
            print(f"ID: {msg.id}")
    print("\nОбычные видео (если нужны):")
    async for msg in client.iter_messages(entity, limit=50):
        if msg.video and not msg.video_note:
            print(f"ID: {msg.id}")

with client:
    client.loop.run_until_complete(main())