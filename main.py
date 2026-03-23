import asyncio
import json
import logging
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

import customtkinter as ctk
from telethon import TelegramClient, errors

# ==================== КОНФИГУРАЦИЯ ====================
CONFIG_FILE = "forwarder_config.json"
DEFAULT_CONFIG = {
    "api_id": "",
    "api_hash": "",
    "recipients_file": "recipients.txt",
    "groups_file": "groups.txt",
    "source_chat": "me", #me - ИЗБРАННОЕ
    "source_message_id": "", # - если пусотое, то самое последнее 
    "auto_find_video_note": True,
    "delay_between_sends": 360,        # сек для ЛС интервала
    "group_cycle_interval": 1800,       # сек для групп
    "group_message_text": "Я вообще андрей",
    "tz_offset": 3,                    # по умолчанию Москва
    "log_file": "forwarder.log"
}

logger = logging.getLogger("forwarder")
logger.setLevel(logging.INFO)

class ForwarderApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Telegram Forwarder")
        self.geometry("1100x750")
        self.minsize(900, 600)

        self.running = False
        self.task_thread = None
        self.loop = None
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

    def load_config(self):
        if Path(CONFIG_FILE).exists():
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                return {**DEFAULT_CONFIG, **saved}
        return DEFAULT_CONFIG.copy()

    def save_config(self):
        self.config["api_id"] = self.api_id_entry.get()
        self.config["api_hash"] = self.api_hash_entry.get()
        self.config["recipients_file"] = self.recipients_file_entry.get()
        self.config["groups_file"] = self.groups_file_entry.get()
        self.config["source_chat"] = self.source_chat_entry.get()
        self.config["auto_find_video_note"] = self.auto_find_var.get()
        if not self.auto_find_var.get():
            self.config["source_message_id"] = self.source_msg_id_entry.get()
        else:
            self.config["source_message_id"] = ""
        self.config["delay_between_sends"] = int(self.delay_entry.get())
        self.config["group_cycle_interval"] = int(self.group_interval_entry.get())
        self.config["group_message_text"] = self.group_text_entry.get()
        self.config["tz_offset"] = int(self.tz_entry.get())
        self.config["log_file"] = self.log_file_entry.get()

        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=4, ensure_ascii=False)

    def create_settings_tab(self):
        ctk.CTkLabel(self.tab_settings, text="API ID:").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.api_id_entry = ctk.CTkEntry(self.tab_settings, width=300)
        self.api_id_entry.grid(row=0, column=1, padx=10, pady=5)
        self.api_id_entry.insert(0, self.config.get("api_id", ""))

        ctk.CTkLabel(self.tab_settings, text="API Hash:").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.api_hash_entry = ctk.CTkEntry(self.tab_settings, width=300)
        self.api_hash_entry.grid(row=1, column=1, padx=10, pady=5)
        self.api_hash_entry.insert(0, self.config.get("api_hash", ""))

        ctk.CTkLabel(self.tab_settings, text="Часовой пояс (смещение от UTC):").grid(row=2, column=0, padx=10, pady=5, sticky="w")
        self.tz_entry = ctk.CTkEntry(self.tab_settings, width=100)
        self.tz_entry.grid(row=2, column=1, padx=10, pady=5, sticky="w")
        self.tz_entry.insert(0, str(self.config.get("tz_offset", 3)))
        msk_time = datetime.utcnow() + timedelta(hours=3)
        self.tz_info_label = ctk.CTkLabel(self.tab_settings, text=f"ВВодите ВРЕМЯ НА УСТРОЙСТВЕ А НЕ ПО ГОРОДУ.Текущее московское время: {msk_time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.tz_info_label.grid(row=2, column=2, padx=10, pady=5)


        ctk.CTkLabel(self.tab_settings, text="Файл получателей (ЛС):").grid(row=3, column=0, padx=10, pady=5, sticky="w")
        self.recipients_file_entry = ctk.CTkEntry(self.tab_settings, width=300)
        self.recipients_file_entry.grid(row=3, column=1, padx=10, pady=5)
        self.recipients_file_entry.insert(0, self.config.get("recipients_file", "recipients.txt"))

        ctk.CTkLabel(self.tab_settings, text="Файл групп:").grid(row=4, column=0, padx=10, pady=5, sticky="w")
        self.groups_file_entry = ctk.CTkEntry(self.tab_settings, width=300)
        self.groups_file_entry.grid(row=4, column=1, padx=10, pady=5)
        self.groups_file_entry.insert(0, self.config.get("groups_file", "groups.txt"))

        ctk.CTkLabel(self.tab_settings, text="Файл логов:").grid(row=5, column=0, padx=10, pady=5, sticky="w")
        self.log_file_entry = ctk.CTkEntry(self.tab_settings, width=300)
        self.log_file_entry.grid(row=5, column=1, padx=10, pady=5)
        self.log_file_entry.insert(0, self.config.get("log_file", "forwarder.log"))

        self.save_button = ctk.CTkButton(self.tab_settings, text="Сохранить настройки", command=self.save_config)
        self.save_button.grid(row=6, column=0, columnspan=2, padx=10, pady=20)


    def create_private_tab(self):
        ctk.CTkLabel(self.tab_private, text="Чат-источник:").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.source_chat_entry = ctk.CTkEntry(self.tab_private, width=300)
        self.source_chat_entry.grid(row=0, column=1, padx=10, pady=5)
        self.source_chat_entry.insert(0, self.config.get("source_chat", "me"))

        self.auto_find_var = ctk.BooleanVar(value=self.config.get("auto_find_video_note", True))
        self.auto_find_check = ctk.CTkCheckBox(
            self.tab_private, text="Автоматически найти последний видеокружок",
            variable=self.auto_find_var, command=self.toggle_message_id
        )
        self.auto_find_check.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="w")

        ctk.CTkLabel(self.tab_private, text="ID сообщения (если не авто-поиск):").grid(row=2, column=0, padx=10, pady=5, sticky="w")
        self.source_msg_id_entry = ctk.CTkEntry(self.tab_private, width=300)
        self.source_msg_id_entry.grid(row=2, column=1, padx=10, pady=5)
        if self.config.get("source_message_id"):
            self.source_msg_id_entry.insert(0, self.config["source_message_id"])
        self.toggle_message_id()


        ctk.CTkLabel(self.tab_private, text="Интервал между сообщениями (сек):").grid(row=3, column=0, padx=10, pady=5, sticky="w")
        self.delay_entry = ctk.CTkEntry(self.tab_private, width=100)
        self.delay_entry.grid(row=3, column=1, padx=10, pady=5, sticky="w")
        self.delay_entry.insert(0, str(self.config.get("delay_between_sends", 360)))

        ctk.CTkLabel(self.tab_private, text="Время первого сообщения (необязательно, HH:MM или YYYY-MM-DD HH:MM:SS):").grid(row=4, column=0, padx=10, pady=5, sticky="w")
        self.start_time_entry = ctk.CTkEntry(self.tab_private, width=300)
        self.start_time_entry.grid(row=4, column=1, padx=10, pady=5)
        self.start_time_entry.insert(0, "") 

        ctk.CTkLabel(self.tab_private, text="Редактировать список получателей:").grid(row=5, column=0, padx=10, pady=5, sticky="w")
        self.recipients_text = ctk.CTkTextbox(self.tab_private, height=200, wrap="none")
        self.recipients_text.grid(row=6, column=0, columnspan=2, padx=10, pady=5, sticky="nsew")
        self.tab_private.grid_rowconfigure(6, weight=1)
        self.tab_private.grid_columnconfigure(1, weight=1)
        self.load_recipients_into_text()

        self.save_recipients_button = ctk.CTkButton(self.tab_private, text="Сохранить получателей", command=self.save_recipients)
        self.save_recipients_button.grid(row=7, column=0, columnspan=2, padx=10, pady=5)

    def toggle_message_id(self):
        if self.auto_find_var.get():
            self.source_msg_id_entry.configure(state="disabled")
        else:
            self.source_msg_id_entry.configure(state="normal")

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

    def create_groups_tab(self):
        ctk.CTkLabel(self.tab_groups, text="Текст сообщения:").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.group_text_entry = ctk.CTkEntry(self.tab_groups, width=400)
        self.group_text_entry.grid(row=0, column=1, padx=10, pady=5)
        self.group_text_entry.insert(0, self.config.get("group_message_text", "Я вообще андрей"))

        ctk.CTkLabel(self.tab_groups, text="Интервал между циклами (сек):").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.group_interval_entry = ctk.CTkEntry(self.tab_groups, width=100)
        self.group_interval_entry.grid(row=1, column=1, padx=10, pady=5, sticky="w")
        self.group_interval_entry.insert(0, str(self.config.get("group_cycle_interval", 720)))

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
        """Добавляет сообщение в текстовое поле логов (GUI-безопасно)"""
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.update_idletasks()

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
        """Создаёт новый event loop и запускает основную функцию"""
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
        """Основная асинхронная логика: выбор режима и запуск соответствующего процесса"""
        api_id = int(self.api_id_entry.get())
        api_hash = self.api_hash_entry.get()
        tz_offset = int(self.tz_entry.get())
        mode = self.tabview.get() 

        if mode == "Личные сообщения":
            await self.run_private_mode(api_id, api_hash, tz_offset)
        else:
            await self.run_groups_mode(api_id, api_hash, tz_offset)

    async def run_private_mode(self, api_id, api_hash, tz_offset):
        recipients_file = self.recipients_file_entry.get()
        recipients = self.load_recipients(recipients_file)
        if not recipients:
            self.log("Нет получателей для рассылки ЛС.")
            return

        source_chat = self.source_chat_entry.get()
        auto_find = self.auto_find_var.get()
        source_msg_id = None
        if not auto_find:
            msg_id_str = self.source_msg_id_entry.get()
            if msg_id_str:
                source_msg_id = int(msg_id_str)

        delay = int(self.delay_entry.get())
        start_time_str = self.start_time_entry.get()
        first_time = None
        if start_time_str:
            try:
                now = datetime.now()
                hour_min = datetime.strptime(start_time_str, "%H:%M")
                first_time = now.replace(hour=hour_min.hour, minute=hour_min.minute, second=0, microsecond=0)
                if first_time < now:
                    first_time += timedelta(days=1)
            except ValueError:
                try:
                    first_time = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    self.log("Неверный формат времени первого сообщения, используется текущее время + интервал")
                    first_time = None

        client = TelegramClient('user_session', api_id, api_hash)
        try:
            await client.start()
            self.log("Авторизация успешна.")
            source_msg = await self.get_source_message(client, source_chat, source_msg_id, auto_find)
            if source_msg is None:
                self.log("Не удалось получить исходное сообщение.")
                return

            await self.schedule_forward_to_recipients(client, recipients, source_msg, delay, first_time, tz_offset)
        except errors.rpcerrorlist.ApiIdInvalidError:
            self.log("Неверный API_ID или API_HASH.")
        except Exception as e:
            self.log(f"Ошибка в режиме ЛС: {e}")
        finally:
            await client.disconnect()
            self.log("Сессия закрыта.")

    def load_recipients(self, file_path):
        if not Path(file_path).exists():
            self.log(f"Файл получателей не найден: {file_path}")
            return []
        with open(file_path, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip()]

    async def get_source_message(self, client, chat, message_id, auto_find):
        try:
            entity = await client.get_entity(chat)
        except Exception as e:
            self.log(f"Не удалось получить сущность источника: {e}")
            return None

        if auto_find:
            self.log(f"Поиск последнего видеокружка в {chat}...")
            async for msg in client.iter_messages(entity):
                if msg.video_note:
                    self.log(f"Найдено сообщение ID={msg.id}")
                    return msg
            self.log("Видеокружков не найдено.")
            return None
        else:
            if not message_id:
                self.log("Не указан ID сообщения")
                return None
            try:
                msg = await client.get_messages(entity, ids=message_id)
                if msg:
                    self.log(f"Загружено сообщение ID={msg.id}")
                    return msg
                else:
                    self.log(f"Сообщение ID={message_id} не найдено")
                    return None
            except Exception as e:
                self.log(f"Ошибка получения сообщения: {e}")
                return None

    async def schedule_forward_to_recipients(self, client, recipients, source_msg, delay, first_time, tz_offset):
        success = 0
        fail = 0
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

            try:
                entity = await client.get_entity(recipient)
                await client.forward_messages(
                    entity,
                    source_msg,
                    drop_author=True,
                    schedule=schedule_time_utc
                )
                success += 1
            except errors.FloodWaitError as e:
                self.log(f"Flood wait для {recipient}: ждём {e.seconds} сек")
                await asyncio.sleep(e.seconds)
                try:
                    entity = await client.get_entity(recipient)
                    await client.forward_messages(entity, source_msg, drop_author=True, schedule=schedule_time_utc)
                    success += 1
                except Exception as e2:
                    self.log(f"Ошибка при повторном планировании {recipient}: {e2}")
                    fail += 1
            except Exception as e:
                self.log(f"Ошибка планирования {recipient}: {e}")
                fail += 1

        self.log(f"Планирование завершено. Успешно: {success}, Ошибок: {fail}")

    async def run_groups_mode(self, api_id, api_hash, tz_offset):
        groups_file = self.groups_file_entry.get()
        groups = self.load_groups(groups_file)
        if not groups:
            self.log("Нет групп для рассылки.")
            return

        text = self.group_text_entry.get()
        if not text:
            self.log("Текст сообщения не может быть пустым.")
            return

        interval = int(self.group_interval_entry.get())

        client = TelegramClient('user_session', api_id, api_hash)
        try:
            await client.start()
            self.log("Авторизация успешна.")
            await self.infinite_scheduled_group_mailing(client, groups, text, interval, tz_offset)
        except errors.rpcerrorlist.ApiIdInvalidError:
            self.log("Неверный API_ID или API_HASH.")
        except Exception as e:
            self.log(f"Ошибка в режиме групп: {e}")
        finally:
            await client.disconnect()
            self.log("Сессия закрыта.")

    def load_groups(self, file_path):
        if not Path(file_path).exists():
            self.log(f"Файл групп не найден: {file_path}")
            return []
        with open(file_path, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip()]

    async def infinite_scheduled_group_mailing(self, client, groups, text, cycle_interval, tz_offset):
        cycle_num = 1
        schedule_delta = timedelta(seconds=cycle_interval)

        while self.running:
            self.log(f"=== Цикл {cycle_num} ===")
            for group in groups:
                if not self.running:
                    break
                await self.send_scheduled_message(client, group, text, schedule_delta, tz_offset)
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

    async def send_scheduled_message(self, client, group, text, schedule_delta, tz_offset):
        try:
            entity = await client.get_entity(group)
            schedule_time_utc = datetime.utcnow() + schedule_delta
            display_time = (datetime.now() + timedelta(hours=tz_offset)) + schedule_delta
            await client.send_message(
                entity,
                text,
                schedule=schedule_time_utc
            )
            self.log(f"Сообщение запланировано в группу {group} на {display_time.strftime('%H:%M:%S')}")
        except errors.FloodWaitError as e:
            self.log(f"Flood wait для группы {group}: ждём {e.seconds} сек")
            await asyncio.sleep(e.seconds)
            await self.send_scheduled_message(client, group, text, schedule_delta, tz_offset)
        except Exception as e:
            self.log(f"Ошибка при планировании в группу {group}: {e}")

    def on_closing(self):
        if self.running:
            if self.task_thread and self.task_thread.is_alive():
                self.task_thread.join(timeout=2)
        self.destroy()

if __name__ == "__main__":
    app = ForwarderApp()
    app.mainloop()