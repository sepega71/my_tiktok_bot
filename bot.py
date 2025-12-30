import asyncio
import json
import logging
import os
import platform
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

import random
import yt_dlp
from TikTokApi import TikTokApi
import weakref
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
ADMIN_ID = int(os.getenv("ADMIN_ID"))
POSTING_INTERVAL_MINUTES = int(os.getenv("POSTING_INTERVAL_MINUTES", 60))  # По умолчанию 60 минут

# Логирование
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Инициализация
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()  # Добавляем диспетчер
scheduler = AsyncIOScheduler()
api_instance = None  # Глобальная переменная для хранения экземпляра TikTokApi


# Database operations class
class DatabaseManager:
    """Класс для управления операциями с базой данных"""
    DB_NAME = 'posted_videos.db'
    
    @classmethod
    def init_db(cls):
        """Инициализирует базу данных для хранения URL опубликованных видео"""
        with sqlite3.connect(cls.DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute('''CREATE TABLE IF NOT EXISTS videos (url TEXT PRIMARY KEY)''')
            conn.commit()

    @classmethod
    def is_video_posted(cls, url: str) -> bool:
        """Проверяет, было ли видео с указанным URL уже опубликовано"""
        with sqlite3.connect(cls.DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT EXISTS(SELECT 1 FROM videos WHERE url=?)', (url,))
            result = cursor.fetchone()[0]
            return bool(result)

    @classmethod
    def get_all_posted_urls(cls) -> set:
        """Получает все URL из таблицы videos в базе данных"""
        with sqlite3.connect(cls.DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT url FROM videos')
            urls = cursor.fetchall()
            return {url[0] for url in urls}

    @classmethod
    def add_posted_video(cls, url: str):
        """Добавляет URL опубликованного видео в базу данных"""
        with sqlite3.connect(cls.DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT OR IGNORE INTO videos (url) VALUES (?)', (url,))
            conn.commit()

    @classmethod
    def delete_video(cls, url: str) -> int:
        """Удаляет URL видео из базы данных и возвращает количество удаленных записей"""
        with sqlite3.connect(cls.DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM videos WHERE url=?', (url,))
            conn.commit()
            return cursor.rowcount

# Инициализация базы данных при запуске
DatabaseManager.init_db()


async def download_video(url: str, output_path: str = "downloads") -> str:
    """Скачивает видео с TikTok по URL"""
    Path(output_path).mkdir(exist_ok=True)
    
    ydl_opts = {
        'format': 'best',
        'outtmpl': f'{output_path}/%(id)s.%(ext)s',
        'quiet': False,
        'no_warnings': False,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_file = ydl.prepare_filename(info)
            # Проверяем, что файл действительно существует перед возвратом
            if os.path.exists(video_file):
                return video_file
            else:
                logger.error(f"Файл не найден после скачивания: {video_file}")
                return None
    except Exception as e:
        logger.error(f"Ошибка при скачивании видео: {e}")
        return None


async def get_random_tiktok_url(api):
    """Получает URL случайного видео из трендов TikTok, используя правильный API."""
    try:
        logger.info("Получение списка трендовых видео из TikTok...")
        
        # Получаем все опубликованные URL
        posted_urls = DatabaseManager.get_all_posted_urls()
        logger.info(f"Найдено {len(posted_urls)} опубликованных видео в базе данных")
        
        
        # Получаем список трендовых видео (уменьшаем количество до 20 для избежания блокировки API)
        trending_videos = [video async for video in api.trending.videos(count=20)]

        if not trending_videos:
            logger.error("Не удалось получить список трендовых видео, список пуст.")
            return None

        # Создаем список потенциальных видео
        potential_videos = [f"https://www.tiktok.com/@{video.author.username}/video/{video.id}" for video in trending_videos]
        
        # Отфильтровываем уже опубликованные видео
        new_videos = [url for url in potential_videos if url not in posted_urls]
        
        if new_videos:
            # Выбираем одно случайное видео из новых
            selected_video = random.choice(new_videos)
            logger.info(f"Выбрано случайное видео: {selected_video}")
            return selected_video
        else:
            logger.warning("Не найдено новых видео для публикации")
            return None

    except Exception as e:
        # Логируем ошибку, чтобы понять, что пошло не так
        logger.error(f"Критическая ошибка при работе с TikTokApi: {e}", exc_info=True)
        return None


async def post_random_video(api):
    """Публикует случайное видео из TikTok"""
    try:
        logger.info("Начало выполнения задачи post_random_video")
        # Получаем URL случайного видео
        video_url = await get_random_tiktok_url(api)
        if not video_url:
            logger.warning("Не удалось получить URL случайного видео")
            return

        logger.info(f"Получен URL видео: {video_url}")
        
        # Скачиваем видео
        video_path = await download_video(video_url)
        if not video_path:
            logger.error("Не удалось скачать видео по URL")
            return

        logger.info(f"Видео скачано: {video_path}")
        
        # Отправляем видео в канал
        try:
            await bot.send_video(
                chat_id=CHANNEL_ID,
                video=FSInputFile(video_path)
            )
            logger.info(f"✓ Случайное видео опубликовано из: {video_url}")
            
            # Добавляем URL видео в базу данных после успешной отправки
            DatabaseManager.add_posted_video(video_url)
            logger.info(f"Видео {video_url} добавлено в базу данных.")
            
        except Exception as e:
            logger.error(f"Ошибка при отправке видео в канал: {e}")
            # Удаляем файл даже если отправка не удалась
            try:
                os.remove(video_path)
                logger.info(f"Файл {video_path} удален после ошибки отправки")
            except OSError as remove_error:
                logger.error(f"Ошибка при удалении файла: {remove_error}")
            return

        # Удаляем локальный файл после успешной отправки
        try:
            os.remove(video_path)
            logger.info(f"Файл {video_path} удален после публикации")
        except OSError as e:
            logger.error(f"Ошибка при удалении файла: {e}")

    except Exception as e:
        logger.error(f"Ошибка в функции post_random_video: {e}")
    finally:
        logger.info("Завершение выполнения задачи post_random_video")


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет доступа к этому боту")
        return

    keyboard = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="/add_post"), types.KeyboardButton(text="/list_posts")],
            [types.KeyboardButton(text="/delete_post")]
        ],
        resize_keyboard=True
    )
    
    await message.answer(
        "🤖 Привет! Я помогу тебе публиковать видео с TikTok в канал.\n\n"
        "📋 Команды:\n"
        "/add_post - добавить видео\n"
        "/delete_post - удалить пост\n"
        "/list_posts - список опубликованных видео\n"
        "/help - справка",
        reply_markup=keyboard
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет доступа к этому боту")
        return

    await message.answer(
        "🤖 Справка по боту:\n\n"
        "📋 Доступные команды:\n"
        "/start - начать работу с ботом\n"
        "/add_post - добавить видео\n"
        "/delete_post - удалить пост\n"
        "/list_posts - список опубликованных видео\n"
        "/help - справка\n"
        "Бот автоматически публикует трендовые видео с TikTok в канал."
    )


class AddPostState(StatesGroup):
    waiting_for_url = State()


class DeletePostState(StatesGroup):
    waiting_for_url = State()


@dp.message(Command("add_post"))
async def cmd_add_post(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет доступа к этой команде")
        return

    await state.set_state(AddPostState.waiting_for_url)
    await message.answer("Введите URL видео TikTok для добавления в очередь или /cancel:")
    

@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("❌ Нечего отменять")
        return

    await state.clear()
    await message.answer("❌ Операция отменена")


@dp.message(AddPostState.waiting_for_url)
async def process_add_post_url(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет доступа к этой команде")
        return

    url = message.text.strip()
    if url == "/cancel":
        await state.clear()
        await message.answer("❌ Операция отменена")
        return

    # Проверяем, что URL - это TikTok URL
    if "tiktok.com" not in url.lower():
        await message.answer("❌ Пожалуйста, введите корректный URL видео TikTok или /cancel:")
        return

    # Добавляем URL в базу данных
    DatabaseManager.add_posted_video(url)
    await state.clear()
    await message.answer(f"✅ Видео добавлено в список опубликованных:\n{url}")


@dp.message(Command("delete_post"))
async def cmd_delete_post(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет доступа к этой команде")
        return

    await state.set_state(DeletePostState.waiting_for_url)
    await message.answer("Отправь URL поста для удаления или /cancel:")
    

@dp.message(DeletePostState.waiting_for_url)
async def process_delete_post_url(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет доступа к этой команде")
        return

    url = message.text.strip()
    if url == "/cancel":
        await state.clear()
        await message.answer("❌ Операция отменена")
        return

    # Удаляем URL из базы данных
    deleted_count = DatabaseManager.delete_video(url)

    await state.clear()
    if deleted_count > 0:
        await message.answer(f"✅ Видео удалено из списка опубликованных:\n{url}")
    else:
        await message.answer(f"❌ Видео не найдено в списке опубликованных:\n{url}")


@dp.message(Command("list_posts"))
async def cmd_list_posts(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет доступа к этой команде")
        return

    urls = DatabaseManager.get_all_posted_urls()
    if urls:
        # Разбиваем список на части по 10 элементов для удобства отображения
        url_list = list(urls)
        chunks = [url_list[i:i+10] for i in range(0, len(url_list), 10)]
        
        for chunk in chunks:
            response = "📋 Список опубликованных видео:\n\n" + "\n".join(chunk)
            await message.answer(response)
    else:
        await message.answer("📭 Нет опубликованных видео")


async def save_session_state(api, session_file="tiktok_session.json", session_index=0):
    """Сохраняет состояние сессии TikTok в файл"""
    try:
        # В новой версии TikTokApi сессии доступны через sessions, а не playwright_sessions
        if hasattr(api, 'sessions') and api.sessions and len(api.sessions) > session_index:
            # Получаем playwright-контекст для сохранения состояния
            session = api.sessions[session_index]
            if hasattr(session, 'context'):
                storage_state = await session.context.storage_state()
                with open(session_file, 'w') as f:
                    json.dump(storage_state, f)
                logger.info(f"Состояние сессии TikTok успешно сохранено в {session_file}")
                return True
            else:
                logger.warning("Контекст сессии недоступен для сохранения")
        elif hasattr(api, 'playwright_sessions') and api.playwright_sessions and len(api.playwright_sessions) > session_index:
            # Поддержка старой версии API на всякий случай
            session = api.playwright_sessions[session_index]
            if hasattr(session, 'context'):
                storage_state = await session.context.storage_state()
                with open(session_file, 'w') as f:
                    json.dump(storage_state, f)
                logger.info(f"Состояние сессии TikTok успешно сохранено в {session_file}")
                return True
        else:
            logger.warning("Нет доступных сессий для сохранения состояния")
    except Exception as e:
        logger.error(f"Ошибка при сохранении состояния сессии: {e}")
    return False


async def main():
    logger.info("🤖 Запуск бота...")
    session_file = "tiktok_session.json"
    
    # Определяем режим работы в зависимости от окружения
    # Для Render.com и других серверов всегда используем headless режим
    is_production = os.getenv("RENDER", "false").lower() == "true" or os.getenv("PRODUCTION", "false").lower() == "true"
    
    # 1. Используй 'async with' с конструктором БЕЗ аргументов
    async with TikTokApi() as api:
        try:
            # 2. Логика загрузки и определения параметров для create_sessions
            create_sessions_kwargs = {}
            storage_state = None
            if os.path.exists(session_file):
                logger.info("Найден файл сессии, загрузка storage_state...")
                with open(session_file, "r", encoding="utf-8") as f:
                    storage_state = json.load(f)
                
                create_sessions_kwargs = {
                    "headless": True,
                    "num_sessions": 1,
                    "ms_tokens": [os.environ.get("ms_token")] if os.environ.get("ms_token") else None,
                    "timeout": 60000,  # Увеличиваем таймаут до 60 секунд
                    "playwright_launch_kwargs": {  # Добавляем аргументы для обхода детекции ботов
                        "args": [
                            "--no-sandbox",
                            "--disable-blink-features=AutomationControlled"
                        ]
                    }
                }
            else:
                # В production всегда используем headless режим, даже при отсутствии сессии
                # Для локальной разработки пользователь может установить переменную окружения FORCE_HEADED=true
                force_headed = os.getenv("FORCE_HEADED", "false").lower() == "true"
                headless_mode = False if force_headed and not is_production else True
                
                logger.info(f"Файл сессии не найден. Запуск в {'headless' if headless_mode else 'headed'} режиме для входа.")
                
                create_sessions_kwargs = {
                    "headless": True,  # Всегда используем headless режим для Render
                    "timeout": 60000,  # Увеличиваем таймаут до 60 секунд
                    "ms_tokens": [os.environ.get("ms_token")] if os.environ.get("ms_token") else None,
                    "executable_path": None,  # Позволяем использовать стандартный путь к браузеру
                    "playwright_launch_kwargs": {  # Добавляем аргументы для обхода детекции ботов
                        "args": [
                            "--no-sandbox",
                            "--disable-blink-features=AutomationControlled"
                        ]
                    }
                }

            # 3. Вызов create_sessions с правильными kwargs в цикле с 3 попытками
            max_attempts = 3
            for attempt in range(max_attempts):
                try:
                    await api.create_sessions(**create_sessions_kwargs)
                    break  # Выходим из цикла, если сессия создана успешно
                except Exception as e:
                    logger.error(f"Ошибка при создании сессии (попытка {attempt + 1}): {e}")
                    if attempt < max_attempts - 1:  # Если это не последняя попытка
                        logger.info("Повторная попытка через 5 секунд...")
                        await asyncio.sleep(5)
                    else:  # Если это была последняя попытка, выбрасываем исключение
                        raise e
            
            # 4. Загрузка сохраненного состояния в сессию, если оно существует
            if storage_state:
                logger.info("Загрузка сохраненного состояния сессии...")
                if hasattr(api, 'sessions') and api.sessions:
                    session = api.sessions[0]
                    if hasattr(session, 'context'):
                        await session.context.clear_cookies()
                        await session.context.add_cookies(storage_state.get('cookies', []))
                        logger.info("Состояние сессии успешно загружено")
                elif hasattr(api, 'playwright_sessions') and api.playwright_sessions:
                    session = api.playwright_sessions[0]
                    if hasattr(session, 'context'):
                        await session.context.clear_cookies()
                        await session.context.add_cookies(storage_state.get('cookies', []))
                        logger.info("Состояние сессии успешно загружено (старый метод)")

            # Сохраняем сессию сразу после создания
            try:
                if hasattr(api, 'sessions') and api.sessions:
                    # Получаем storage_state из первого контекста сессии
                    session = api.sessions[0]
                    if hasattr(session, 'context'):
                        storage_state = await session.context.storage_state()

                        logger.info("Сессия успешно создана. Немедленное сохранение storage_state...")
                        with open(session_file, "w", encoding="utf-8") as f:
                            json.dump(storage_state, f, indent=4)
                        logger.info(f"Storage state сессии успешно сохранен в {session_file}")
                elif hasattr(api, 'playwright_sessions') and api.playwright_sessions:
                    # Поддержка старого метода на всякий случай
                    session = api.playwright_sessions[0]
                    if hasattr(session, 'context'):
                        storage_state = await session.context.storage_state()

                        logger.info("Сессия успешно создана. Немедленное сохранение storage_state...")
                        with open(session_file, "w", encoding="utf-8") as f:
                            json.dump(storage_state, f, indent=4)
                        logger.info(f"Storage state сессии успешно сохранен в {session_file}")
            except Exception as e:
                logger.error(f"Ошибка при первоначальном сохранении storage state сессии: {e}")

            # 4. Основная логика бота (планировщик, aiogram)
            global scheduler
            scheduler = AsyncIOScheduler()
            
            # Добавляем задачу с правильной передачей аргументов
            scheduler.add_job(
                post_random_video,
                'interval',
                minutes=POSTING_INTERVAL_MINUTES,
                args=[api],
                id='post_random_video_job',
                max_instances=1,  # Ограничиваем количество одновременных выполнений
                misfire_grace_time=30 # Время для выполнения просроченных задач
            )
            scheduler.start()
            logger.info("✅ Бот готов!")

            # Запускаем поллинг с корректной остановкой планировщика
            try:
                await dp.start_polling(bot)
            finally:
                # Останавливаем планировщик при завершении
                if scheduler.running:
                    scheduler.shutdown()
                    logger.info("Планировщик остановлен")

        except (KeyboardInterrupt, SystemExit):
            logger.info("Получено прерывание с клавиатуры (Ctrl+C).")
             
        finally:
            # 5. Логика сохранения сессии (новая логика с использованием storage_state)
            logger.info("Завершение работы бота...")
            try:
                if hasattr(api, 'sessions') and api.sessions:
                    # Получаем storage_state из первого контекста сессии
                    session = api.sessions[0]
                    if hasattr(session, 'context'):
                        storage_state = await session.context.storage_state()

                        logger.info("Обнаружен storage state сессии. Попытка сохранения...")
                        with open(session_file, "w", encoding="utf-8") as f:
                            json.dump(storage_state, f, indent=4)
                        logger.info(f"Storage state сессии успешно сохранен в {session_file}")
                elif hasattr(api, 'playwright_sessions') and api.playwright_sessions:
                    # Поддержка старого метода на всякий случай
                    session = api.playwright_sessions[0]
                    if hasattr(session, 'context'):
                        storage_state = await session.context.storage_state()

                        logger.info("Обнаружен storage state сессии. Попытка сохранения...")
                        with open(session_file, "w", encoding="utf-8") as f:
                            json.dump(storage_state, f, indent=4)
                        logger.info(f"Storage state сессии успешно сохранен в {session_file}")
                else:
                    logger.warning("Сессии для сохранения не найдены. Файл не будет создан.")
            except Exception as e:
                logger.error(f"Ошибка при получении или сохранения storage state сессии: {e}")

            # Останавливаем планировщик при завершении
            if 'scheduler' in globals() and scheduler.running:
                scheduler.shutdown()
                logger.info("Планировщик остановлен")
            
            logger.info("Бот остановлен.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Получено прерывание с клавиатуры (Ctrl+C).")
