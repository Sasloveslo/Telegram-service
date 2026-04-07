import asyncio
import json
import logging
import random
import smtplib
import sys
import threading
import time
import queue

from tkinter import simpledialog
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog
from telethon import TelegramClient, errors
from telethon.tl.types import DocumentAttributeVideo, DocumentAttributeAudio
from telethon.tl.functions.messages import GetScheduledHistoryRequest
from telethon.tl.functions.messages import GetScheduledHistoryRequest, DeleteScheduledMessagesRequest

# ==================== КОНФИГУРАЦИЯ ====================
CONFIG_FILE = "forwarder_config.json"
DEFAULT_CONFIG = {
    "api_id": "",
    "api_hash": "",
    "recipients_file": "recipients.txt",
    "groups_file": "groups.txt",
    # Настройки для кружков (личные сообщения)
    "ls_source_chat_1": "",           # чат для первого сообщения
    "ls_auto_find_1": True,
    "ls_message_ids_1": "",
    "ls_source_chat_2": "",           # чат для второго сообщения
    "ls_auto_find_2": True,
    "ls_message_ids_2": "",
    "ls_message_interval": 150,       # интервал между сообщениями
    "delay_between_sends": 360,
    # Общие настройки
    "delay_between_sends": 360,
    "group_cycle_interval": 1800,
    "group_message_text": "",
    "tz_offset": 3,
    "log_file": "forwarder.log",
    # Настройки для групп (пересылка сообщений)
    "group_source_chat": "",
    "group_auto_find": True,
    "group_message_ids": "",
    # ---------- НАСТРОЙКИ EMAIL ----------
    "email_smtp_server": "smtp.gmail.com",
    "email_smtp_port": 587,
    "email_login": "",
    "email_password": "",
    "email_subject": "Привет!",
    "email_body": "Это тестовое письмо.",
    "email_interval": 60,
    "emails_file": "emails.txt",

    "verify_sent": True,  # Проверять реальную отправку сообщений
    "verification_delay": 36000,  # Через сколько секунд проверять (по умолчанию 1 час)
}

logger = logging.getLogger("forwarder")
logger.setLevel(logging.INFO)


class ForwarderApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Telegram Forwarder")
        self.geometry("1100x800")
        self.minsize(900, 650)

        self.running_ls = False
        self.running_groups = False
        self.ls_thread = None
        self.groups_thread = None
        self.running_email = False
        self.email_thread = None

        self.config = self.load_config()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)


        self.authorized = False
        self.current_user = None
        self.after(100, self.check_existing_session)

        self.tab_settings = self.tabview.add("Настройки")
        self.tab_private = self.tabview.add("Личные сообщения")
        self.tab_groups = self.tabview.add("Группы")
        self.tab_email = self.tabview.add("Email рассылка")
        self.tab_logs = self.tabview.add("Логи")

        self.create_check_scheduled_tab()

        self.create_settings_tab()
        self.create_private_tab()
        self.create_groups_tab()
        self.create_email_tab()
        self.create_logs_tab()

        sys.stdout = self.StreamRedirector(self.log, sys.__stdout__)
        sys.stderr = self.StreamRedirector(self.log, sys.__stderr__)

        import builtins
        self.original_input = builtins.input
        builtins.input = self.input_redirect

        # Кнопки управления (отдельно для Telegram и email)
        self.button_frame = ctk.CTkFrame(self)
        self.button_frame.pack(side="bottom", fill="x", padx=10, pady=(0, 10))

        self.start_stop_ls_button = ctk.CTkButton(
            self.button_frame, text="Запустить ЛС",
            command=self.toggle_ls_mailing
        )
        self.start_stop_ls_button.pack(side="left", padx=5, pady=5)

        self.start_stop_groups_button = ctk.CTkButton(
            self.button_frame, text="Запустить группы",
            command=self.toggle_groups_mailing
        )
        self.start_stop_groups_button.pack(side="left", padx=5, pady=5)

        self.start_stop_email_button = ctk.CTkButton(
            self.button_frame, text="Запустить email",
            command=self.toggle_email_mailing
        )
        self.start_stop_email_button.pack(side="left", padx=5, pady=5)

        self.check_scheduled_button = ctk.CTkButton(
            self.button_frame, text="Проверить отложенные",
            command=self.check_scheduled_messages
        )
        self.check_scheduled_button.pack(side="left", padx=5, pady=5)

        self.setup_log_redirect()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.setup_global_bindings()

        self.tab_messages = self.tabview.add("Просмотр сообщений")
        self.create_messages_tab()

    class StreamRedirector:
        """Перенаправляет stdout/stderr в лог-виджет"""
        def __init__(self, log_callback, original_stream):
            self.log_callback = log_callback
            self.original_stream = original_stream

        def write(self, text):
            if text and text.strip():
                self.log_callback(text.rstrip())
            if self.original_stream:
                self.original_stream.write(text)

        def flush(self):
            if self.original_stream:
                self.original_stream.flush()
        
    def input_redirect(self, prompt=''):
        """Перехватывает input() и показывает диалоговое окно (универсальный)"""
        if prompt:
            self.log(prompt.strip())

        # Очередь для получения результата
        result_queue = queue.Queue()

        def show_dialog():
            try:
                # Создаём диалоговое окно
                dialog = ctk.CTkToplevel(self)
                dialog.title("Требуется ввод")
                dialog.geometry("550x220")
                dialog.transient(self)
                dialog.grab_set()
                dialog.focus_force()

                # Центрируем окно
                dialog.update_idletasks()
                x = self.winfo_x() + (self.winfo_width() - 550) // 2
                y = self.winfo_y() + (self.winfo_height() - 220) // 2
                dialog.geometry(f"+{x}+{y}")

                # Определяем тип запроса (пароль или обычный текст)
                prompt_lower = prompt.lower()
                is_password = any(word in prompt_lower for word in 
                                ['password', 'пароль', '2fa', 'two-factor', 'two factor'])

                # Метка с вопросом (делаем перенос строк)
                label = ctk.CTkLabel(dialog, text=prompt, wraplength=500, justify="left")
                label.pack(pady=(20, 10), padx=20)

                # Поле ввода (со звездочками для пароля)
                entry = ctk.CTkEntry(dialog, width=450, show="*" if is_password else "")
                entry.pack(pady=5, padx=20)
                entry.focus()

                result = [""]

                def on_ok():
                    result[0] = entry.get()
                    dialog.destroy()

                def on_cancel():
                    result[0] = ""
                    dialog.destroy()

                # Кнопки
                button_frame = ctk.CTkFrame(dialog)
                button_frame.pack(pady=15)

                ctk.CTkButton(button_frame, text="OK", command=on_ok, width=100).pack(side="left", padx=10)
                ctk.CTkButton(button_frame, text="Отмена", command=on_cancel, width=100).pack(side="left", padx=10)

                # Привязываем Enter к OK
                entry.bind("<Return>", lambda e: on_ok())

                # Ждём закрытия окна
                dialog.wait_window()
                result_queue.put(result[0])

            except Exception as e:
                self.log(f"Ошибка диалога: {e}")
                # Если диалог не сработал, используем терминал
                self.log("Пожалуйста, введите данные в терминале:")
                result_queue.put(self.original_input(prompt))

        # Запускаем диалог в главном потоке
        self.after(0, show_dialog)

        # Ждём результат (с таймаутом)
        while True:
            try:
                return result_queue.get(timeout=0.1)
            except queue.Empty:
                time.sleep(0.05)
                if not self.winfo_exists():
                    return ""
    async def verify_and_reschedule(self, client, recipient, scheduled_messages):
        """
        Проверяет, отправились ли запланированные сообщения.
        Если нет - перепланирует их на более позднее время.
        """
        for msg_info in scheduled_messages:
            msg_id = msg_info["message_id"]
            try:
                # Получаем историю чата с получателем
                entity = await client.get_entity(recipient)
                # Ищем наше сообщение по ID
                msg = await client.get_messages(entity, ids=msg_id)

                if msg and hasattr(msg, 'date') and msg.date > datetime.now(timezone.utc) - timedelta(hours=1):
                    self.log(f"Сообщение {msg_id} для {recipient} успешно отправлено")
                    return True
                else:
                    self.log(f"Сообщение {msg_id} для {recipient} не найдено или не отправлено")
                    return False
            except Exception as e:
                self.log(f"Ошибка проверки сообщения {msg_id} для {recipient}: {e}")
                return False

    def check_scheduled_messages(self):
        """Проверяет все запланированные сообщения и перепланирует застрявшие"""
        self.log("Проверка отложенных сообщений...")
        self.check_thread = threading.Thread(target=self.run_check_scheduled, daemon=True)
        self.check_thread.start()

    def run_check_scheduled(self):
        """Запускает асинхронную проверку отложенных сообщений"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.async_check_scheduled())
        except Exception as e:
            self.log(f"Ошибка проверки: {e}")
        finally:
            loop.close()
    
    async def async_check_scheduled(self):
        """Асинхронная проверка отложенных сообщений"""
        tracking_file = "scheduled_tracking.json"
        if not Path(tracking_file).exists():
            self.log("Нет отслеживаемых сообщений")
            return

        if not self.authorized or self.client is None:
            self.log("❌ Профиль не авторизован! Сначала авторизуйтесь в настройках.")
            return

        with open(tracking_file, 'r', encoding='utf-8') as f:
            scheduled_messages = json.load(f)

        # Фильтруем только непроверенные или старые
        to_check = [msg for msg in scheduled_messages if not msg.get("checked", False)]

        if not to_check:
            self.log("Все сообщения уже проверены")
            return

        tz_offset = int(self.tz_entry.get())

        # Проверяем, что клиент всё ещё жив
        try:
            await self.client.get_me()
        except:
            self.log("⚠️ Сессия устарела. Пожалуйста, авторизуйтесь заново.")
            self.authorized = False
            self.current_user = None
            self.after(0, self._update_profile_display, None)
            return

        rescheduled = []
        still_pending = []

        for item in to_check:
            recipient = item.get("recipient")
            if not recipient:
                continue

            schedule_time_str = item.get("schedule_time")
            if not schedule_time_str:
                continue

            try:
                schedule_time = datetime.fromisoformat(schedule_time_str)
            except:
                self.log(f"Неверный формат времени для {recipient}")
                still_pending.append(recipient)
                continue

            # Если прошло больше 1 часа с запланированного времени
            if datetime.now() > schedule_time + timedelta(hours=1):
                self.log(f"Сообщение для {recipient} не отправилось в срок, перепланируем...")

                # Отмечаем как проверенное
                item["checked"] = True
                rescheduled.append(recipient)
            else:
                # Ещё рано проверять
                still_pending.append(recipient)

        # Обновляем файл
        with open(tracking_file, 'w', encoding='utf-8') as f:
            json.dump(scheduled_messages, f, indent=4)

        self.log(f"Проверка завершена. Просрочено: {len(rescheduled)}, ожидают: {len(still_pending)}")

    async def reschedule_stuck_messages(self, client, recipient, original_schedule_time, note_msg, video_msg, video_interval, tz_offset):
        """Перепланирует застрявшие сообщения на новое время"""
        new_schedule_time = datetime.now() + timedelta(minutes=30)  # Через 30 минут

        new_schedule_utc = new_schedule_time - timedelta(hours=tz_offset)

        try:
            entity = await client.get_entity(recipient)

            # Отменяем старые отложенные сообщения (если можно)
            # Telethon не имеет прямого метода для отмены, поэтому просто отправляем новые

            # Отправляем новый кружок
            await client.forward_messages(
                entity,
                note_msg,
                drop_author=True,
                schedule=new_schedule_utc
            )

            if video_interval > 0 and video_msg:
                video_schedule_time = new_schedule_time + timedelta(seconds=video_interval)
                video_schedule_utc = video_schedule_time - timedelta(hours=tz_offset)
                await client.forward_messages(
                    entity,
                    video_msg,
                    drop_author=True,
                    schedule=video_schedule_utc
                )

            self.log(f"Перепланировано для {recipient} на {new_schedule_time}")
            return True
        except Exception as e:
            self.log(f"Ошибка перепланирования для {recipient}: {e}")
            return False

    def save_scheduled_tracking(self, scheduled_data):
        """Сохраняет информацию о запланированных сообщениях для последующей проверки"""
        tracking_file = "scheduled_tracking.json"

        # Загружаем существующие данные
        existing_data = []
        if Path(tracking_file).exists():
            try:
                with open(tracking_file, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError):
                self.log("Ошибка чтения файла отслеживания, создаю новый")

        # Добавляем новые данные
        existing_data.extend(scheduled_data)

        # Сохраняем обратно
        with open(tracking_file, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, indent=4, ensure_ascii=False)

        self.log(f"Сохранено отслеживание для {len(scheduled_data)} получателей")

    def check_existing_session(self):
        """Проверяет, есть ли уже сохранённая сессия"""
        if Path("user_session.session").exists():
            self.log("🔍 Обнаружена сохранённая сессия. Нажмите 'Авторизовать профиль' для входа.")

    def create_messages_tab(self):
        """Вкладка для просмотра сообщений из канала/чата"""
        # Поля ввода
        ctk.CTkLabel(self.tab_messages, text="Чат (ссылка или username):").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.messages_chat_entry = ctk.CTkEntry(self.tab_messages, width=400)
        self.messages_chat_entry.grid(row=0, column=1, padx=10, pady=5)
        self.messages_chat_entry.insert(0, "https://t.me/arteeeeimKokaraev")

        ctk.CTkLabel(self.tab_messages, text="Лимит сообщений:").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.messages_limit_entry = ctk.CTkEntry(self.tab_messages, width=100)
        self.messages_limit_entry.grid(row=1, column=1, padx=10, pady=5, sticky="w")
        self.messages_limit_entry.insert(0, "50")

        ctk.CTkLabel(self.tab_messages, text="Фильтр по типу:").grid(row=2, column=0, padx=10, pady=5, sticky="w")
        self.messages_filter_var = ctk.StringVar(value="Все")
        filter_menu = ctk.CTkOptionMenu(self.tab_messages, 
                                        values=["Все", "Текст", "Кружок", "Видео", "Голосовое", "Фото", "Документ"],
                                        variable=self.messages_filter_var)
        filter_menu.grid(row=2, column=1, padx=10, pady=5, sticky="w")

        # Кнопка загрузки
        self.load_messages_button = ctk.CTkButton(self.tab_messages, text="Загрузить сообщения", command=self.start_messages_loading)
        self.load_messages_button.grid(row=3, column=0, columnspan=2, padx=10, pady=10)

        # Текстовое поле для вывода
        self.messages_output = ctk.CTkTextbox(self.tab_messages, wrap="none", font=("Courier", 11))
        self.messages_output.grid(row=4, column=0, columnspan=2, padx=10, pady=5, sticky="nsew")
        self.tab_messages.grid_rowconfigure(4, weight=1)
        self.tab_messages.grid_columnconfigure(1, weight=1)

    def create_check_scheduled_tab(self):
        """Вкладка для проверки пустых чатов"""
        self.tab_check = self.tabview.add("Проверка чатов")

        # === Верхняя панель с настройками ===
        top_frame = ctk.CTkFrame(self.tab_check)
        top_frame.pack(fill="x", padx=10, pady=10)

        # Файл со списком для проверки
        ctk.CTkLabel(top_frame, text="Файл со списком для проверки:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.check_list_entry = ctk.CTkEntry(top_frame, width=300)
        self.check_list_entry.grid(row=0, column=1, padx=5, pady=5)
        self.check_list_entry.insert(0, "check_list.txt")

        self.browse_check_list_button = ctk.CTkButton(top_frame, text="Обзор", command=self.browse_check_list_file)
        self.browse_check_list_button.grid(row=0, column=2, padx=5, pady=5)

        self.load_check_list_button = ctk.CTkButton(top_frame, text="Загрузить список", command=self.load_check_list)
        self.load_check_list_button.grid(row=0, column=3, padx=5, pady=5)

        # Кнопки действий
        button_frame = ctk.CTkFrame(top_frame)
        button_frame.grid(row=1, column=0, columnspan=4, pady=10)

        self.check_button = ctk.CTkButton(button_frame, text="🔍 Найти пустые чаты", command=self.start_check_scheduled, width=200)
        self.check_button.pack(side="left", padx=5)

        self.export_button = ctk.CTkButton(button_frame, text="📄 Экспорт отчёта", command=self.export_check_report, width=120)
        self.export_button.pack(side="left", padx=5)

        # === Редактор списка для проверки ===
        ctk.CTkLabel(self.tab_check, text="Редактировать список для проверки (по одному на строку):").pack(anchor="w", padx=10, pady=(0, 5))
        self.check_list_text = ctk.CTkTextbox(self.tab_check, height=150, wrap="none")
        self.check_list_text.pack(fill="x", padx=10, pady=(0, 10))
        self.save_check_list_button = ctk.CTkButton(self.tab_check, text="Сохранить список", command=self.save_check_list)
        self.save_check_list_button.pack(anchor="w", padx=10, pady=(0, 10))

        # === Результаты проверки ===
        ctk.CTkLabel(self.tab_check, text="📊 Результаты проверки:").pack(anchor="w", padx=10, pady=(0, 5))

        # Создаём frame для таблицы с прокруткой
        table_frame = ctk.CTkFrame(self.tab_check)
        table_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Текстовое поле для вывода результатов
        self.check_results_text = ctk.CTkTextbox(table_frame, wrap="none", font=("Courier", 11))
        self.check_results_text.pack(fill="both", expand=True, padx=2, pady=2)

        # Статусная строка
        self.check_status_label = ctk.CTkLabel(self.tab_check, text="Готов к проверке", font=("Arial", 11))
        self.check_status_label.pack(anchor="w", padx=10, pady=(0, 10))

    def browse_check_list_file(self):
        """Выбор файла со списком для проверки"""
        file_path = filedialog.askopenfilename(title="Выберите файл со списком")
        if file_path:
            self.check_list_entry.delete(0, "end")
            self.check_list_entry.insert(0, file_path)
            self.load_check_list()

    def load_check_list(self):
        """Загружает список для проверки из файла"""
        file_path = self.check_list_entry.get()
        if Path(file_path).exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                self.check_list_text.delete("1.0", "end")
                self.check_list_text.insert("1.0", f.read())
            self.log(f"Загружен список для проверки из {file_path}")
        else:
            self.log(f"Файл {file_path} не найден")

    def save_check_list(self):
        """Сохраняет список для проверки в файл"""
        content = self.check_list_text.get("1.0", "end-1c")
        file_path = self.check_list_entry.get()
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        self.log(f"Список для проверки сохранён в {file_path}")

    def start_check_scheduled(self):
        """Запускает проверку пустых чатов"""
        if not self.authorized or self.client is None:
            self.log("❌ Профиль не авторизован! Сначала авторизуйтесь в настройках.")
            return

        self.check_button.configure(state="disabled", text="⏳ Проверка...")
        self.check_results_text.delete("1.0", "end")
        self.check_results_text.insert("end", "Загрузка...\n")

        thread = threading.Thread(target=self.run_check_scheduled_full, daemon=True)
        thread.start()

    def run_check_scheduled_full(self):
        """Запускает полную проверку отложенных сообщений"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.async_check_scheduled_full())
        except Exception as e:
            self.log(f"Ошибка проверки: {e}")
        finally:
            loop.close()
            self.after(0, lambda: self.check_button.configure(state="normal", text="🔍 Проверить"))

    from telethon.tl.functions.messages import GetScheduledHistoryRequest

    async def async_check_scheduled_full(self):
        """Проверка списка пользователей - выводит только пустые чаты"""

        # Получаем список для проверки
        check_list_text = self.check_list_text.get("1.0", "end-1c")
        check_list = [line.strip() for line in check_list_text.split('\n') if line.strip()]

        if not check_list:
            self.after(0, lambda: self.check_results_text.insert("end", "❌ Список пуст! Загрузите или введите данные для проверки.\n"))
            return

        self.log(f"📋 Загружено {len(check_list)} записей для проверки: {check_list}")

        self.after(0, lambda: self.check_results_text.delete("1.0", "end"))

        # СОЗДАЁМ НОВОГО ВРЕМЕННОГО КЛИЕНТА
        api_id = int(self.api_id_entry.get())
        api_hash = self.api_hash_entry.get()
        client = TelegramClient('temp_session', api_id, api_hash)

        empty_usernames = []  # Список username с пустыми чатами
        not_found = []        # Не найденные пользователи

        try:
            await client.start()
            self.after(0, lambda: self.check_results_text.insert("end", "🔍 Поиск пустых чатов...\n\n"))

            for check_item in check_list:
                check_item_clean = check_item.replace('@', '').replace('https://t.me/', '').replace('t.me/', '').strip()

                try:
                    # Пытаемся получить пользователя
                    entity = await client.get_entity(check_item_clean)

                    # Проверяем, есть ли сообщения в чате
                    messages = []
                    async for msg in client.iter_messages(entity, limit=1):
                        messages.append(msg)

                    has_messages = len(messages) > 0

                    # Если чат пустой (нет сообщений)
                    if not has_messages:
                        username = getattr(entity, 'username', None)
                        if username:
                            empty_usernames.append(f"@{username}")
                        else:
                            # Если нет username, выводим имя
                            first_name = getattr(entity, 'first_name', '')
                            last_name = getattr(entity, 'last_name', '')
                            name = f"{first_name} {last_name}".strip()
                            empty_usernames.append(name if name else str(entity.id))

                        self.log(f"📭 Пустой чат: {check_item}")
                    else:
                        self.log(f"✅ Есть сообщения: {check_item}")

                except errors.UserIsBlockedError:
                    # Заблокированный пользователь тоже считается "пустым" для наших целей
                    empty_usernames.append(f"{check_item} (заблокирован)")
                    self.log(f"🚫 Пользователь заблокировал бота: {check_item}")
                except errors.UsernameNotOccupiedError:
                    not_found.append(check_item)
                    self.log(f"❌ Пользователь не найден: {check_item}")
                except Exception as e:
                    error_msg = str(e)
                    if "FLOOD" in error_msg:
                        self.log(f"⚠️ Flood wait для {check_item}")
                    else:
                        not_found.append(f"{check_item} (ошибка: {error_msg[:50]})")
                        self.log(f"⚠️ Ошибка при проверке {check_item}: {error_msg[:100]}")

            # Выводим результаты
            self.after(0, lambda: self.check_results_text.delete("1.0", "end"))

            result_text = ""

            if empty_usernames:
                result_text += "📋 СПИСОК ПОЛЬЗОВАТЕЛЕЙ С ПУСТЫМИ ЧАТАМИ:\n"
                result_text += "=" * 50 + "\n"
                for username in empty_usernames:
                    result_text += f"{username}\n"
                result_text += f"\n📊 Всего найдено: {len(empty_usernames)} пользователей с пустыми чатами\n"
            else:
                result_text += "✅ Пустых чатов не найдено!\n"

            if not_found:
                result_text += f"\n⚠️ Не найдено пользователей:\n"
                result_text += "=" * 50 + "\n"
                for item in not_found:
                    result_text += f"  • {item}\n"

            self.after(0, lambda: self.check_results_text.insert("end", result_text))

            # Обновляем статус
            status_text = f"📊 Проверка завершена. Пустых чатов: {len(empty_usernames)}, Не найдено: {len(not_found)}"
            self.after(0, lambda: self.check_status_label.configure(text=status_text))
            self.log(status_text)

        except Exception as e:
            error_text = f"Ошибка проверки: {e}"
            self.after(0, lambda: self.check_results_text.insert("end", error_text + "\n"))
            self.log(error_text)
        finally:
            await client.disconnect()

    def clear_scheduled_messages(self):
        """Очищает все отложенные сообщения в выбранных чатах"""
        # Получаем текст из результатов для парсинга
        results_text = self.check_results_text.get("1.0", "end-1c")
        if not results_text.strip():
            self.log("Нет данных для очистки. Сначала выполните проверку.")
            return

        # Подтверждение
        dialog = ctk.CTkToplevel(self)
        dialog.title("Подтверждение")
        dialog.geometry("400x150")
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text="Вы уверены, что хотите удалить все отложенные сообщения?", wraplength=350).pack(pady=20)

        result = [False]
        def confirm():
            result[0] = True
            dialog.destroy()
        def cancel():
            dialog.destroy()

        button_frame = ctk.CTkFrame(dialog)
        button_frame.pack(pady=10)
        ctk.CTkButton(button_frame, text="Да, удалить", command=confirm, fg_color="#8B0000").pack(side="left", padx=10)
        ctk.CTkButton(button_frame, text="Отмена", command=cancel).pack(side="left", padx=10)

        dialog.wait_window()
        if not result[0]:
            return

        self.log("Начинаю очистку отложенных сообщений...")
        thread = threading.Thread(target=self.run_clear_scheduled, daemon=True)
        thread.start()

    def run_clear_scheduled(self):
        """Запускает очистку отложенных сообщений"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.async_clear_scheduled())
        except Exception as e:
            self.log(f"Ошибка очистки: {e}")
        finally:
            loop.close()

    from telethon.tl.functions.messages import GetScheduledHistoryRequest, DeleteScheduledMessagesRequest

    async def async_clear_scheduled(self):
        """Асинхронная очистка отложенных сообщений"""
        results_text = self.check_results_text.get("1.0", "end-1c")
        lines = results_text.strip().split('\n')

        api_id = int(self.api_id_entry.get())
        api_hash = self.api_hash_entry.get()
        client = TelegramClient('temp_session', api_id, api_hash)

        cleared = 0
        errors = 0

        try:
            await client.start()

            for line in lines:
                if '|' not in line or 'Ошибка' in line:
                    continue

                parts = line.split('|')
                if len(parts) >= 2:
                    chat_name = parts[0].strip()
                    chat_id_str = parts[1].strip()

                    try:
                        # Получаем entity
                        try:
                            entity = await client.get_entity(int(chat_id_str))
                        except:
                            entity = await client.get_entity(chat_name)

                        input_entity = await client.get_input_entity(entity)

                        # Получаем отложенные сообщения
                        result = await client(GetScheduledHistoryRequest(
                            peer=input_entity,
                            hash=0
                        ))

                        if result.messages:
                            # Удаляем их
                            await client(DeleteScheduledMessagesRequest(
                                peer=input_entity,
                                id=[msg.id for msg in result.messages]
                            ))
                            cleared += len(result.messages)
                            self.log(f"Очищены отложенные в {chat_name} ({len(result.messages)} сообщений)")

                    except Exception as e:
                        self.log(f"Ошибка очистки {chat_name}: {e}")
                        errors += 1
        finally:
            await client.disconnect()

        self.log(f"Очистка завершена. Удалено сообщений: {cleared}, Ошибок: {errors}")

    def reschedule_stuck_messages(self):
        """Перепланирование застрявших сообщений"""
        # Проверяем, есть ли данные для перепланирования
        tracking_file = "scheduled_tracking.json"
        if not Path(tracking_file).exists():
            self.log("❌ Нет данных о запланированных сообщениях. Сначала выполните рассылку.")
            return

        # Проверяем авторизацию
        if not self.authorized or self.client is None:
            self.log("❌ Профиль не авторизован! Сначала авторизуйтесь в настройках.")
            return

        # Загружаем данные
        with open(tracking_file, 'r', encoding='utf-8') as f:
            scheduled_data = json.load(f)

        # Фильтруем только непроверенные или проблемные сообщения
        stuck_messages = [msg for msg in scheduled_data if not msg.get("checked", False)]

        if not stuck_messages:
            self.log("✅ Нет застрявших сообщений для перепланирования.")
            return

        # Подтверждение действия
        dialog = ctk.CTkToplevel(self)
        dialog.title("Подтверждение")
        dialog.geometry("450x200")
        dialog.transient(self)
        dialog.grab_set()

        dialog.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 450) // 2
        y = self.winfo_y() + (self.winfo_height() - 200) // 2
        dialog.geometry(f"+{x}+{y}")

        ctk.CTkLabel(dialog, text=f"Найдено {len(stuck_messages)} получателей с застрявшими сообщениями.", wraplength=400).pack(pady=(20, 5))
        ctk.CTkLabel(dialog, text="Перепланировать их?", wraplength=400).pack(pady=(0, 10))

        result = [False]
        def confirm():
            result[0] = True
            dialog.destroy()
        def cancel():
            dialog.destroy()

        button_frame = ctk.CTkFrame(dialog)
        button_frame.pack(pady=10)
        ctk.CTkButton(button_frame, text="Да, перепланировать", command=confirm, fg_color="#006400", width=150).pack(side="left", padx=10)
        ctk.CTkButton(button_frame, text="Отмена", command=cancel, width=100).pack(side="left", padx=10)

        dialog.wait_window()
        if not result[0]:
            self.log("Перепланирование отменено.")
            return

        self.log(f"🔄 Начинаю перепланирование для {len(stuck_messages)} получателей...")

        # Запускаем в отдельном потоке
        thread = threading.Thread(target=self.run_reschedule, daemon=True)
        thread.start()

        def run_reschedule(self):
            """Запускает асинхронное перепланирование"""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.async_reschedule())
            except Exception as e:
                self.log(f"Ошибка перепланирования: {e}")
            finally:
                loop.close()

        async def async_reschedule(self):
            """Асинхронное перепланирование застрявших сообщений"""
            tracking_file = "scheduled_tracking.json"

            with open(tracking_file, 'r', encoding='utf-8') as f:
                scheduled_data = json.load(f)

            # Получаем исходные сообщения для перепланирования
            api_id = int(self.api_id_entry.get())
            api_hash = self.api_hash_entry.get()

            # Создаём временного клиента
            client = TelegramClient('temp_session', api_id, api_hash)

            try:
                await client.start()
                self.log("✅ Авторизация для перепланирования успешна")

                # Получаем сообщения для первого и второго слота
                messages_1 = await self.get_source_messages(
                    client,
                    self.ls_chat_1_entry.get(),
                    self.ls_auto_1_var.get(),
                    self.ls_ids_1_entry.get()
                )
                if not messages_1:
                    self.log("❌ Не удалось получить сообщения для первого слота")
                    return

                messages_2 = await self.get_source_messages(
                    client,
                    self.ls_chat_2_entry.get(),
                    self.ls_auto_2_var.get(),
                    self.ls_ids_2_entry.get()
                )
                if not messages_2:
                    self.log("❌ Не удалось получить сообщения для второго слота")
                    return

                msg_interval = int(self.ls_interval_entry.get())
                tz_offset = int(self.tz_entry.get())

                rescheduled_count = 0
                error_count = 0

                # Получаем текущее время как базовое для перепланирования
                now = datetime.now()
                current_time = now + timedelta(seconds=30)  # Начинаем через 30 секунд

                for item in scheduled_data:
                    if item.get("checked", False):
                        continue  # Пропускаем уже проверенные

                    recipient = item.get("recipient")
                    if not recipient:
                        continue

                    self.log(f"🔄 Перепланирование для {recipient}...")

                    # Время для первого сообщения
                    time_1 = current_time
                    time_1_utc = time_1 - timedelta(hours=tz_offset)

                    # Время для второго сообщения (через msg_interval)
                    time_2 = time_1 + timedelta(seconds=msg_interval)
                    time_2_utc = time_2 - timedelta(hours=tz_offset)

                    try:
                        entity = await client.get_entity(recipient)

                        # Отправляем первое сообщение
                        msg_1 = random.choice(messages_1)
                        await client.forward_messages(
                            entity, msg_1,
                            drop_author=True,
                            schedule=time_1_utc
                        )

                        # Отправляем второе сообщение
                        msg_2 = random.choice(messages_2)
                        await client.forward_messages(
                            entity, msg_2,
                            drop_author=True,
                            schedule=time_2_utc
                        )

                        self.log(f"  ✅ Перепланировано для {recipient}: 1-е на {time_1.strftime('%H:%M:%S')}, 2-е на {time_2.strftime('%H:%M:%S')}")
                        rescheduled_count += 1

                        # Отмечаем как перепланированное
                        item["checked"] = True
                        item["rescheduled"] = True
                        item["new_schedule_time_1"] = time_1.isoformat()
                        item["new_schedule_time_2"] = time_2.isoformat()

                        # Увеличиваем текущее время для следующего получателя (интервал 530 секунд = 8 минут 50 секунд)
                        current_time += timedelta(seconds=530)

                    except Exception as e:
                        self.log(f"  ❌ Ошибка перепланирования для {recipient}: {e}")
                        error_count += 1

                # Сохраняем обновлённые данные
                with open(tracking_file, 'w', encoding='utf-8') as f:
                    json.dump(scheduled_data, f, indent=4, ensure_ascii=False)

                self.log(f"📊 Перепланирование завершено. Успешно: {rescheduled_count}, Ошибок: {error_count}")

            except Exception as e:
                self.log(f"❌ Ошибка в процессе перепланирования: {e}")
            finally:
                await client.disconnect()

    def export_check_report(self):
        """Экспорт отчёта в файл"""
        results_text = self.check_results_text.get("1.0", "end-1c")
        if not results_text.strip():
            self.log("Нет данных для экспорта")
            return

        file_path = filedialog.asksaveasfilename(
            title="Сохранить отчёт",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("CSV files", "*.csv"), ("All files", "*.*")]
        )

        if file_path:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(results_text)
            self.log(f"Отчёт сохранён в {file_path}")

    def start_messages_loading(self):
        """Запускает загрузку сообщений в отдельном потоке"""
        chat = self.messages_chat_entry.get().strip()
        if not chat:
            self.safe_insert_messages_output("Ошибка: укажите чат.\n")
            return
        try:
            limit = int(self.messages_limit_entry.get())
            if limit <= 0:
                raise ValueError
        except:
            self.safe_insert_messages_output("Ошибка: лимит должен быть положительным числом.\n")
            return

        filter_type = self.messages_filter_var.get()
        filter_type = None if filter_type == "Все" else filter_type

        self.safe_clear_messages_output()
        self.safe_insert_messages_output("Загрузка сообщений...\n")
        self.load_messages_button.configure(state="disabled", text="Загрузка...")

        # Запускаем в потоке
        thread = threading.Thread(target=self.run_messages_loading, args=(chat, limit, filter_type), daemon=True)
        thread.start()

    def run_messages_loading(self, chat, limit, filter_type):
        """Запускает асинхронную функцию в отдельном event loop"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Выполняем асинхронную загрузку, получаем список строк результата
            lines = loop.run_until_complete(self.fetch_messages(chat, limit, filter_type))
        except Exception as e:
            lines = [f"Ошибка: {e}\n"]
        finally:
            # Даём время завершиться внутренним задачам Telethon
            loop.run_until_complete(asyncio.sleep(0.1))
            loop.close()
            # Возвращаем результат в главный поток
            self.after(0, self.display_messages_result, lines)
            self.after(0, lambda: self.load_messages_button.configure(state="normal", text="Загрузить сообщения"))

    def display_messages_result(self, lines):
        """Выводит накопленные строки в текстовое поле"""
        self.safe_clear_messages_output()
        for line in lines:
            self.safe_insert_messages_output(line)

    async def fetch_messages(self, chat, limit, filter_type):
        """Асинхронная загрузка сообщений через Telethon (возвращает список строк)"""
    
        # Проверяем авторизацию (наличие файла сессии)
        if not Path("user_session.session").exists():
            return ["❌ Профиль не авторизован! Сначала авторизуйтесь в настройках.\n"]
    
        api_id = int(self.api_id_entry.get())
        api_hash = self.api_hash_entry.get()
        
        # ✅ СОЗДАЁМ НОВОГО КЛИЕНТА
        client = TelegramClient('temp_session', api_id, api_hash)
    
        result_lines = []
        try:
            await client.start()
            
            entity = await client.get_entity(chat)
            result_lines.append(f"=== Последние {limit} сообщений из {chat} ===\n\n")
    
            count = 0
            async for msg in client.iter_messages(entity, limit=limit):
                msg_type = self.get_message_type_helper(msg)
                if filter_type and filter_type not in msg_type:
                    continue
    
                duration_str = ""
                if msg.video_note or msg.video or msg.voice:
                    duration = None
                    if msg.video_note or msg.video:
                        media = msg.video_note if msg.video_note else msg.video
                        if hasattr(media, 'attributes'):
                            for attr in media.attributes:
                                if isinstance(attr, DocumentAttributeVideo):
                                    duration = attr.duration
                                    break
                    if msg.voice:
                        for attr in msg.voice.attributes:
                            if isinstance(attr, DocumentAttributeAudio) and attr.voice:
                                duration = attr.duration
                                break
                    if duration is not None:
                        duration_int = int(duration)
                        minutes = duration_int // 60
                        seconds = duration_int % 60
                        if minutes:
                            duration_str = f" | Длительность: {minutes}:{seconds:02d}"
                        else:
                            duration_str = f" | Длительность: {seconds} сек"
                    else:
                        duration_str = " | Длительность: ?"
    
                raw_content = msg.text if msg.text else getattr(msg.file, 'name', None)
                content = raw_content if raw_content is not None else '—'
                if len(content) > 100:
                    content = content[:100] + "..."
                line = f"ID: {msg.id} | Тип: {msg_type}{duration_str} | Содержание: {content}\n"
                result_lines.append(line)
                count += 1
    
            result_lines.append(f"\n--- Загружено {count} сообщений ---\n")
    
        except Exception as e:
            result_lines.append(f"Ошибка: {e}\n")
        finally:
            await client.disconnect()
    
        return result_lines

    def get_message_type_helper(self, message):
        """Вспомогательная функция для определения типа сообщения (без self.log)"""
        from telethon.tl.types import DocumentAttributeVideo, DocumentAttributeAudio
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

    def safe_insert_messages_output(self, text):
        """Безопасная вставка текста в messages_output (в главном потоке)"""
        def _insert():
            if hasattr(self, 'messages_output') and self.messages_output:
                self.messages_output.insert("end", text)
                self.messages_output.see("end")
            else:
                self.log(text)  # fallback в лог
        self.after(0, _insert)

    def safe_clear_messages_output(self):
        """Безопасная очистка messages_output"""
        def _clear():
            if hasattr(self, 'messages_output') and self.messages_output:
                self.messages_output.delete("1.0", "end")
        self.after(0, _clear)

    def setup_global_bindings(self):
        # Привязываем ко всем текстовым виджетам
        for widget in self.winfo_children():
            self._bind_recursive(widget)
    def _bind_recursive(self, widget):
        # Если виджет является текстовым (CTkEntry, CTkTextbox, CTkText)
        if isinstance(widget, (ctk.CTkEntry, ctk.CTkTextbox)):
            widget.bind('<Control-c>', lambda e: self.copy_to_clipboard(widget))
            widget.bind('<Control-v>', lambda e: self.paste_from_clipboard(widget))
            widget.bind('<Control-x>', lambda e: self.cut_to_clipboard(widget))
            widget.bind('<Control-a>', lambda e: self.select_all(widget))
            # Для macOS (Command)
            widget.bind('<Command-c>', lambda e: self.copy_to_clipboard(widget))
            widget.bind('<Command-v>', lambda e: self.paste_from_clipboard(widget))
            widget.bind('<Command-x>', lambda e: self.cut_to_clipboard(widget))
            widget.bind('<Command-a>', lambda e: self.select_all(widget))
        # Рекурсивно обрабатываем детей
        for child in widget.winfo_children():
            self._bind_recursive(child)

    def copy_to_clipboard(self, widget):
        try:
            text = widget.get()
            if hasattr(widget, 'get'):
                text = widget.get()
            elif hasattr(widget, 'get'):
                text = widget.get(1.0, 'end-1c')  # для текстового поля
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception as e:
            print(f"Copy error: {e}")

    def paste_from_clipboard(self, widget):
        try:
            clipboard = self.clipboard_get()
            if hasattr(widget, 'insert'):
                widget.insert('insert', clipboard)
            elif hasattr(widget, 'insert'):
                widget.insert('insert', clipboard)
        except Exception as e:
            print(f"Paste error: {e}")

    def cut_to_clipboard(self, widget):
        self.copy_to_clipboard(widget)
        if hasattr(widget, 'delete'):
            widget.delete(0, 'end')
        elif hasattr(widget, 'delete'):
            widget.delete(1.0, 'end')

    def select_all(self, widget):
        if hasattr(widget, 'select_range'):
            widget.select_range(0, 'end')
        elif hasattr(widget, 'tag_add'):
            widget.tag_add('sel', '1.0', 'end')

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
            # Новые настройки для ЛС (2 сообщения)
            "ls_source_chat_1": self.ls_chat_1_entry.get(),
            "ls_auto_find_1": self.ls_auto_1_var.get(),
            "ls_message_ids_1": self.ls_ids_1_entry.get(),
            "ls_source_chat_2": self.ls_chat_2_entry.get(),
            "ls_auto_find_2": self.ls_auto_2_var.get(),
            "ls_message_ids_2": self.ls_ids_2_entry.get(),
            "ls_message_interval": int(self.ls_interval_entry.get()),
            "delay_between_sends": int(self.delay_entry.get()),
            "group_cycle_interval": int(self.group_interval_entry.get()),
            "group_source_chat": self.group_chat_entry.get(),
            "group_auto_find": self.group_auto_var.get(),
            "group_message_ids": self.group_ids_entry.get(),
            "tz_offset": int(self.tz_entry.get()),
            "log_file": self.log_file_entry.get(),
            # Email
            "email_smtp_server": self.email_smtp_entry.get(),
            "email_smtp_port": int(self.email_port_entry.get()),
            "email_login": self.email_login_entry.get(),
            "email_password": self.email_password_entry.get(),
            "email_subject": self.email_subject_entry.get(),
            "email_body": self.email_body_text.get("1.0", "end-1c"),
            "email_interval": int(self.email_interval_entry.get()),
            "emails_file": self.emails_file_entry.get(),
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
        msk_time = datetime.now(timezone.utc) + timedelta(hours=3)
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

        self.save_button = ctk.CTkButton(self.tab_settings, text="Сохранить настройки", command=self.save_config)
        self.save_button.grid(row=row, column=0, columnspan=2, padx=10, pady=20)
        row += 1


        auth_frame = ctk.CTkFrame(self.tab_settings)
        auth_frame.grid(row=row, column=0, columnspan=3, padx=10, pady=10, sticky="ew")
        row += 1

        ctk.CTkLabel(auth_frame, text="🔐 АВТОРИЗАЦИЯ", font=("Arial", 14, "bold")).grid(row=0, column=0, columnspan=3, padx=5, pady=5, sticky="w")

        self.auth_button = ctk.CTkButton(
            auth_frame, 
            text="🔑 Авторизовать профиль", 
            command=self.authorize_profile,
            width=200
        )
        self.auth_button.grid(row=1, column=0, padx=5, pady=5)

        self.profile_status_label = ctk.CTkLabel(
            auth_frame, 
            text="❌ Не авторизован", 
            text_color="red",
            font=("Arial", 12)
        )
        self.profile_status_label.grid(row=1, column=1, padx=5, pady=5, sticky="w")

        self.profile_info_label = ctk.CTkLabel(
            auth_frame, 
            text="", 
            font=("Arial", 11),
            text_color="gray"
        )
        self.profile_info_label.grid(row=2, column=0, columnspan=2, padx=5, pady=2, sticky="w")


        # Разделительная линия
        separator = ctk.CTkFrame(self.tab_settings, height=2, fg_color="gray")
        separator.grid(row=row, column=0, columnspan=3, padx=10, pady=10, sticky="ew")
        row += 1

        # Кнопка удаления профиля
        self.delete_profile_button = ctk.CTkButton(
            self.tab_settings, 
            text="🗑️ Удалить профиль (сброс авторизации)", 
            command=self.delete_profile,
            fg_color="#8B0000",  # тёмно-красный цвет
            hover_color="#A00000",
            width=250
        )
        self.delete_profile_button.grid(row=row, column=0, columnspan=2, padx=10, pady=10)

        # Предупреждение
        warning_label = ctk.CTkLabel(
            self.tab_settings, 
            text="⚠️ Внимание! Это удалит все сохранённые сессии Telegram.\nПосле этого потребуется повторная авторизация при следующем запуске рассылки.",
            text_color="orange",
            font=("Arial", 11)
        )
        warning_label.grid(row=row+1, column=0, columnspan=2, padx=10, pady=5)

    def authorize_profile(self):
        """Авторизация профиля Telegram"""

        if not self.api_id_entry.get() or not self.api_hash_entry.get():
            self.log("Ошибка: сначала укажите API ID и API Hash в настройках!")
            return

        # Запускаем авторизацию в отдельном потоке
        self.auth_button.configure(state="disabled", text="⏳ Авторизация...")
        self.log("Начинаем авторизацию профиля Telegram...")

        def auth_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._do_authorize())
            except Exception as e:
                self.log(f"Ошибка авторизации: {e}")
            finally:
                loop.close()
                self.after(0, lambda: self.auth_button.configure(state="normal", text="🔑 Авторизовать профиль"))

        threading.Thread(target=auth_thread, daemon=True).start()

    async def _do_authorize(self):
        """Асинхронная проверка авторизации (без сохранения клиента)"""
        api_id = int(self.api_id_entry.get())
        api_hash = self.api_hash_entry.get()

        # Временный клиент только для проверки
        client = TelegramClient('user_session', api_id, api_hash)

        try:
            await client.start()
            me = await client.get_me()

            self.current_user = me
            self.authorized = True
            # НЕ сохраняем client в self.client!

            self.after(0, self._update_profile_display, me)
            self.log(f"✅ Авторизация успешна! Вы вошли как: {me.first_name}")

        except Exception as e:
            self.authorized = False
            self.current_user = None
            self.log(f"❌ Ошибка авторизации: {e}")
            self.after(0, self._update_profile_display, None)
        finally:
            await client.disconnect()  # Закрываем временный клиент

    def _update_profile_display(self, user):
        """Обновляет отображение информации о профиле"""
        if user:
            name = f"{user.first_name} {user.last_name or ''}".strip()
            username = f"@{user.username}" if user.username else "нет username"
            self.profile_status_label.configure(text="✅ Авторизован", text_color="green")
            self.profile_info_label.configure(text=f"{name} | {username} | ID: {user.id}")
        else:
            self.profile_status_label.configure(text="❌ Не авторизован", text_color="red")
            self.profile_info_label.configure(text="")

    def delete_profile(self):
        """Удаляет файлы сессии Telegram для сброса авторизации"""
        # Подтверждение действия
        dialog = ctk.CTkToplevel(self)
        dialog.title("Подтверждение")
        dialog.geometry("400x180")
        dialog.transient(self)
        dialog.grab_set()
        dialog.focus_force()
    
        # Центрируем окно
        dialog.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 400) // 2
        y = self.winfo_y() + (self.winfo_height() - 180) // 2
        dialog.geometry(f"+{x}+{y}")
    
        ctk.CTkLabel(dialog, text="Вы уверены, что хотите удалить профиль?", wraplength=350).pack(pady=(20, 10), padx=20)
        ctk.CTkLabel(dialog, text="Будут удалены все сохранённые сессии Telegram.", text_color="orange", wraplength=350).pack(pady=(0, 10), padx=20)
    
        result = [False]
    
        def on_confirm():
            result[0] = True
            dialog.destroy()
    
        def on_cancel():
            result[0] = False
            dialog.destroy()
    
        button_frame = ctk.CTkFrame(dialog)
        button_frame.pack(pady=10)
    
        ctk.CTkButton(button_frame, text="Да, удалить", command=on_confirm, fg_color="#8B0000", hover_color="#A00000", width=100).pack(side="left", padx=10)
        ctk.CTkButton(button_frame, text="Отмена", command=on_cancel, width=100).pack(side="left", padx=10)
    
        dialog.wait_window()
    
        if not result[0]:
            self.log("Удаление профиля отменено.")
            return
    
        # Удаляем файлы сессии
        session_files = [
            "user_session.session",
            "temp_session.session",
            "user_session.session-journal",  # SQLite журнал
            "temp_session.session-journal"
        ]
    
        deleted_count = 0
        for file_name in session_files:
            file_path = Path(file_name)
            if file_path.exists():
                try:
                    file_path.unlink()
                    self.log(f"Удалён файл: {file_name}")
                    deleted_count += 1
                except Exception as e:
                    self.log(f"Ошибка при удалении {file_name}: {e}")
    
        # Также удаляем файл сессии из папки с программой (на всякий случай)
        session_variants = ["*.session", "*.session-journal"]
        for pattern in session_variants:
            for file_path in Path(".").glob(pattern):
                if file_path.exists():
                    try:
                        file_path.unlink()
                        self.log(f"Удалён файл: {file_path.name}")
                        deleted_count += 1
                    except Exception:
                        pass
    
        # Сбрасываем статус авторизации
        self.authorized = False
        self.current_user = None
        
        # Сбрасываем клиент, если он был активен
        if self.client:
            try:
                # Создаём временный loop для отключения, если клиент активен
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self.close_client())
                loop.close()
            except:
                pass
            self.client = None
    
        # Обновляем интерфейс (сбрасываем отображение профиля)
        self.after(0, self._update_profile_display, None)
    
        if deleted_count > 0:
            self.log(f"✅ Профиль успешно удалён. Удалено файлов: {deleted_count}")
            self.log("При следующем запуске рассылки потребуется повторная авторизация.")
    
            # Показываем информационное окно
            info_dialog = ctk.CTkToplevel(self)
            info_dialog.title("Готово")
            info_dialog.geometry("350x120")
            info_dialog.transient(self)
            info_dialog.grab_set()
    
            info_dialog.update_idletasks()
            x = self.winfo_x() + (self.winfo_width() - 350) // 2
            y = self.winfo_y() + (self.winfo_height() - 120) // 2
            info_dialog.geometry(f"+{x}+{y}")
    
            ctk.CTkLabel(info_dialog, text="✅ Профиль успешно удалён!", font=("Arial", 14)).pack(pady=(20, 10))
            ctk.CTkLabel(info_dialog, text="При следующем запуске рассылки потребуется авторизация.").pack(pady=(0, 10))
            ctk.CTkButton(info_dialog, text="OK", command=info_dialog.destroy, width=80).pack(pady=10)
        else:
            self.log("⚠️ Файлы сессии не найдены. Возможно, профиль уже был удалён.")

    # ---------- Вкладка личных сообщений ----------
    def create_private_tab(self):
        """Вкладка для личных сообщений - пересылка 2 любых сообщений"""

        # Блок "Первое сообщение"
        self.frame_msg1 = ctk.CTkFrame(self.tab_private)
        self.frame_msg1.grid(row=0, column=0, columnspan=4, padx=10, pady=10, sticky="ew")

        ctk.CTkLabel(self.frame_msg1, text="📨 ПЕРВОЕ СООБЩЕНИЕ", font=("Arial", 14, "bold")).grid(row=0, column=0, columnspan=4, padx=5, pady=5, sticky="w")

        ctk.CTkLabel(self.frame_msg1, text="Чат-источник:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.ls_chat_1_entry = ctk.CTkEntry(self.frame_msg1, width=300)
        self.ls_chat_1_entry.grid(row=1, column=1, padx=5, pady=5)
        self.ls_chat_1_entry.insert(0, self.config.get("ls_source_chat_1", ""))

        self.ls_auto_1_var = ctk.BooleanVar(value=self.config.get("ls_auto_find_1", True))
        self.ls_auto_1_check = ctk.CTkCheckBox(self.frame_msg1, text="авто-поиск последнего", variable=self.ls_auto_1_var)
        self.ls_auto_1_check.grid(row=1, column=2, padx=5, pady=5)

        ctk.CTkLabel(self.frame_msg1, text="ID сообщений (через запятую):").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.ls_ids_1_entry = ctk.CTkEntry(self.frame_msg1, width=400)
        self.ls_ids_1_entry.grid(row=2, column=1, columnspan=2, padx=5, pady=5, sticky="w")
        self.ls_ids_1_entry.insert(0, self.config.get("ls_message_ids_1", ""))

        # Блок "Второе сообщение"
        self.frame_msg2 = ctk.CTkFrame(self.tab_private)
        self.frame_msg2.grid(row=1, column=0, columnspan=4, padx=10, pady=10, sticky="ew")

        ctk.CTkLabel(self.frame_msg2, text="📨 ВТОРОЕ СООБЩЕНИЕ", font=("Arial", 14, "bold")).grid(row=0, column=0, columnspan=4, padx=5, pady=5, sticky="w")

        ctk.CTkLabel(self.frame_msg2, text="Чат-источник:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.ls_chat_2_entry = ctk.CTkEntry(self.frame_msg2, width=300)
        self.ls_chat_2_entry.grid(row=1, column=1, padx=5, pady=5)
        self.ls_chat_2_entry.insert(0, self.config.get("ls_source_chat_2", ""))

        self.ls_auto_2_var = ctk.BooleanVar(value=self.config.get("ls_auto_find_2", True))
        self.ls_auto_2_check = ctk.CTkCheckBox(self.frame_msg2, text="авто-поиск последнего", variable=self.ls_auto_2_var)
        self.ls_auto_2_check.grid(row=1, column=2, padx=5, pady=5)

        ctk.CTkLabel(self.frame_msg2, text="ID сообщений (через запятую):").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.ls_ids_2_entry = ctk.CTkEntry(self.frame_msg2, width=400)
        self.ls_ids_2_entry.grid(row=2, column=1, columnspan=2, padx=5, pady=5, sticky="w")
        self.ls_ids_2_entry.insert(0, self.config.get("ls_message_ids_2", ""))

        # Настройки рассылки
        ctk.CTkLabel(self.tab_private, text="⚙️ НАСТРОЙКИ РАССЫЛКИ", font=("Arial", 14, "bold")).grid(row=2, column=0, columnspan=4, padx=10, pady=(10, 5), sticky="w")

        ctk.CTkLabel(self.tab_private, text="Интервал между сообщениями (сек):").grid(row=3, column=0, padx=10, pady=5, sticky="w")
        self.ls_interval_entry = ctk.CTkEntry(self.tab_private, width=100)
        self.ls_interval_entry.grid(row=3, column=1, padx=10, pady=5, sticky="w")
        self.ls_interval_entry.insert(0, str(self.config.get("ls_message_interval", 150)))

        ctk.CTkLabel(self.tab_private, text="Интервал между получателями (сек):").grid(row=4, column=0, padx=10, pady=5, sticky="w")
        self.delay_entry = ctk.CTkEntry(self.tab_private, width=100)
        self.delay_entry.grid(row=4, column=1, padx=10, pady=5, sticky="w")
        self.delay_entry.insert(0, str(self.config.get("delay_between_sends", 360)))

        ctk.CTkLabel(self.tab_private, text="Время первого сообщения (HH:MM или YYYY-MM-DD HH:MM:SS):").grid(row=5, column=0, padx=10, pady=5, sticky="w")
        self.start_time_entry = ctk.CTkEntry(self.tab_private, width=300)
        self.start_time_entry.grid(row=5, column=1, padx=10, pady=5)
        self.start_time_entry.insert(0, "")

        # Файл получателей
        ctk.CTkLabel(self.tab_private, text="Файл получателей:").grid(row=6, column=0, padx=10, pady=5, sticky="w")
        self.recipients_file_entry = ctk.CTkEntry(self.tab_private, width=300)
        self.recipients_file_entry.grid(row=6, column=1, padx=10, pady=5)
        self.recipients_file_entry.insert(0, self.config.get("recipients_file", "recipients.txt"))
        self.browse_recipients_button = ctk.CTkButton(self.tab_private, text="Обзор", command=self.browse_recipients_file)
        self.browse_recipients_button.grid(row=6, column=2, padx=5, pady=5)
        self.load_recipients_button = ctk.CTkButton(self.tab_private, text="Загрузить", command=self.load_recipients_from_file)
        self.load_recipients_button.grid(row=6, column=3, padx=5, pady=5)

        # Редактор получателей
        ctk.CTkLabel(self.tab_private, text="Редактировать список получателей:").grid(row=7, column=0, padx=10, pady=5, sticky="w")
        self.recipients_text = ctk.CTkTextbox(self.tab_private, height=200, wrap="none")
        self.recipients_text.grid(row=8, column=0, columnspan=4, padx=10, pady=5, sticky="nsew")
        self.tab_private.grid_rowconfigure(8, weight=1)
        self.tab_private.grid_columnconfigure(1, weight=1)

        self.save_recipients_button = ctk.CTkButton(self.tab_private, text="Сохранить получателей", command=self.save_recipients)
        self.save_recipients_button.grid(row=9, column=0, columnspan=4, padx=10, pady=5)

        # Проверка статуса аккаунта
        self.check_status_var = ctk.BooleanVar(value=False)
        self.check_status_check = ctk.CTkCheckBox(
            self.tab_private, 
            text="🔍 Проверить статус аккаунта перед рассылкой (через @SpamBot)",
            variable=self.check_status_var
        )
        self.check_status_check.grid(row=11, column=0, columnspan=4, padx=10, pady=5, sticky="w")

        self.status_button = ctk.CTkButton(
            self.tab_private, 
            text="📊 Проверить статус сейчас",
            command=self.check_account_status,
            width=200
        )
        self.status_button.grid(row=12, column=0, columnspan=4, padx=10, pady=5, sticky="w")

    def check_account_status(self):
        """Проверяет статус аккаунта через @SpamBot"""
        if not self.authorized:
            self.log("❌ Профиль не авторизован! Сначала авторизуйтесь.")
            return

        self.log("🔍 Проверка статуса аккаунта через @SpamBot...")
        thread = threading.Thread(target=self.run_status_check, daemon=True)
        thread.start()

    def run_status_check(self):
        """Запускает асинхронную проверку статуса"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.async_check_account_status())
        except Exception as e:
            self.log(f"Ошибка проверки статуса: {e}")
        finally:
            loop.close()

    async def async_check_account_status(self):
        """Асинхронная проверка статуса аккаунта через @SpamBot"""
        api_id = int(self.api_id_entry.get())
        api_hash = self.api_hash_entry.get()
        client = TelegramClient('user_session', api_id, api_hash)

        try:
            await client.start()

            # Получаем @SpamBot
            spam_bot = await client.get_entity('@SpamBot')

            # Отправляем /start
            await client.send_message(spam_bot, '/start')

            # Ждём ответа
            await asyncio.sleep(2)

            # Читаем последние сообщения
            has_restrictions = False
            async for msg in client.iter_messages(spam_bot, limit=5):
                text = msg.text.lower() if msg.text else ""

                if "не имеет ограничений" in text or "no restrictions" in text:
                    self.log("✅ Аккаунт в хорошем состоянии, ограничений нет!")
                elif "ограничения" in text or "restrictions" in text:
                    self.log("⚠️ ВНИМАНИЕ! Аккаунт имеет ограничения!")
                    has_restrictions = True
                    self.log(f"   Сообщение: {msg.text[:200]}")
                elif "жалобы" in text or "complaints" in text:
                    self.log("⚠️ На аккаунт поступали жалобы!")

            if not has_restrictions:
                self.log("✅ Статус аккаунта: нормальный")

        except Exception as e:
            self.log(f"❌ Ошибка при проверке: {e}")
        finally:
            await client.disconnect()

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
        self.source_frame.grid(row=0, column=0, columnspan=4, padx=10, pady=5, sticky="ew")

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

        # Интервал между циклами
        ctk.CTkLabel(self.tab_groups, text="Интервал между циклами (сек):").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.group_interval_entry = ctk.CTkEntry(self.tab_groups, width=100)
        self.group_interval_entry.grid(row=1, column=1, padx=10, pady=5, sticky="w")
        self.group_interval_entry.insert(0, str(self.config.get("group_cycle_interval", 720)))

        # Файл групп
        ctk.CTkLabel(self.tab_groups, text="Файл групп:").grid(row=2, column=0, padx=10, pady=5, sticky="w")
        self.groups_file_entry = ctk.CTkEntry(self.tab_groups, width=300)
        self.groups_file_entry.grid(row=2, column=1, padx=10, pady=5)
        self.groups_file_entry.insert(0, self.config.get("groups_file", "groups.txt"))
        self.browse_groups_button = ctk.CTkButton(self.tab_groups, text="Обзор", command=self.browse_groups_file)
        self.browse_groups_button.grid(row=2, column=2, padx=5, pady=5)
        self.load_groups_button = ctk.CTkButton(self.tab_groups, text="Загрузить", command=self.load_groups_from_file)
        self.load_groups_button.grid(row=2, column=3, padx=5, pady=5)

        # Редактор списка групп
        ctk.CTkLabel(self.tab_groups, text="Редактировать список групп:").grid(row=3, column=0, padx=10, pady=5, sticky="w")
        self.groups_text = ctk.CTkTextbox(self.tab_groups, height=200, wrap="none")
        self.groups_text.grid(row=4, column=0, columnspan=4, padx=10, pady=5, sticky="nsew")
        self.tab_groups.grid_rowconfigure(4, weight=1)
        self.tab_groups.grid_columnconfigure(1, weight=1)

        self.save_groups_button = ctk.CTkButton(self.tab_groups, text="Сохранить группы", command=self.save_groups)
        self.save_groups_button.grid(row=5, column=0, columnspan=4, padx=10, pady=5)

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

    def browse_recipients_file(self):
        file_path = filedialog.askopenfilename(title="Выберите файл получателей")
        if file_path:
            self.recipients_file_entry.delete(0, "end")
            self.recipients_file_entry.insert(0, file_path)
            self.load_recipients_from_file()

    def load_recipients_from_file(self):
        file_path = self.recipients_file_entry.get()
        if Path(file_path).exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                self.recipients_text.delete("1.0", "end")
                self.recipients_text.insert("1.0", f.read())
            self.log(f"Загружен список получателей из {file_path}")
        else:
            self.log(f"Файл {file_path} не найден")

    def browse_groups_file(self):
        file_path = filedialog.askopenfilename(title="Выберите файл групп")
        if file_path:
            self.groups_file_entry.delete(0, "end")
            self.groups_file_entry.insert(0, file_path)
            self.load_groups_from_file()

    def load_groups_from_file(self):
        file_path = self.groups_file_entry.get()
        if Path(file_path).exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                self.groups_text.delete("1.0", "end")
                self.groups_text.insert("1.0", f.read())
            self.log(f"Загружен список групп из {file_path}")
        else:
            self.log(f"Файл {file_path} не найден")

    def browse_emails_file(self):
        file_path = filedialog.askopenfilename(title="Выберите файл email адресов")
        if file_path:
            self.emails_file_entry.delete(0, "end")
            self.emails_file_entry.insert(0, file_path)
            self.load_emails_from_file()

    def load_emails_from_file(self):
        file_path = self.emails_file_entry.get()
        if Path(file_path).exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                self.emails_text.delete("1.0", "end")
                self.emails_text.insert("1.0", f.read())
            self.log(f"Загружен список email адресов из {file_path}")
        else:
            self.log(f"Файл {file_path} не найден")

    # ---------- Вкладка email ----------
    def create_email_tab(self):
        row = 0

        ctk.CTkLabel(self.tab_email, text="SMTP сервер:").grid(row=row, column=0, padx=10, pady=5, sticky="w")
        self.email_smtp_entry = ctk.CTkEntry(self.tab_email, width=300)
        self.email_smtp_entry.grid(row=row, column=1, padx=10, pady=5)
        self.email_smtp_entry.insert(0, self.config.get("email_smtp_server", "smtp.gmail.com"))
        row += 1

        ctk.CTkLabel(self.tab_email, text="Порт:").grid(row=row, column=0, padx=10, pady=5, sticky="w")
        self.email_port_entry = ctk.CTkEntry(self.tab_email, width=100)
        self.email_port_entry.grid(row=row, column=1, padx=10, pady=5, sticky="w")
        self.email_port_entry.insert(0, str(self.config.get("email_smtp_port", 587)))
        row += 1

        ctk.CTkLabel(self.tab_email, text="Логин (email отправителя):").grid(row=row, column=0, padx=10, pady=5, sticky="w")
        self.email_login_entry = ctk.CTkEntry(self.tab_email, width=300)
        self.email_login_entry.grid(row=row, column=1, padx=10, pady=5)
        self.email_login_entry.insert(0, self.config.get("email_login", ""))
        row += 1

        ctk.CTkLabel(self.tab_email, text="Пароль (или app password):").grid(row=row, column=0, padx=10, pady=5, sticky="w")
        self.email_password_entry = ctk.CTkEntry(self.tab_email, width=300, show="")
        self.email_password_entry.grid(row=row, column=1, padx=10, pady=5)
        self.email_password_entry.insert(0, self.config.get("email_password", ""))
        row += 1

        ctk.CTkLabel(self.tab_email, text="Тема письма:").grid(row=row, column=0, padx=10, pady=5, sticky="w")
        self.email_subject_entry = ctk.CTkEntry(self.tab_email, width=400)
        self.email_subject_entry.grid(row=row, column=1, padx=10, pady=5)
        self.email_subject_entry.insert(0, self.config.get("email_subject", "Привет!"))
        row += 1

        ctk.CTkLabel(self.tab_email, text="Текст письма (HTML поддерживается):").grid(row=row, column=0, padx=10, pady=5, sticky="w")
        self.email_body_text = ctk.CTkTextbox(self.tab_email, height=150, wrap="word")
        self.email_body_text.grid(row=row, column=1, padx=10, pady=5, sticky="ew")
        self.email_body_text.insert("1.0", self.config.get("email_body", "Это тестовое письмо."))
        row += 1

        ctk.CTkLabel(self.tab_email, text="Интервал между письмами (сек):").grid(row=row, column=0, padx=10, pady=5, sticky="w")
        self.email_interval_entry = ctk.CTkEntry(self.tab_email, width=100)
        self.email_interval_entry.grid(row=row, column=1, padx=10, pady=5, sticky="w")
        self.email_interval_entry.insert(0, str(self.config.get("email_interval", 60)))
        row += 1

        # Файл email адресов
        ctk.CTkLabel(self.tab_email, text="Файл email адресов:").grid(row=row, column=0, padx=10, pady=5, sticky="w")
        self.emails_file_entry = ctk.CTkEntry(self.tab_email, width=300)
        self.emails_file_entry.grid(row=row, column=1, padx=10, pady=5)
        self.emails_file_entry.insert(0, self.config.get("emails_file", "emails.txt"))
        self.browse_emails_button = ctk.CTkButton(self.tab_email, text="Обзор", command=self.browse_emails_file)
        self.browse_emails_button.grid(row=row, column=2, padx=5, pady=5)
        self.load_emails_button = ctk.CTkButton(self.tab_email, text="Загрузить", command=self.load_emails_from_file)
        self.load_emails_button.grid(row=row, column=3, padx=5, pady=5)
        row += 1

        # Редактор email адресов
        ctk.CTkLabel(self.tab_email, text="Редактировать список email адресов:").grid(row=row, column=0, padx=10, pady=5, sticky="w")
        self.emails_text = ctk.CTkTextbox(self.tab_email, height=200, wrap="none")
        self.emails_text.grid(row=row+1, column=0, columnspan=4, padx=10, pady=5, sticky="nsew")
        self.tab_email.grid_rowconfigure(row+1, weight=1)
        self.tab_email.grid_columnconfigure(1, weight=1)

        self.save_emails_button = ctk.CTkButton(self.tab_email, text="Сохранить список email", command=self.save_emails)
        self.save_emails_button.grid(row=row+2, column=0, columnspan=4, padx=10, pady=5)

    def load_emails_into_text(self):
        file_path = self.emails_file_entry.get()
        if Path(file_path).exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                self.emails_text.delete("1.0", "end")
                self.emails_text.insert("1.0", f.read())
        else:
            self.emails_text.delete("1.0", "end")

    def save_emails(self):
        content = self.emails_text.get("1.0", "end-1c")
        file_path = self.emails_file_entry.get()
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        self.log("Список email сохранён в файл.")

    def browse_emails_file(self):
        file_path = filedialog.askopenfilename(title="Выберите файл email адресов")
        if file_path:
            self.emails_file_entry.delete(0, "end")
            self.emails_file_entry.insert(0, file_path)
            self.load_emails_from_file()

    def load_emails_from_file(self):
        file_path = self.emails_file_entry.get()
        if Path(file_path).exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                self.emails_text.delete("1.0", "end")
                self.emails_text.insert("1.0", f.read())
            self.log(f"Загружен список email адресов из {file_path}")
        else:
            self.log(f"Файл {file_path} не найден")

    # ---------- Вкладка логов ----------
    def create_logs_tab(self):
        top_frame = ctk.CTkFrame(self.tab_logs)
        top_frame.pack(fill="x", padx=10, pady=(10, 0))

        self.clear_logs_button = ctk.CTkButton(
            top_frame, text="Очистить логи", 
            command=self.clear_logs, width=120
        )
        self.clear_logs_button.pack(side="right", padx=5, pady=5)

        # Текстовое поле для логов (только один раз!)
        self.log_text = ctk.CTkTextbox(self.tab_logs, wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=10, pady=(5, 10))

    def clear_logs(self):
        """Очищает текстовое поле логов"""
        self.log_text.delete("1.0", "end")
    def log(self, message):
        """Добавляет сообщение в текстовое поле логов (GUI-безопасно)"""
        def _log():
            if hasattr(self, 'log_text') and self.log_text:
                self.log_text.insert("end", message + "\n")
                self.log_text.see("end")
        self.after(0, _log)

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

    # ---------- Управление рассылкой ЛС ----------
    def toggle_ls_mailing(self):
        if self.running_ls:
            self.stop_ls_mailing()
        else:
            self.start_ls_mailing()

    def start_ls_mailing(self):
        if self.running_groups:
            self.stop_groups_mailing()
        self.save_config()
        self.save_recipients()
        self.save_groups()

        if not self.api_id_entry.get() or not self.api_hash_entry.get():
            self.log("Ошибка: не указаны API ID и/или API Hash")
            return

        self.running_ls = True
        self.start_stop_ls_button.configure(text="Остановить ЛС")
        self.log("Запуск рассылки ЛС...")
        self.ls_thread = threading.Thread(target=self.run_ls_loop, daemon=True)
        self.ls_thread.start()

    def stop_ls_mailing(self):
        self.running_ls = False
        self.log("Остановка рассылки ЛС...")

    def run_ls_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.async_ls_mode())
        except Exception as e:
            self.log(f"Критическая ошибка в ЛС: {e}")
        finally:
            loop.close()
            self.after(0, lambda: self.start_stop_ls_button.configure(text="Запустить ЛС"))
            self.running_ls = False

    async def async_ls_mode(self):
        api_id = int(self.api_id_entry.get())
        api_hash = self.api_hash_entry.get()
        tz_offset = int(self.tz_entry.get())
        await self.run_private_mode(api_id, api_hash, tz_offset)

    # ---------- Управление рассылкой групп ----------
    def toggle_groups_mailing(self):
        if self.running_groups:
            self.stop_groups_mailing()
        else:
            self.start_groups_mailing()

    def start_groups_mailing(self):
        if self.running_ls:
            self.stop_ls_mailing()
        self.save_config()
        self.save_recipients()
        self.save_groups()

        if not self.api_id_entry.get() or not self.api_hash_entry.get():
            self.log("Ошибка: не указаны API ID и/или API Hash")
            return

        self.running_groups = True
        self.start_stop_groups_button.configure(text="Остановить группы")
        self.log("Запуск рассылки групп...")
        self.groups_thread = threading.Thread(target=self.run_groups_loop, daemon=True)
        self.groups_thread.start()

    def stop_groups_mailing(self):
        self.running_groups = False
        self.log("Остановка рассылки групп...")

    def run_groups_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.async_groups_mode())
        except Exception as e:
            self.log(f"Критическая ошибка в группах: {e}")
        finally:
            loop.close()
            self.after(0, lambda: self.start_stop_groups_button.configure(text="Запустить группы"))
            self.running_groups = False

    async def async_groups_mode(self):
        api_id = int(self.api_id_entry.get())
        api_hash = self.api_hash_entry.get()
        tz_offset = int(self.tz_entry.get())
        await self.run_groups_mode(api_id, api_hash, tz_offset)

    # ---------- Управление Email рассылкой ----------
    def toggle_email_mailing(self):
        if self.running_email:
            self.stop_email_mailing()
        else:
            self.start_email_mailing()

    def start_email_mailing(self):
        self.save_config()
        self.save_emails()

        smtp_server = self.email_smtp_entry.get()
        if not smtp_server:
            self.log("Ошибка: не указан SMTP сервер")
            return
        email_login = self.email_login_entry.get()
        email_password = self.email_password_entry.get()
        if not email_login or not email_password:
            self.log("Ошибка: не указаны логин или пароль для SMTP")
            return

        self.running_email = True
        self.start_stop_email_button.configure(text="Остановить Email рассылку")
        self.log("Запуск Email рассылки...")
        self.email_thread = threading.Thread(target=self.run_email_mailing, daemon=True)
        self.email_thread.start()

    def stop_email_mailing(self):
        self.running_email = False
        self.log("Остановка Email рассылки...")

    def run_email_mailing(self):
        """Запускает цикл отправки писем в отдельном потоке (без asyncio)"""
        emails_file = self.emails_file_entry.get()
        emails = self.load_emails_from_file(emails_file)
        if not emails:
            self.log("Нет email адресов для рассылки.")
            self.stop_email_mailing()
            return

        interval = int(self.email_interval_entry.get())
        subject = self.email_subject_entry.get()
        body = self.email_body_text.get("1.0", "end-1c")
        is_html = body.strip().startswith("<html>") or body.strip().startswith("<!DOCTYPE")
        smtp_server = self.email_smtp_entry.get()
        smtp_port = int(self.email_port_entry.get())
        login = self.email_login_entry.get()
        password = self.email_password_entry.get()

        success = 0
        fail = 0
        total = len(emails)

        for i, recipient in enumerate(emails, start=1):
            if not self.running_email:
                break
            self.log(f"[{i}/{total}] Отправка письма на {recipient}")
            ok = self.send_email_via_smtp(
                smtp_server, smtp_port, login, password,
                recipient, subject, body, is_html
            )
            if ok:
                success += 1
            else:
                fail += 1
            if i < total and self.running_email:
                self.log(f"Ожидание {interval} сек...")
                for _ in range(interval):
                    if not self.running_email:
                        break
                    time.sleep(1)

        self.log(f"Email рассылка завершена. Успешно: {success}, Ошибок: {fail}")
        self.after(0, lambda: self.start_stop_email_button.configure(text="Запустить Email рассылку"))
        self.running_email = False

    def load_emails_from_file(self, file_path):
        if not Path(file_path).exists():
            self.log(f"Файл email адресов не найден: {file_path}")
            return []
        with open(file_path, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip()]

    def send_email_via_smtp(self, server, port, login, password, to, subject, body, is_html):
        try:
            msg = MIMEMultipart()
            msg['From'] = login
            msg['To'] = to
            msg['Subject'] = subject
            if is_html:
                msg.attach(MIMEText(body, 'html', 'utf-8'))
            else:
                msg.attach(MIMEText(body, 'plain', 'utf-8'))

            if port == 465:
                with smtplib.SMTP_SSL(server, port) as srv:
                    srv.login(login, password)
                    srv.send_message(msg)
            else:
                with smtplib.SMTP(server, port) as srv:
                    srv.starttls()
                    srv.login(login, password)
                    srv.send_message(msg)
            self.log(f"Письмо отправлено на {to}")
            return True
        except Exception as e:
            self.log(f"Ошибка отправки на {to}: {e}")
            return False

    async def run_private_mode(self, api_id, api_hash, tz_offset):
        """Режим ЛС - пересылка 2 любых сообщений"""

        # Проверяем, есть ли файл сессии (авторизованы ли мы)
        if not Path("user_session.session").exists():
            self.log("❌ Профиль не авторизован! Сначала авторизуйтесь в настройках.")
            return

        # Проверяем, что у нас есть api_id и api_hash
        if not api_id or not api_hash:
            self.log("❌ Не указаны API ID или API Hash")
            return

        # СОЗДАЁМ НОВОГО КЛИЕНТА (используем сохранённую сессию)
        client = TelegramClient('user_session', api_id, api_hash)

        # Проверка статуса аккаунта перед рассылкой
        if self.check_status_var.get():
            self.log("🔍 Проверка статуса аккаунта перед рассылкой...")
            client_temp = TelegramClient('user_session', api_id, api_hash)
            try:
                await client_temp.start()
                spam_bot = await client_temp.get_entity('@SpamBot')
                await client_temp.send_message(spam_bot, '/start')
                await asyncio.sleep(2)

                has_restrictions = False
                async for msg in client_temp.iter_messages(spam_bot, limit=3):
                    if "ограничения" in (msg.text or "").lower():
                        has_restrictions = True
                        break

                if has_restrictions:
                    self.log("❌ Обнаружены ограничения на аккаунте! Рассылка отменена.")
                    return
                else:
                    self.log("✅ Статус аккаунта нормальный, продолжаем...")
            except Exception as e:
                self.log(f"⚠️ Не удалось проверить статус: {e}")
            finally:
                await client_temp.disconnect()

        try:
            await client.start()
            self.log("✅ Клиент подключён")

            # Получаем получателей
            recipients_file = self.recipients_file_entry.get()
            recipients = self.load_recipients(recipients_file)
            if not recipients:
                self.log("Нет получателей для рассылки ЛС.")
                return

            # Получаем сообщения для первого и второго слота
            messages_1 = await self.get_source_messages(
                client,
                self.ls_chat_1_entry.get(),
                self.ls_auto_1_var.get(),
                self.ls_ids_1_entry.get()
            )
            if not messages_1:
                self.log("Не удалось получить ни одного сообщения для первого слота. Отмена.")
                return

            messages_2 = await self.get_source_messages(
                client,
                self.ls_chat_2_entry.get(),
                self.ls_auto_2_var.get(),
                self.ls_ids_2_entry.get()
            )
            if not messages_2:
                self.log("Не удалось получить ни одного сообщения для второго слота. Отмена.")
                return

            msg_interval = int(self.ls_interval_entry.get())
            delay = int(self.delay_entry.get())
            first_time = self.parse_start_time(self.start_time_entry.get())

            await self.schedule_two_messages(
                client, recipients,
                messages_1, messages_2,
                delay, msg_interval, first_time, tz_offset
            )

        except errors.rpcerrorlist.ApiIdInvalidError:
            self.log("Неверный API_ID или API_HASH.")
        except Exception as e:
            self.log(f"Ошибка в режиме ЛС: {e}")
        finally:
            await client.disconnect()
            self.log("Клиент отключён")

    def load_recipients(self, file_path):
        if not Path(file_path).exists():
            self.log(f"Файл получателей не найден: {file_path}")
            return []
        with open(file_path, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip()]
    async def schedule_two_messages(self, client, recipients, msgs_1, msgs_2, delay, msg_interval, first_time, tz_offset):
        """Планирует пересылку двух сообщений для каждого получателя"""
        success_1 = 0
        fail_1 = 0
        success_2 = 0
        fail_2 = 0
        total = len(recipients)

        now = datetime.now()
        if first_time and first_time > now:
            first_schedule = first_time
        else:
            first_schedule = now + timedelta(seconds=delay)

        for i, recipient in enumerate(recipients, start=1):
            # Время для первого сообщения
            time_1 = first_schedule + timedelta(seconds=(i-1)*delay)
            time_1_utc = time_1 - timedelta(hours=tz_offset)
            display_time_1 = time_1

            # Время для второго сообщения
            time_2 = time_1 + timedelta(seconds=msg_interval)
            time_2_utc = time_2 - timedelta(hours=tz_offset)
            display_time_2 = time_2

            self.log(f"[{i}/{total}] Планирование для {recipient}:")
            self.log(f"  Сообщение 1 на {display_time_1.strftime('%Y-%m-%d %H:%M:%S')}")
            self.log(f"  Сообщение 2 на {display_time_2.strftime('%Y-%m-%d %H:%M:%S')}")

            # Первое сообщение (случайное из списка)
            msg_1 = random.choice(msgs_1)
            if msg_1:
                try:
                    entity = await client.get_entity(recipient)
                    await client.forward_messages(
                        entity, msg_1,
                        drop_author=True,
                        schedule=time_1_utc
                    )
                    success_1 += 1
                except errors.FloodWaitError as e:
                    self.log(f"Flood wait для {recipient}: ждём {e.seconds} сек")
                    await asyncio.sleep(e.seconds)
                    try:
                        entity = await client.get_entity(recipient)
                        await client.forward_messages(entity, msg_1, drop_author=True, schedule=time_1_utc)
                        success_1 += 1
                    except Exception as e2:
                        self.log(f"Ошибка при отправке первого сообщения {recipient}: {e2}")
                        fail_1 += 1
                except Exception as e:
                    self.log(f"Ошибка планирования первого сообщения {recipient}: {e}")
                    fail_1 += 1
            else:
                fail_1 += 1

            # Второе сообщение (случайное из списка)
            msg_2 = random.choice(msgs_2)
            if msg_2:
                try:
                    entity = await client.get_entity(recipient)
                    await client.forward_messages(
                        entity, msg_2,
                        drop_author=True,
                        schedule=time_2_utc
                    )
                    success_2 += 1
                except errors.FloodWaitError as e:
                    self.log(f"Flood wait для {recipient}: ждем {e.seconds} сек")
                    await asyncio.sleep(e.seconds)
                    try:
                        entity = await client.get_entity(recipient)
                        await client.forward_messages(entity, msg_2, drop_author=True, schedule=time_2_utc)
                        success_2 += 1
                    except Exception as e2:
                        self.log(f"Ошибка при отправке второго сообщения {recipient}: {e2}")
                        fail_2 += 1
                except Exception as e:
                    self.log(f"Ошибка планирования второго сообщения {recipient}: {e}")
                    fail_2 += 1
            else:
                fail_2 += 1

        self.log(f"Планирование завершено. Сообщение 1: успешно {success_1}, ошибок {fail_1}. Сообщение 2: успешно {success_2}, ошибок {fail_2}")
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

        # Список для отслеживания запланированных сообщений
        scheduled_tracking = []

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

            # Словарь для хранения информации о текущем получателе
            recipient_tracking = {
                "recipient": recipient,
                "schedule_time": schedule_time.isoformat(),
                "note_scheduled": False,
                "video_scheduled": False,
                "note_msg_id": None,
                "video_msg_id": None
            }

            # 1. Отправка кружка (выбираем случайный из списка)
            note_msg = random.choice(note_msgs) if note_msgs else None
            if note_msg:
                try:
                    entity = await client.get_entity(recipient)
                    result = await client.forward_messages(
                        entity,
                        note_msg,
                        drop_author=True,
                        schedule=schedule_time_utc
                    )
                    success_notes += 1
                    recipient_tracking["note_scheduled"] = True
                    # Сохраняем ID запланированного сообщения (если доступно)
                    if hasattr(result, 'id'):
                        recipient_tracking["note_msg_id"] = result.id
                    self.log(f"  Кружок запланирован")
                except errors.FloodWaitError as e:
                    self.log(f"Flood wait для {recipient}: ждём {e.seconds} сек")
                    await asyncio.sleep(e.seconds)
                    try:
                        entity = await client.get_entity(recipient)
                        result = await client.forward_messages(entity, note_msg, drop_author=True, schedule=schedule_time_utc)
                        success_notes += 1
                        recipient_tracking["note_scheduled"] = True
                        if hasattr(result, 'id'):
                            recipient_tracking["note_msg_id"] = result.id
                        self.log(f"  Кружок запланирован (после ожидания)")
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
                    result = await client.forward_messages(
                        entity,
                        video_msg,
                        drop_author=True,
                        schedule=video_schedule_utc
                    )
                    success_videos += 1
                    recipient_tracking["video_scheduled"] = True
                    if hasattr(result, 'id'):
                        recipient_tracking["video_msg_id"] = result.id
                    self.log(f"  Видео запланировано на {video_display.strftime('%Y-%m-%d %H:%M:%S')}")
                except errors.FloodWaitError as e:
                    self.log(f"Flood wait для видео {recipient}: ждём {e.seconds} сек")
                    await asyncio.sleep(e.seconds)
                    try:
                        entity = await client.get_entity(recipient)
                        result = await client.forward_messages(entity, video_msg, drop_author=True, schedule=video_schedule_utc)
                        success_videos += 1
                        recipient_tracking["video_scheduled"] = True
                        if hasattr(result, 'id'):
                            recipient_tracking["video_msg_id"] = result.id
                        self.log(f"  Видео запланировано (после ожидания)")
                    except Exception as e2:
                        self.log(f"Ошибка при повторной отправке видео {recipient}: {e2}")
                        fail_videos += 1
                except Exception as e:
                    self.log(f"Ошибка планирования видео {recipient}: {e}")
                    fail_videos += 1

            # Если хотя бы одно сообщение было запланировано, добавляем в отслеживание
            if recipient_tracking["note_scheduled"] or recipient_tracking["video_scheduled"]:
                scheduled_tracking.append(recipient_tracking)

        # Сохраняем отслеживание запланированных сообщений
        if scheduled_tracking:
            self.save_scheduled_tracking(scheduled_tracking)

        self.log(f"Планирование завершено. Кружки: успешно {success_notes}, ошибок {fail_notes}. Видео: успешно {success_videos}, ошибок {fail_videos}")

    # ---------- Режим групп ----------
    async def run_groups_mode(self, api_id, api_hash, tz_offset):
        """Режим групп: бесконечно пересылает случайное сообщение из указанного чата во все группы"""

        # Проверяем, есть ли файл сессии (авторизованы ли мы)
        if not Path("user_session.session").exists():
            self.log("❌ Профиль не авторизован! Сначала авторизуйтесь в настройках.")
            return

        # Проверяем, что у нас есть api_id и api_hash
        if not api_id or not api_hash:
            self.log("❌ Не указаны API ID или API Hash")
            return

        # Загружаем список групп
        groups_file = self.groups_file_entry.get()
        groups = self.load_groups(groups_file)
        if not groups:
            self.log("Нет групп для рассылки.")
            return

        # Получаем интервал между циклами
        cycle_interval = int(self.group_interval_entry.get())
        if cycle_interval <= 0:
            self.log("Интервал между циклами должен быть больше 0.")
            return

        # Получаем настройки источника сообщений
        source_chat = self.group_chat_entry.get()
        auto_find = self.group_auto_var.get()
        ids_str = self.group_ids_entry.get()

        # СОЗДАЁМ НОВОГО КЛИЕНТА (используем сохранённую сессию)
        client = TelegramClient('user_session', api_id, api_hash)

        try:
            await client.start()
            self.log("✅ Клиент подключён")

            # Получаем сообщения-источники из указанного чата
            source_messages = await self.get_source_messages(
                client,
                source_chat,
                auto_find,
                ids_str
            )

            if not source_messages:
                self.log(f"❌ Не удалось получить ни одного сообщения из чата {source_chat}. Отмена.")
                return

            self.log(f"📥 Загружено {len(source_messages)} сообщений-источников (ID: {', '.join(str(m.id) for m in source_messages)}).")

            # Запускаем бесконечную рассылку с пересылкой
            await self.infinite_scheduled_group_mailing(
                client,
                groups,
                source_messages,
                cycle_interval,
                tz_offset
            )

        except errors.rpcerrorlist.ApiIdInvalidError:
            self.log("❌ Неверный API_ID или API_HASH.")
        except Exception as e:
            self.log(f"❌ Ошибка в режиме групп: {e}")
        finally:
            await client.disconnect()
            self.log("🔌 Клиент отключён")

    def load_groups(self, file_path):
        """Загружает список групп из файла"""
        if not Path(file_path).exists():
            self.log(f"⚠️ Файл групп не найден: {file_path}")
            return []
        with open(file_path, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip()]

    async def infinite_scheduled_group_mailing(self, client, groups, source_messages, cycle_interval, tz_offset):
        """Бесконечная рассылка с пересылкой сообщений в группы"""
        cycle_num = 1
        schedule_delta = timedelta(seconds=cycle_interval)

        while self.running_groups:
            self.log(f"=== Цикл {cycle_num} ===")
            source_msg = random.choice(source_messages)
            self.log(f"📨 Выбрано сообщение ID={source_msg.id} из чата {source_msg.chat_id}")

            for group in groups:
                if not self.running_groups:
                    break
                await self.forward_scheduled_message(client, group, source_msg, schedule_delta, tz_offset)
                await asyncio.sleep(1)  # небольшая пауза между группами

            if not self.running_groups:
                break

            next_cycle_time = datetime.now() + schedule_delta
            next_cycle_local = next_cycle_time + timedelta(hours=tz_offset)
            self.log(f"⏳ Цикл {cycle_num} завершён. Следующий цикл в {next_cycle_local.strftime('%Y-%m-%d %H:%M:%S')} (через {cycle_interval // 60} минут).")

            # Ждём интервал, но с возможностью остановки каждые 5 секунд
            for _ in range(cycle_interval // 5):
                if not self.running_groups:
                    break
                await asyncio.sleep(5)
            if not self.running_groups:
                break

            cycle_num += 1

    async def forward_scheduled_message(self, client, group, source_msg, schedule_delta, tz_offset):
        max_retries = 5
        for attempt in range(max_retries):
            try:
                entity = await client.get_entity(group)
                schedule_time_utc = datetime.now(timezone.utc) + schedule_delta
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
                schedule_time_utc = datetime.now(timezone.utc) + schedule_delta
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

    async def close_client(self):
        if self.client:
            try:
                await self.client.disconnect()
            except:
                pass
            self.client = None

    def save_scheduled_tracking(self, scheduled_data):
        """Сохраняет информацию о запланированных сообщениях для последующей проверки"""
        tracking_file = "scheduled_tracking.json"

        # Загружаем существующие данные
        existing_data = []
        if Path(tracking_file).exists():
            try:
                with open(tracking_file, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError):
                self.log("Ошибка чтения файла отслеживания, создаю новый")

        # Добавляем новые данные
        existing_data.extend(scheduled_data)

        # Сохраняем обратно
        with open(tracking_file, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, indent=4, ensure_ascii=False)

        self.log(f"Сохранено отслеживание для {len(scheduled_data)} получателей")

    def on_closing(self):
        # Восстанавливаем оригинальные потоки
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        if hasattr(self, 'original_input'):
            import builtins
            builtins.input = self.original_input

        if self.running_ls and self.ls_thread and self.ls_thread.is_alive():
            self.ls_thread.join(timeout=2)
        if self.running_groups and self.groups_thread and self.groups_thread.is_alive():
            self.groups_thread.join(timeout=2)
        if self.running_email and self.email_thread and self.email_thread.is_alive():
            self.email_thread.join(timeout=2)

        # Закрываем клиент в отдельном потоке, чтобы не блокировать GUI
        if self.client:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(self.close_client())
            loop.close()

        self.destroy()


if __name__ == "__main__":
    app = ForwarderApp()
    app.mainloop()