import os
import sys
import subprocess
import shutil

def clean_build():
    """Очистка старых сборок"""
    folders_to_remove = ['build', 'dist', '__pycache__']
    for folder in folders_to_remove:
        if os.path.exists(folder):
            shutil.rmtree(folder)
            print(f"Удалена папка: {folder}")
    
    spec_file = 'main.spec'
    if os.path.exists(spec_file):
        os.remove(spec_file)
        print(f"Удалён файл: {spec_file}")

def install_requirements():
    """Установка зависимостей из requirements.txt"""
    if os.path.exists('requirements.txt'):
        print("Установка зависимостей...")
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'])
        print("Зависимости установлены.")
    else:
        print("Файл requirements.txt не найден!")

def build_exe():
    """Сборка exe файла"""
    print("Начинаем сборку EXE...")
    
    # Команда для PyInstaller
    cmd = [
        'pyinstaller',
        '--onefile',                    # Один файл
        '--windowed',                   # Без консоли (оконное приложение)
        '--name', 'TelegramForwarder',  # Имя файла
        '--icon', 'icon.ico',           # Иконка (если есть)
        '--add-data', 'config.json;.',  # Добавить файлы конфигурации (если нужны)
        '--hidden-import', 'customtkinter',
        '--hidden-import', 'telethon',
        '--hidden-import', 'PIL',
        '--collect-all', 'customtkinter',
        '--collect-all', 'telethon',
        'main.py'
    ]
    
    try:
        subprocess.run(cmd, check=True)
        print("Сборка завершена успешно!")
        print(f"EXE файл находится в папке: {os.path.abspath('dist/TelegramForwarder.exe')}")
    except subprocess.CalledProcessError as e:
        print(f"Ошибка сборки: {e}")
        return False
    return True

def create_portable_version():
    """Создание портативной версии с необходимыми файлами"""
    portable_dir = "TelegramForwarder_portable"
    if not os.path.exists(portable_dir):
        os.makedirs(portable_dir)
    
    # Копируем exe
    shutil.copy('dist/TelegramForwarder.exe', portable_dir)
    
    # Копируем примеры файлов
    example_files = ['recipients.txt', 'groups.txt', 'emails.txt']
    for file in example_files:
        if not os.path.exists(os.path.join(portable_dir, file)):
            with open(os.path.join(portable_dir, file), 'w', encoding='utf-8') as f:
                f.write(f"# Файл {file}\n# Добавьте данные по одному на строку\n")
    
    print(f"Портативная версия создана в папке: {portable_dir}")

if __name__ == "__main__":
    print("=== Сборка Telegram Forwarder ===\n")
    
    # Очистка старых сборок
    clean_build()
    
    # Установка зависимостей (опционально)
    install_requirements()
    
    # Сборка exe
    if build_exe():
        # Создание портативной версии
        create_portable_version()
        
        print("\n=== Готово! ===")
        print("1. EXE файл: dist/TelegramForwarder.exe")
        print("2. Портативная версия: TelegramForwarder_portable/")
        print("\nПри первом запуске на другом ПК программа создаст файлы конфигурации автоматически.")
    else:
        print("\n=== Ошибка сборки ===")