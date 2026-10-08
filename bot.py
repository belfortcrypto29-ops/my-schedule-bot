import asyncio
from datetime import datetime, timedelta
import logging
import sqlite3
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

TOKEN = "8900420770:AAHN20qf_1LPISGfnuu7O2Zq9bVcvc1HYsg"
TIMEZONE = pytz.timezone("Europe/Moscow")

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler(timezone=TIMEZONE)

DAYS_OF_WEEK = {
    0: "Понедельник",
    1: "Вторник",
    2: "Среда",
    3: "Четверг",
    4: "Пятница",
    5: "Суббота",
    6: "Воскресенье",
}

# --- БАЗА ДАННЫХ И АВТОЗАПОЛНЕНИЕ ---
def init_db():
    conn = sqlite3.connect("schedule.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day_of_week INTEGER,
            start_time TEXT,
            end_time TEXT,
            subject TEXT,
            location TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS homework (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT,
            due_date TEXT,
            task_text TEXT
        )
    """)
    
    cursor.execute("SELECT COUNT(*) FROM schedule")
    if cursor.fetchone()[0] == 0:
        default_schedule = [
            # Понедельник (0)
            (0, "10:10", "11:50", "Comprehensive Chinese (1) (Intl)", "Reading Bldg S206"),
            (0, "13:45", "15:25", "Physical Education (1)", "Gym North Foyer"),
            
            # Вторник (1)
            (1, "18:45", "20:25", "Advanced Mathematics (1) (Intl)", "Mingde N203"),
            (1, "20:35", "21:20", "Advanced Mathematics (1) (Intl)", "Mingde N203"),
            
            # Среда (2)
            (2, "10:10", "11:50", "Comprehensive Chinese (1) (Intl)", "Reading Bldg S206"),
            (2, "15:55", "17:35", "Introduction to Computer Science", "Mingde N207"),
            (2, "18:45", "20:25", "Orientation Education (Intl)", "Mingde N311"),
            
            # Четверг (3) — первый урок убран
            (3, "10:10", "11:50", "Advanced Mathematics (1) (Intl)", "Wende N307"),
            
            # Пятница (4) — последний урок убран
            (4, "08:00", "09:40", "Comprehensive Chinese (1) (Intl)", "Reading Bldg S114"),
            (4, "10:10", "11:50", "Chinese Listening & Speaking (1)", "Wende S205"),
            (4, "13:45", "15:25", "Chinese Reading & Writing (1)", "Reading Bldg S114"),
            (4, "15:55", "17:35", "Chinese Reading & Writing (1)", "Reading Bldg S114"),
        ]
        cursor.executemany("""
            INSERT INTO schedule (day_of_week, start_time, end_time, subject, location)
            VALUES (?, ?, ?, ?, ?)
        """, default_schedule)
        conn.commit()
        
    conn.close()

init_db()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_schedule_for_day(day_index):
    conn = sqlite3.connect("schedule.db")
    cursor = conn.cursor()
    cursor.execute("SELECT start_time, end_time, subject, location FROM schedule WHERE day_of_week = ? ORDER BY start_time", (day_index,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_homework_for_date(date_str):
    conn = sqlite3.connect("schedule.db")
    cursor = conn.cursor()
    cursor.execute("SELECT subject, task_text FROM homework WHERE due_date = ?", (date_str,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def find_next_subject(subject_name):
    now = datetime.now(TIMEZONE)
    current_day = now.weekday()
    current_time = now.strftime("%H:%M")
    
    conn = sqlite3.connect("schedule.db")
    cursor = conn.cursor()
    
    for i in range(14):
        check_day = (current_day + i) % 7
        cursor.execute("SELECT start_time, end_time, location FROM schedule WHERE day_of_week = ? AND subject LIKE ? ORDER BY start_time", (check_day, f"%{subject_name}%"))
        lessons = cursor.fetchall()
        
        for start, end, loc in lessons:
            if i == 0 and start <= current_time:
                continue
            
            target_date = now + timedelta(days=i)
            day_name = DAYS_OF_WEEK[check_day]
            if i == 0:
                day_str = "сегодня"
            elif i == 1:
                day_str = "завтра"
            else:
                day_str = f"в {day_name.lower()} ({target_date.strftime('%d.%m')})"
                
            conn.close()
            return f"📖 **{subject_name}** будет {day_str} в **{start}**\n📍 Аудитория/Ссылка: {loc}"
            
    conn.close()
    return f"❌ Предмет «{subject_name}» не найден в расписании."

# --- КЛАВИАТУРЫ ---
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="📅 На сегодня")
    builder.button(text="🟢 Что сейчас?")
    builder.button(text="➡️ Следующая пара")
    builder.button(text="📆 Расписание на неделю")
    builder.button(text="🔍 Найти предмет")
    builder.adjust(2, 2, 1)
    return builder.as_markup(resize_keyboard=True)

def get_days_keyboard():
    builder = InlineKeyboardBuilder()
    for day_idx, day_name in DAYS_OF_WEEK.items():
        builder.button(text=day_name, callback_data=f"day_{day_idx}")
    builder.adjust(2)
    return builder.as_markup()

# --- ОБРАБОТЧИКИ СОБЫТИЙ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я бот-помощник по расписанию.\n"
        "Выбирай нужные действия с помощью кнопок внизу 👇",
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text == "📅 На сегодня")
async def btn_today(message: types.Message):
    now = datetime.now(TIMEZONE)
    day_idx = now.weekday()
    lessons = get_schedule_for_day(day_idx)
    
    if not lessons:
        await message.answer("🎉 На сегодня пар нет!", reply_markup=get_main_keyboard())
        return

    today_str = now.strftime("%Y-%m-%d")
    hw = get_homework_for_date(today_str)

    text = f"📚 **Расписание на сегодня ({DAYS_OF_WEEK[day_idx]}):**\n\n"
    for start, end, subject, loc in lessons:
        text += f"⏰ `{start} - {end}` | **{subject}**\n📍 *{loc}*\n\n"

    if hw:
        text += "📝 **Домашнее задание:**\n"
        for subj, task in hw:
            text += f"• **{subj}:** {task}\n"

    await message.answer(text, parse_mode="MARKDOWN", reply_markup=get_main_keyboard())

@dp.message(F.text == "🟢 Что сейчас?")
async def btn_now(message: types.Message):
    now = datetime.now(TIMEZONE)
    current_time_str = now.strftime("%H:%M")
    lessons = get_schedule_for_day(now.weekday())

    current_lesson = None
    next_lesson = None

    for i, (start, end, subject, loc) in enumerate(lessons):
        if start <= current_time_str <= end:
            current_lesson = (start, end, subject, loc)
            if i + 1 < len(lessons):
                next_lesson = lessons[i + 1]
            break
        elif current_time_str < start:
            next_lesson = (start, end, subject, loc)
            break

    if current_lesson:
        start, end, subject, loc = current_lesson
        text = f"🟢 **Сейчас идет пара:**\n⏰ {start} - {end}\n📖 **{subject}**\n📍 {loc}\n"
        if next_lesson:
            text += f"\n➡️ *Следующая:* {next_lesson[0]} — {next_lesson[2]}"
        await message.answer(text, parse_mode="MARKDOWN", reply_markup=get_main_keyboard())
    elif next_lesson:
        start, end, subject, loc = next_lesson
        await message.answer(f"⏳ Сейчас пары нет.\n\nСледующая пара начнется в **{start}**:\n📖 **{subject}** ({loc})", parse_mode="MARKDOWN", reply_markup=get_main_keyboard())
    else:
        await message.answer("🌴 На сегодня все пары уже закончились!", reply_markup=get_main_keyboard())

@dp.message(F.text == "➡️ Следующая пара")
async def btn_next(message: types.Message):
    now = datetime.now(TIMEZONE)
    current_time_str = now.strftime("%H:%M")
    lessons = get_schedule_for_day(now.weekday())

    next_lesson = None
    for start, end, subject, loc in lessons:
        if start > current_time_str:
            next_lesson = (start, end, subject, loc)
            break

    if next_lesson:
        start, end, subject, loc = next_lesson
        await message.answer(f"➡️ **Следующая пара:**\n⏰ {start} - {end}\n📖 **{subject}**\n📍 {loc}", parse_mode="MARKDOWN", reply_markup=get_main_keyboard())
    else:
        await message.answer("📭 Больше пар на сегодня не предвидится.", reply_markup=get_main_keyboard())

@dp.message(F.text == "📆 Расписание на неделю")
async def btn_week(message: types.Message):
    await message.answer("👇 Выбери день недели:", reply_markup=get_days_keyboard())

@dp.message(F.text == "🔍 Найти предмет")
async def btn_search_prompt(message: types.Message):
    await message.answer("Напиши название предмета (или его часть), и я скажу, когда он будет следующий раз (например: `Math` или `Chinese`).", parse_mode="MARKDOWN")

@dp.message(F.text & ~F.text.in_({"📅 На сегодня", "🟢 Что сейчас?", "➡️ Следующая пара", "📆 Расписание на неделю", "🔍 Найти предмет"}))
async def handle_text_search(message: types.Message):
    subject_query = message.text.strip()
    result = find_next_subject(subject_query)
    await message.answer(result, parse_mode="MARKDOWN", reply_markup=get_main_keyboard())

@dp.callback_query(F.data.startswith("day_"))
async def process_day_callback(callback: types.CallbackQuery):
    day_idx = int(callback.data.split("_")[1])
    lessons = get_schedule_for_day(day_idx)
    day_name = DAYS_OF_WEEK[day_idx]

    if not lessons:
        await callback.message.edit_text(f"🎉 На **{day_name}** пар нет!", parse_mode="MARKDOWN")
        await callback.answer()
        return

    text = f"📚 **Расписание на {day_name}:**\n\n"
    for start, end, subject, loc in lessons:
        text += f"⏰ `{start} - {end}` | **{subject}**\n📍 *{loc}*\n\n"

    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад к дням", callback_data="back_to_days")

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="MARKDOWN")
    await callback.answer()

@dp.callback_query(F.data == "back_to_days")
async def process_back_callback(callback: types.CallbackQuery):
    await callback.message.edit_text("👇 Выбери день недели:", reply_markup=get_days_keyboard())
    await callback.answer()

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())