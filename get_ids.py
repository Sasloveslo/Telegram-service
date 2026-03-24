from telethon import TelegramClient

api_id = 34531129
api_hash = 'afcccc31d4a493b7035809b5dfc09386'
channel = 'https://t.me/programmmmmmer'          # укажите username канала

client = TelegramClient('session', api_id, api_hash)

async def main():
    await client.start()
    entity = await client.get_entity(channel)
    print(f"Сообщения с текстом и фото в канале {channel}:")
    count = 0
    async for msg in client.iter_messages(entity, limit=100):
        # Проверяем, есть ли текст и есть ли фото
        if msg.text and msg.photo:
            print(f"ID: {msg.id} (текст: {msg.text[:50]}...)")
            count += 1
    print(f"\nВсего найдено сообщений с текстом и фото: {count}")

    # Если нужны сообщения с фото (даже без текста) — раскомментируйте:
    # print("\nСообщения с фото (любые):")
    # async for msg in client.iter_messages(entity, limit=100):
    #     if msg.photo:
    #         print(f"ID: {msg.id}")

with client:
    client.loop.run_until_complete(main())