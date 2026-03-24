import asyncio
import json
import logging
import random
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

import customtkinter as ctk
from telethon import TelegramClient, errors

# ==================== КОНФИГУРАЦИЯ ====================
CONFIG_FILE = "forwarder_config.json"
DEFAULT_CONFIG = {
    "api_id": "34531129",
    "api_hash": "afcccc31d4a493b7035809b5dfc09386",
    "recipients_file": "recipients.txt",
    "groups_file": "groups.txt",
    # Настройки для кружков (личные сообщения)
    "note_source_chat": "https://t.me/arteeeeimKokaraev",
    "note_auto_find": True,
    "note_message_ids": "4,3",
    # Настройки для видео (личные сообщения)
    "video_source_chat": "https://t.me/arteeeeimKokaraev",
    "video_auto_find": True,
    "video_message_ids": "5,6", # 5 - подкаст, 6 - эксперт
    "video_interval": 150,              # секунд между кружком и видео
    # Общие настройки
    "delay_between_sends": 360,         # сек между получателями
    "group_cycle_interval": 1800,       # сек для групп
    "group_message_text": "Я вообще андрей",
    "tz_offset": 3,                     # по умолчанию Москва
    "log_file": "forwarder.log",
    # Настройки для групп (пересылка сообщений)
    "group_source_chat": "https://t.me/programmmmmmer",           # чат-источник
    "group_auto_find": True,             # авто-поиск последнего
    "group_message_ids": "4",             # ID сообщений через запяту
}

logger = logging.getLogger("forwarder")
logger.setLevel(logging.INFO)


class ForwarderApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Telegram Forwarder")
        self.geometry("1100x800")
        self.minsize(900, 650)

        self.running = False
        self.task_thread = None
        self.client = None

        self.config = self.load_config()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)

        self.tab_settings = self.tabview.add("Настройки")
        self.tab_private = self.tabview.add("Личные сообщения")
        self.tab_groups = self.tabview.add("Группы")
        self.tab_logs = self.tabview.add("Логи")

        self.create_settings_tab()
        self.create_private_tab()
        self.create_groups_tab()
        self.create_logs_tab()

        self.button_frame = ctk.CTkFrame(self)
        self.button_frame.pack(side="bottom", fill="x", padx=10, pady=(0, 10))
        self.start_stop_button = ctk.CTkButton(self.button_frame, text="Запустить", command=self.toggle_start_stop)
        self.start_stop_button.pack(pady=5)

        self.setup_log_redirect()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    # ---------- Загрузка / сохранение конфига ----------
    def load_config(self):
        if Path(CONFIG_FILE).exists():
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                    return {**DEFAULT_CONFIG, **saved}
            except (json.JSONDecodeError, UnicodeDecodeError):
                print("Ошибка чтения конфига. Использую значения по умолчанию.")
        return DEFAULT_CONFIG.copy()

    def save_config(self):
        self.config.update({
            "api_id": self.api_id_entry.get(),
            "api_hash": self.api_hash_entry.get(),
            "recipients_file": self.recipients_file_entry.get(),
            "groups_file": self.groups_file_entry.get(),
            "note_source_chat": self.note_chat_entry.get(),
            "note_auto_find": self.note_auto_var.get(),
            "note_message_ids": self.note_ids_entry.get(),
            "video_source_chat": self.video_chat_entry.get(),
            "video_auto_find": self.video_auto_var.get(),
            "video_message_ids": self.video_ids_entry.get(),
            "video_interval": int(self.video_interval_entry.get()),
            "delay_between_sends": int(self.delay_entry.get()),
            "group_cycle_interval": int(self.group_interval_entry.get()),
            # "group_message_text": self.group_text_entry.get(),  <-- УДАЛИТЬ ЭТУ СТРОКУ
            "group_source_chat": self.group_chat_entry.get(),
            "group_auto_find": self.group_auto_var.get(),
            "group_message_ids": self.group_ids_entry.get(),
            "tz_offset": int(self.tz_entry.get()),
            "log_file": self.log_file_entry.get(),
        })
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=4, ensure_ascii=False)

    # ---------- Вкладка настроек ----------
    def create_settings_tab(self):
        row = 0
        ctk.CTkLabel(self.tab_settings, text="API ID:").grid(row=row, column=0, padx=10, pady=5, sticky="w")
        self.api_id_entry = ctk.CTkEntry(self.tab_settings, width=300)
        self.api_id_entry.grid(row=row, column=1, padx=10, pady=5)
        self.api_id_entry.insert(0, self.config.get("api_id", ""))
        row += 1

        ctk.CTkLabel(self.tab_settings, text="API Hash:").grid(row=row, column=0, padx=10, pady=5, sticky="w")
        self.api_hash_entry = ctk.CTkEntry(self.tab_settings, width=300)
        self.api_hash_entry.grid(row=row, column=1, padx=10, pady=5)
        self.api_hash_entry.insert(0, self.config.get("api_hash", ""))
        row += 1

        ctk.CTkLabel(self.tab_settings, text="Часовой пояс (смещение от UTC):").grid(row=row, column=0, padx=10, pady=5, sticky="w")
        self.tz_entry = ctk.CTkEntry(self.tab_settings, width=100)
        self.tz_entry.grid(row=row, column=1, padx=10, pady=5, sticky="w")
        self.tz_entry.insert(0, str(self.config.get("tz_offset", 3)))
        msk_time = datetime.utcnow() + timedelta(hours=3)
        ctk.CTkLabel(self.tab_settings, text=f"Текущее московское время: {msk_time.strftime('%Y-%m-%d %H:%M:%S')}").grid(row=row, column=2, padx=10, pady=5)
        row += 1

        ctk.CTkLabel(self.tab_settings, text="Файл получателей (ЛС):").grid(row=row, column=0, padx=10, pady=5, sticky="w")
        self.recipients_file_entry = ctk.CTkEntry(self.tab_settings, width=300)
        self.recipients_file_entry.grid(row=row, column=1, padx=10, pady=5)
        self.recipients_file_entry.insert(0, self.config.get("recipients_file", "recipients.txt"))
        row += 1

        ctk.CTkLabel(self.tab_settings, text="Файл групп:").grid(row=row, column=0, padx=10, pady=5, sticky="w")
        self.groups_file_entry = ctk.CTkEntry(self.tab_settings, width=300)
        self.groups_file_entry.grid(row=row, column=1, padx=10, pady=5)
        self.groups_file_entry.insert(0, self.config.get("groups_file", "groups.txt"))
        row += 1

        ctk.CTkLabel(self.tab_settings, text="Файл логов:").grid(row=row, column=0, padx=10, pady=5, sticky="w")
        self.log_file_entry = ctk.CTkEntry(self.tab_settings, width=300)
        self.log_file_entry.grid(row=row, column=1, padx=10, pady=5)
        self.log_file_entry.insert(0, self.config.get("log_file", "forwarder.log"))
        row += 1

        self.save_button = ctk.CTkButton(self.tab_settings, text="Сохранить настройки", command=self.save_config)
        self.save_button.grid(row=row, column=0, columnspan=2, padx=10, pady=20)

    # ---------- Вкладка личных сообщений ----------
    def create_private_tab(self):
        # Блок "Видеокружки"
        self.note_frame = ctk.CTkFrame(self.tab_private)
        self.note_frame.grid(row=0, column=0, columnspan=2, padx=10, pady=10, sticky="ew")
        ctk.CTkLabel(self.note_frame, text="Видеокружки:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.note_chat_entry = ctk.CTkEntry(self.note_frame, width=250)
        self.note_chat_entry.grid(row=0, column=1, padx=5, pady=5)
        self.note_chat_entry.insert(0, self.config.get("note_source_chat", "me"))
        self.note_auto_var = ctk.BooleanVar(value=self.config.get("note_auto_find", True))
        self.note_auto_check = ctk.CTkCheckBox(self.note_frame, text="авто-поиск последнего", variable=self.note_auto_var)
        self.note_auto_check.grid(row=0, column=2, padx=5, pady=5)
        ctk.CTkLabel(self.note_frame, text="ID сообщений (через запятую):").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.note_ids_entry = ctk.CTkEntry(self.note_frame, width=400)
        self.note_ids_entry.grid(row=1, column=1, columnspan=2, padx=5, pady=5, sticky="w")
        self.note_ids_entry.insert(0, self.config.get("note_message_ids", ""))

        # Блок "Видео"
        self.video_frame = ctk.CTkFrame(self.tab_private)
        self.video_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=10, sticky="ew")
        ctk.CTkLabel(self.video_frame, text="Видео (статичное):").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.video_chat_entry = ctk.CTkEntry(self.video_frame, width=250)
        self.video_chat_entry.grid(row=0, column=1, padx=5, pady=5)
        self.video_chat_entry.insert(0, self.config.get("video_source_chat", "me"))
        self.video_auto_var = ctk.BooleanVar(value=self.config.get("video_auto_find", True))
        self.video_auto_check = ctk.CTkCheckBox(self.video_frame, text="авто-поиск последнего", variable=self.video_auto_var)
        self.video_auto_check.grid(row=0, column=2, padx=5, pady=5)
        ctk.CTkLabel(self.video_frame, text="ID сообщений (через запятую):").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.video_ids_entry = ctk.CTkEntry(self.video_frame, width=400)
        self.video_ids_entry.grid(row=1, column=1, columnspan=2, padx=5, pady=5, sticky="w")
        self.video_ids_entry.insert(0, self.config.get("video_message_ids", ""))

        # Интервал между кружком и видео
        ctk.CTkLabel(self.tab_private, text="Интервал до видео (сек, min=60):").grid(row=2, column=0, padx=10, pady=5, sticky="w")
        self.video_interval_entry = ctk.CTkEntry(self.tab_private, width=100)
        self.video_interval_entry.grid(row=2, column=1, padx=10, pady=5, sticky="w")
        self.video_interval_entry.insert(0, str(self.config.get("video_interval", 150)))

        # Интервал между получателями
        ctk.CTkLabel(self.tab_private, text="Интервал между сообщениями (сек):").grid(row=3, column=0, padx=10, pady=5, sticky="w")
        self.delay_entry = ctk.CTkEntry(self.tab_private, width=100)
        self.delay_entry.grid(row=3, column=1, padx=10, pady=5, sticky="w")
        self.delay_entry.insert(0, str(self.config.get("delay_between_sends", 360)))

        # Время первого сообщения
        ctk.CTkLabel(self.tab_private, text="Время первого сообщения (HH:MM или YYYY-MM-DD HH:MM:SS):").grid(row=4, column=0, padx=10, pady=5, sticky="w")
        self.start_time_entry = ctk.CTkEntry(self.tab_private, width=300)
        self.start_time_entry.grid(row=4, column=1, padx=10, pady=5)
        self.start_time_entry.insert(0, "")

        # Редактор получателей
        ctk.CTkLabel(self.tab_private, text="Редактировать список получателей:").grid(row=5, column=0, padx=10, pady=5, sticky="w")
        self.recipients_text = ctk.CTkTextbox(self.tab_private, height=200, wrap="none")
        self.recipients_text.grid(row=6, column=0, columnspan=2, padx=10, pady=5, sticky="nsew")
        self.tab_private.grid_rowconfigure(6, weight=1)
        self.tab_private.grid_columnconfigure(1, weight=1)
        self.load_recipients_into_text()

        self.save_recipients_button = ctk.CTkButton(self.tab_private, text="Сохранить получателей", command=self.save_recipients)
        self.save_recipients_button.grid(row=7, column=0, columnspan=2, padx=10, pady=5)

    def load_recipients_into_text(self):
        file_path = self.recipients_file_entry.get()
        if Path(file_path).exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                self.recipients_text.delete("1.0", "end")
                self.recipients_text.insert("1.0", f.read())
        else:
            self.recipients_text.delete("1.0", "end")

    def save_recipients(self):
        content = self.recipients_text.get("1.0", "end-1c")
        file_path = self.recipients_file_entry.get()
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        self.log("Получатели сохранены в файл.")

    # ---------- Вкладка групп ----------
    def create_groups_tab(self):
        # Блок "Источник сообщения для пересылки"
        self.source_frame = ctk.CTkFrame(self.tab_groups)
        self.source_frame.grid(row=0, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
        
        ctk.CTkLabel(self.source_frame, text="Чат-источник:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.group_chat_entry = ctk.CTkEntry(self.source_frame, width=250)
        self.group_chat_entry.grid(row=0, column=1, padx=5, pady=5)
        self.group_chat_entry.insert(0, self.config.get("group_source_chat", "me"))
        
        self.group_auto_var = ctk.BooleanVar(value=self.config.get("group_auto_find", True))
        self.group_auto_check = ctk.CTkCheckBox(self.source_frame, text="авто-поиск последнего", variable=self.group_auto_var)
        self.group_auto_check.grid(row=0, column=2, padx=5, pady=5)
        
        ctk.CTkLabel(self.source_frame, text="ID сообщений (через запятую):").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.group_ids_entry = ctk.CTkEntry(self.source_frame, width=400)
        self.group_ids_entry.grid(row=1, column=1, columnspan=2, padx=5, pady=5, sticky="w")
        self.group_ids_entry.insert(0, self.config.get("group_message_ids", ""))

        # Блок "Интервал между циклами"
        ctk.CTkLabel(self.tab_groups, text="Интервал между циклами (сек):").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.group_interval_entry = ctk.CTkEntry(self.tab_groups, width=100)
        self.group_interval_entry.grid(row=1, column=1, padx=10, pady=5, sticky="w")
        self.group_interval_entry.insert(0, str(self.config.get("group_cycle_interval", 720)))

        # Редактор списка групп
        ctk.CTkLabel(self.tab_groups, text="Редактировать список групп:").grid(row=2, column=0, padx=10, pady=5, sticky="w")
        self.groups_text = ctk.CTkTextbox(self.tab_groups, height=200, wrap="none")
        self.groups_text.grid(row=3, column=0, columnspan=2, padx=10, pady=5, sticky="nsew")
        self.tab_groups.grid_rowconfigure(3, weight=1)
        self.tab_groups.grid_columnconfigure(1, weight=1)
        self.load_groups_into_text()

        self.save_groups_button = ctk.CTkButton(self.tab_groups, text="Сохранить группы", command=self.save_groups)
        self.save_groups_button.grid(row=4, column=0, columnspan=2, padx=10, pady=5)

    def load_groups_into_text(self):
        file_path = self.groups_file_entry.get()
        if Path(file_path).exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                self.groups_text.delete("1.0", "end")
                self.groups_text.insert("1.0", f.read())
        else:
            self.groups_text.delete("1.0", "end")

    def save_groups(self):
        content = self.groups_text.get("1.0", "end-1c")
        file_path = self.groups_file_entry.get()
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        self.log("Группы сохранены в файл.")

    # ---------- Вкладка логов ----------
    def create_logs_tab(self):
        self.log_text = ctk.CTkTextbox(self.tab_logs, wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=10, pady=10)

    def setup_log_redirect(self):
        class TextHandler(logging.Handler):
            def __init__(self, app):
                super().__init__()
                self.app = app
                self.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

            def emit(self, record):
                msg = self.format(record)
                self.app.log(msg)

        handler = TextHandler(self)
        logger.addHandler(handler)
        log_file = self.log_file_entry.get()
        if log_file:
            try:
                file_handler = logging.FileHandler(log_file, encoding='utf-8')
                file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
                logger.addHandler(file_handler)
            except Exception as e:
                self.log(f"Не удалось создать файл логов: {e}")

    def log(self, message):
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.update_idletasks()

    # ---------- Управление запуском ----------
    def toggle_start_stop(self):
        if self.running:
            self.stop_mailing()
        else:
            self.start_mailing()

    def start_mailing(self):
        self.save_config()
        self.save_recipients()
        self.save_groups()

        if not self.api_id_entry.get() or not self.api_hash_entry.get():
            self.log("Ошибка: не указаны API ID и/или API Hash")
            return

        self.running = True
        self.start_stop_button.configure(text="Остановить")
        self.log("Запуск рассылки...")
        self.task_thread = threading.Thread(target=self.run_async_loop, daemon=True)
        self.task_thread.start()

    def stop_mailing(self):
        self.running = False
        self.log("Остановка рассылки...")

    def run_async_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.async_main())
        except Exception as e:
            self.log(f"Критическая ошибка: {e}")
        finally:
            loop.close()
            self.after(0, lambda: self.start_stop_button.configure(text="Запустить"))
            self.running = False

    async def async_main(self):
        api_id = int(self.api_id_entry.get())
        api_hash = self.api_hash_entry.get()
        tz_offset = int(self.tz_entry.get())
        mode = self.tabview.get()  # "Личные сообщения" или "Группы"

        if mode == "Личные сообщения":
            await self.run_private_mode(api_id, api_hash, tz_offset)
        else:
            await self.run_groups_mode(api_id, api_hash, tz_offset)

    # ---------- Режим личных сообщений ----------
    async def run_private_mode(self, api_id, api_hash, tz_offset):
        recipients_file = self.recipients_file_entry.get()
        recipients = self.load_recipients(recipients_file)
        if not recipients:
            self.log("Нет получателей для рассылки ЛС.")
            return

        client = TelegramClient('user_session', api_id, api_hash)
        self.client = client
        try:
            await client.start()
            self.log("Авторизация успешна.")

            note_messages = await self.get_source_messages(
                client,
                self.note_chat_entry.get(),
                self.note_auto_var.get(),
                self.note_ids_entry.get()
            )
            if not note_messages:
                self.log("Не удалось получить ни одного видеокружка. Отмена.")
                return

            video_messages = await self.get_source_messages(
                client,
                self.video_chat_entry.get(),
                self.video_auto_var.get(),
                self.video_ids_entry.get()
            )
            video_interval = int(self.video_interval_entry.get())
            if not video_messages:
                self.log("Видео не найдены, отправка только кружков.")
                video_interval = 0

            delay = int(self.delay_entry.get())
            first_time = self.parse_start_time(self.start_time_entry.get())

            await self.schedule_forward_to_recipients(
                client, recipients,
                note_messages, video_messages,
                delay, first_time, tz_offset, video_interval
            )
        except errors.rpcerrorlist.ApiIdInvalidError:
            self.log("Неверный API_ID или API_HASH.")
        except Exception as e:
            self.log(f"Ошибка в режиме ЛС: {e}")
        finally:
            await client.disconnect()
            self.client = None
            self.log("Сессия закрыта.")

    def load_recipients(self, file_path):
        if not Path(file_path).exists():
            self.log(f"Файл получателей не найден: {file_path}")
            return []
        with open(file_path, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip()]

    async def get_source_messages(self, client, chat, auto_find, ids_str):
        try:
            entity = await client.get_entity(chat)
        except Exception as e:
            self.log(f"Не удалось получить сущность {chat}: {e}")
            return []

        if auto_find and not ids_str:
            self.log(f"Поиск последнего сообщения в {chat}...")
            async for msg in client.iter_messages(entity, limit=1):
                if msg:
                    self.log(f"Найдено сообщение ID={msg.id}")
                    return [msg]
            return []
        elif ids_str:
            ids = [int(x.strip()) for x in ids_str.split(',') if x.strip()]
            messages = []
            for mid in ids:
                msg = await client.get_messages(entity, ids=mid)
                if msg:
                    messages.append(msg)
                else:
                    self.log(f"Сообщение {mid} не найдено в {chat}")
            return messages
        return []

    def parse_start_time(self, time_str):
        if not time_str:
            return None
        try:
            # Попытка HH:MM
            now = datetime.now()
            hour_min = datetime.strptime(time_str, "%H:%M")
            result = now.replace(hour=hour_min.hour, minute=hour_min.minute, second=0, microsecond=0)
            if result < now:
                result += timedelta(days=1)
            return result
        except ValueError:
            try:
                return datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                self.log("Неверный формат времени первого сообщения, используется текущее время + интервал")
                return None

    async def schedule_forward_to_recipients(self, client, recipients, note_msgs, video_msgs, delay, first_time, tz_offset, video_interval):
        success_notes = 0
        fail_notes = 0
        success_videos = 0
        fail_videos = 0
        total = len(recipients)

        now = datetime.now()
        if first_time and first_time > now:
            first_schedule = first_time
        else:
            first_schedule = now + timedelta(seconds=delay)

        for i, recipient in enumerate(recipients, start=1):
            schedule_time = first_schedule + timedelta(seconds=(i-1)*delay)
            schedule_time_utc = schedule_time - timedelta(hours=tz_offset)
            display_time = schedule_time

            self.log(f"[{i}/{total}] Планирование для {recipient} на {display_time.strftime('%Y-%m-%d %H:%M:%S')}")

            # 1. Отправка кружка (выбираем случайный из списка)
            note_msg = random.choice(note_msgs)
            if note_msg:
                try:
                    entity = await client.get_entity(recipient)
                    await client.forward_messages(
                        entity,
                        note_msg,
                        drop_author=True,
                        schedule=schedule_time_utc
                    )
                    success_notes += 1
                except errors.FloodWaitError as e:
                    self.log(f"Flood wait для {recipient}: ждём {e.seconds} сек")
                    await asyncio.sleep(e.seconds)
                    try:
                        entity = await client.get_entity(recipient)
                        await client.forward_messages(entity, note_msg, drop_author=True, schedule=schedule_time_utc)
                        success_notes += 1
                    except Exception as e2:
                        self.log(f"Ошибка при повторной отправке кружка {recipient}: {e2}")
                        fail_notes += 1
                except Exception as e:
                    self.log(f"Ошибка планирования кружка {recipient}: {e}")
                    fail_notes += 1
            else:
                fail_notes += 1

            # 2. Отправка видео, если интервал > 0 и есть видео
            if video_interval > 0 and video_msgs:
                video_schedule_time = schedule_time + timedelta(seconds=video_interval)
                video_schedule_utc = video_schedule_time - timedelta(hours=tz_offset)
                video_display = video_schedule_time
                video_msg = random.choice(video_msgs)
                try:
                    entity = await client.get_entity(recipient)
                    await client.forward_messages(
                        entity,
                        video_msg,
                        drop_author=True,
                        schedule=video_schedule_utc
                    )
                    success_videos += 1
                    self.log(f"  Видео запланировано на {video_display.strftime('%Y-%m-%d %H:%M:%S')}")
                except errors.FloodWaitError as e:
                    self.log(f"Flood wait для видео {recipient}: ждём {e.seconds} сек")
                    await asyncio.sleep(e.seconds)
                    try:
                        entity = await client.get_entity(recipient)
                        await client.forward_messages(entity, video_msg, drop_author=True, schedule=video_schedule_utc)
                        success_videos += 1
                    except Exception as e2:
                        self.log(f"Ошибка при повторной отправке видео {recipient}: {e2}")
                        fail_videos += 1
                except Exception as e:
                    self.log(f"Ошибка планирования видео {recipient}: {e}")
                    fail_videos += 1

        self.log(f"Планирование завершено. Кружки: успешно {success_notes}, ошибок {fail_notes}. Видео: успешно {success_videos}, ошибок {fail_videos}")

    # ---------- Режим групп ----------
    async def run_groups_mode(self, api_id, api_hash, tz_offset):
        """
        Режим групп: бесконечно пересылает случайное сообщение из указанного чата
        во все группы через заданный интервал.
        """
        # Загружаем список групп
        groups_file = self.groups_file_entry.get()
        groups = self.load_groups(groups_file)
        if not groups:
            self.log("Нет групп для рассылки.")
            return

        # Интервал между циклами
        cycle_interval = int(self.group_interval_entry.get())
        if cycle_interval <= 0:
            self.log("Интервал между циклами должен быть больше 0.")
            return

        # Создаём клиент
        self.client = TelegramClient('user_session', api_id, api_hash)
        try:
            await self.client.start()
            self.log("Авторизация успешна.")

            # Получаем сообщения-источники из указанного чата
            source_chat = self.group_chat_entry.get()
            auto_find = self.group_auto_var.get()
            ids_str = self.group_ids_entry.get()

            source_messages = await self.get_source_messages(
                self.client,
                source_chat,
                auto_find,
                ids_str
            )

            if not source_messages:
                self.log(f"Не удалось получить ни одного сообщения из чата {source_chat}. Отмена.")
                return

            self.log(f"Загружено {len(source_messages)} сообщений-источников (ID: {', '.join(str(m.id) for m in source_messages)}).")

            # Запускаем бесконечную рассылку с пересылкой
            await self.infinite_scheduled_group_mailing(
                self.client,
                groups,
                source_messages,
                cycle_interval,
                tz_offset
            )

        except errors.rpcerrorlist.ApiIdInvalidError:
            self.log("Неверный API_ID или API_HASH.")
        except Exception as e:
            self.log(f"Ошибка в режиме групп: {e}")
        finally:
            if self.client:
                await self.client.disconnect()
                self.client = None
            self.log("Сессия закрыта.")

    def load_groups(self, file_path):
        if not Path(file_path).exists():
            self.log(f"Файл групп не найден: {file_path}")
            return []
        with open(file_path, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip()]

    async def infinite_scheduled_group_mailing(self, client, groups, source_messages, cycle_interval, tz_offset):
        cycle_num = 1
        schedule_delta = timedelta(seconds=cycle_interval)

        while self.running:
            self.log(f"=== Цикл {cycle_num} ===")
            # Выбираем случайное сообщение для этого цикла
            source_msg = random.choice(source_messages)
            self.log(f"Выбрано сообщение ID={source_msg.id} из чата {source_msg.chat_id}")
            for group in groups:
                if not self.running:
                    break
                await self.forward_scheduled_message(client, group, source_msg, schedule_delta, tz_offset)
                await asyncio.sleep(1)

            if not self.running:
                break

            next_cycle_time = datetime.now() + schedule_delta
            next_cycle_local = next_cycle_time + timedelta(hours=tz_offset)
            self.log(f"Цикл {cycle_num} завершён. Следующий цикл в {next_cycle_local.strftime('%Y-%m-%d %H:%M:%S')} (через {cycle_interval // 60} минут).")
            for _ in range(cycle_interval // 5):
                if not self.running:
                    break
                await asyncio.sleep(5)
            if not self.running:
                break
            cycle_num += 1

    async def forward_scheduled_message(self, client, group, source_msg, schedule_delta, tz_offset):
        max_retries = 5
        for attempt in range(max_retries):
            try:
                entity = await client.get_entity(group)
                schedule_time_utc = datetime.utcnow() + schedule_delta
                await client.forward_messages(
                    entity,
                    source_msg,
                    drop_author=True,
                    schedule=schedule_time_utc
                )
                display_time = schedule_time_utc + timedelta(hours=tz_offset)
                self.log(f"Сообщение ID={source_msg.id} запланировано в группу {group} на {display_time.strftime('%H:%M:%S')}")
                break
            except errors.FloodWaitError as e:
                self.log(f"Flood wait для {group}: ждём {e.seconds} сек (попытка {attempt+1})")
                await asyncio.sleep(e.seconds)
            except Exception as e:
                self.log(f"Ошибка при планировании в группу {group}: {e}")
                break

    async def send_scheduled_message(self, client, group, text, schedule_delta, tz_offset):
        max_retries = 5
        for attempt in range(max_retries):
            try:
                entity = await client.get_entity(group)
                schedule_time_utc = datetime.utcnow() + schedule_delta
                await client.send_message(entity, text, schedule=schedule_time_utc)
                display_time = schedule_time_utc + timedelta(hours=tz_offset)
                self.log(f"Сообщение запланировано в группу {group} на {display_time.strftime('%H:%M:%S')}")
                break
            except errors.FloodWaitError as e:
                self.log(f"Flood wait для {group}: ждём {e.seconds} сек (попытка {attempt+1})")
                await asyncio.sleep(e.seconds)
            except Exception as e:
                self.log(f"Ошибка при планировании в группу {group}: {e}")
                break

    def on_closing(self):
        if self.running and self.task_thread and self.task_thread.is_alive():
            self.task_thread.join(timeout=2)
        self.destroy()


if __name__ == "__main__":
    app = ForwarderApp()
    app.mainloop()