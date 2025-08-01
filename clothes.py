import asyncio
import os
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import sqlite3
from datetime import datetime
import os

# === НАСТРОЙКИ ===
BOT_TOKEN = os.getenv("API_TOKEN")  # Заменить на свой токен
ADMIN_IDS = [1453081434]  # Заменить на свои ID
PAYMENT_DETAILS = (
    "💳 Реквизиты для вклада:\n"
    "Принимаю ТОЛЬКО Т-БАНК!!!\n"
    "Карта: 2200 7010 4325 8000\n"
    "Телефон: +79219753645\n"
    "💬 Комментарий: Вклад в поставку"
)

# === ПАПКИ ===
os.makedirs("photos", exist_ok=True)
DB_NAME = "supplies.db"

# === БАЗА ДАННЫХ ===
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    # === Поставки ===
    cur.execute("""
        CREATE TABLE IF NOT EXISTS supplies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            status TEXT DEFAULT 'active'
        )
    """)

    # === Товары ===
    cur.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supply_id INTEGER,
            title TEXT,
            price REAL,
            sell_price REAL,
            description TEXT,
            photo TEXT,
            is_sold INTEGER DEFAULT 0,
            FOREIGN KEY(supply_id) REFERENCES supplies(id)
        )
    """)

    # === Вклады ===
    cur.execute("""
        CREATE TABLE IF NOT EXISTS contributions (
            user_id INTEGER,
            supply_id INTEGER,
            amount REAL,
            username TEXT,
            PRIMARY KEY (user_id, supply_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS contribution_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            bank TEXT,
            payment_info TEXT,
            status TEXT DEFAULT 'pending'  -- pending, approved, rejected
        )
    """)

    # === ДОБАВЛЯЕМ СТОЛБЕЦ status, ЕСЛИ ЕГО НЕТ ===
    cur.execute("PRAGMA table_info(items)")
    columns = [col[1] for col in cur.fetchall()]
    if 'status' not in columns:
        cur.execute("ALTER TABLE items ADD COLUMN status TEXT DEFAULT 'Куплен'")

    # === Создаём тестовую поставку, если нет ===
    cur.execute("SELECT COUNT(*) FROM supplies")
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO supplies (name, status) VALUES ('Поставка #1', 'active')")

    conn.commit()
    conn.close()

init_db()

# === FSM для добавления товара ===
# === FSM для добавления товара ===
class AddItem(StatesGroup):
    waiting_title = State()
    waiting_price = State()
    waiting_sell_price = State()
    waiting_description = State()
    waiting_photo = State()

# === FSM для добавления вклада ===
class AddContribution(StatesGroup):
    waiting_username = State()
    waiting_amount = State()

class EditItem(StatesGroup):
    waiting_new_title = State()
    waiting_new_price = State()
    waiting_new_sell_price = State()
    waiting_new_description = State()
    waiting_new_photo = State()

class MakeContribution(StatesGroup):
    waiting_bank = State()
    waiting_payment_info = State()
    waiting_confirm = State()
# === БОТ ===
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# === КЛАВИАТУРЫ ===
def get_main_menu(user_id):
    buttons = [
        [InlineKeyboardButton(text="1. Мой вклад", callback_data="my_contributions")],
        [InlineKeyboardButton(text="2. Посмотреть поставку", callback_data="view_supply")],
        [InlineKeyboardButton(text="3. Сделать вклад", callback_data="make_contribution")]
    ]
    if user_id in ADMIN_IDS:
        buttons.append([InlineKeyboardButton(text="4. Админская панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_supply_list_keyboard(supply_type):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    if supply_type == "current":
        cur.execute("SELECT id, name FROM supplies WHERE status = 'active'")
    else:
        cur.execute("SELECT id, name FROM supplies WHERE status = 'completed'")
    supplies = cur.fetchall()
    conn.close()

    buttons = []
    for s in supplies:
        buttons.append([InlineKeyboardButton(text=s[1], callback_data=f"supply_{s[0]}_{supply_type}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_item_list_keyboard(supply_id, for_admin=False):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id, title, price, is_sold FROM items WHERE supply_id = ?", (supply_id,))
    items = cur.fetchall()
    conn.close()

    buttons = []
    for item in items:
        item_id, title, price, is_sold = item
        status = "✅" if is_sold else "🔄"
        text = f"{title} — {price}₽ {status}"
        callback = f"admin_item_{item_id}" if for_admin else f"user_item_{item_id}"
        buttons.append([InlineKeyboardButton(text=text, callback_data=callback)])

    # Кнопка "Назад"
    back_callback = "admin_view_supply" if for_admin else "view_supply"
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback)])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_panel():
    buttons = [
        [InlineKeyboardButton(text="📋 Посмотреть вклады людей", callback_data="admin_view_contributions")],
        [InlineKeyboardButton(text="📬 Заявки на вклады", callback_data="admin_view_requests")],  # ← НОВАЯ КНОПКА
        [InlineKeyboardButton(text="➕ Добавить вклад", callback_data="admin_add_contribution")],
        [InlineKeyboardButton(text="📦 Заполнить поставку", callback_data="admin_add_item")],
        [InlineKeyboardButton(text="🔍 Управлять поставкой", callback_data="admin_view_supply")],
        [InlineKeyboardButton(text="🆕 Создать поставку", callback_data="admin_create_supply")],
        [InlineKeyboardButton(text="🗑 Удалить поставку", callback_data="admin_delete_supply")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.callback_query(F.data == "admin_view_requests")
async def admin_view_requests(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id, user_id, username, bank, payment_info FROM contribution_requests WHERE status = 'pending'")
    requests = cur.fetchall()
    conn.close()

    if not requests:
        await call.answer("Нет новых заявок.", show_alert=True)
        return

    for req in requests:
        req_id, user_id, username, bank, info = req
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"approve_req_{req_id}")],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_req_{req_id}")]
        ])
        await call.message.answer(
            f"📬 Заявка #{req_id}\n"
            f"👤 Пользователь: @{username or user_id}\n"
            f"🏦 Банк: {bank}\n"
            f"📱/💳: <code>{info}</code>",
            reply_markup=markup,
            parse_mode="HTML"
        )

@dp.callback_query(F.data.startswith("approve_req_"))
async def approve_contribution_request(call: CallbackQuery, state: FSMContext):
    req_id = int(call.data.split("_")[2])

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT user_id, bank, payment_info FROM contribution_requests WHERE id = ?", (req_id,))
    row = cur.fetchone()
    if not row:
        await call.answer("Заявка не найдена.")
        return

    user_id, bank, info = row

    # Спрашиваем сумму
    await state.update_data(req_id=req_id, temp_user_id=user_id)
    await state.set_state(MakeContribution.waiting_bank)  # Переиспользуем состояние
    await call.message.edit_text(f"Сколько внес пользователь (в рублях)?")

@dp.message(MakeContribution.waiting_bank)
async def admin_enter_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        if amount <= 0: raise ValueError
    except:
        await message.answer("Введите число!")
        return

    data = await state.get_data()
    req_id = data["req_id"]
    user_id = data["temp_user_id"]

    # Получаем активную поставку
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id FROM supplies WHERE status = 'active' LIMIT 1")
    supply_row = cur.fetchone()
    if not supply_row:
        await message.answer("❌ Нет активной поставки.")
        await state.clear()
        return

    supply_id = supply_row[0]

    # Проверяем, есть ли уже вклад
    cur.execute("SELECT amount FROM contributions WHERE user_id = ? AND supply_id = ?", (user_id, supply_id))
    existing = cur.fetchone()

    if existing:
        new_amount = existing[0] + amount
        cur.execute("UPDATE contributions SET amount = ? WHERE user_id = ? AND supply_id = ?",
                    (new_amount, user_id, supply_id))
    else:
        cur.execute("INSERT INTO contributions (user_id, supply_id, amount) VALUES (?, ?, ?)",
                    (user_id, supply_id, amount))

    # Обновляем статус заявки
    cur.execute("UPDATE contribution_requests SET status = 'approved' WHERE id = ?", (req_id,))
    conn.commit()
    conn.close()

    # Уведомляем пользователя
    try:
        await bot.send_message(
            user_id,
            f"✅ Ваш вклад на {amount}₽ подтверждён!\n"
            f"Он добавлен в поставку #{supply_id}."
        )
    except:
        pass

    await message.answer("✅ Вклад подтверждён и добавлен.")
    await state.clear()
    await cmd_start(message)  # ❌ ОШИБКА ЗДЕСЬ

# === ОСНОВНЫЕ ОБРАБОТЧИКИ ===

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username  # Может быть None

    await state.clear()

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM contributions WHERE user_id = ? LIMIT 1", (user_id,))
    if not cur.fetchone():
        cur.execute("INSERT INTO contributions (user_id, username, amount) VALUES (?, ?, 0)",
                    (user_id, username))
    else:
        cur.execute("UPDATE contributions SET username = ? WHERE user_id = ?", (username, user_id))
    conn.commit()
    conn.close()

    await message.answer("👋 Добро пожаловать! Выберите действие:", reply_markup=get_main_menu(user_id))


@dp.callback_query(F.data.startswith("user_item_"))
async def user_show_item_details(call: CallbackQuery):
    item_id = int(call.data.split("_")[2])

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT title, price, sell_price, description, photo, is_sold, supply_id, status
        FROM items WHERE id = ?
    """, (item_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        await call.answer("Товар не найден.")
        return

    title, price, sell_price, desc, photo_path, is_sold_db, supply_id, status = row

    # === РАСЧЁТ СРОКОВ ===
    arrival_text = "🚚 Приедет примерно через: <b>20–30 дней</b>"

    # Срок продажи
    if sell_price < 5000:
        sale_time = "⏱ Продажа: <b>Меньше недели</b>"
    elif 5000 <= sell_price < 10000:
        sale_time = "⏱ Продажа: <b>5–10 дней</b>"
    elif 10000 <= sell_price < 15000:
        sale_time = "⏱ Продажа: <b>10–20 дней</b>"
    else:
        sale_time = "⏱ Продажа: <b>3 недели – 2 месяца</b>"

    # Получение денег = после продажи + 1-2 дня на обработку
    money_time = "💰 Деньги: <b>Через неделю после продажи (пока авито доставит покупателю)</b>"

    # Описание
    text = (
        f"📦 <b>{title}</b>\n\n"
        f"💰 Закупка: <b>{price}₽</b>\n"
        f"🎯 Продажа: <b>{sell_price}₽</b>\n"
        f"🏷 Статус: <b>{status}</b>\n\n"
        f"{arrival_text}\n"
        f"{sale_time}\n"
        f"{money_time}\n\n"
        f"📝 Описание:\n{desc or 'Нет описания'}"
    )

    # Кнопка "Назад"
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"supply_user_{supply_id}")]
    ])

    if photo_path and os.path.exists(photo_path):
        try:
            await call.message.delete()
        except:
            pass
        await bot.send_photo(
            chat_id=call.message.chat.id,
            photo=FSInputFile(photo_path),
            caption=text,
            reply_markup=markup,
            parse_mode="HTML"
        )
    else:
        try:
            await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        except:
            await call.message.answer(text, reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data == "admin_create_supply")
async def admin_create_supply(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Доступ запрещён.", show_alert=True)
        return

    # Имя поставки: "Поставка от 01.09.2024"
    name = f"Поставка от {datetime.now().strftime('%d.%m.%Y')}"

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("INSERT INTO supplies (name, status) VALUES (?, 'active')", (name,))
    conn.commit()
    conn.close()

    await call.answer(f"✅ Поставка '{name}' создана!", show_alert=True)
    await admin_panel(call)

@dp.callback_query(F.data == "admin_delete_supply")
async def admin_delete_supply_start(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Доступ запрещён.", show_alert=True)
        return

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM supplies WHERE status = 'active'")
    supplies = cur.fetchall()
    conn.close()

    if not supplies:
        await call.answer("Нет активных поставок.", show_alert=True)
        return

    buttons = []
    for s in supplies:
        buttons.append([InlineKeyboardButton(text=s[1], callback_data=f"confirm_delete_supply_{s[0]}")])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="admin_panel")])

    await call.message.answer("Выберите поставку для удаления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@dp.callback_query(F.data.startswith("confirm_delete_supply_"))
async def confirm_delete_supply(call: CallbackQuery):
    supply_id = int(call.data.split("_")[3])

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT name FROM supplies WHERE id = ?", (supply_id,))
    name = cur.fetchone()
    conn.close()

    if not name:
        await call.answer("Поставка не найдена.")
        return

    # Спрашиваем: удалить или переместить?
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 В предыдущие", callback_data=f"move_supply_{supply_id}")],
        [InlineKeyboardButton(text="💀 Удалить полностью", callback_data=f"full_delete_supply_{supply_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_panel")]
    ])
    await call.message.edit_text(f"Что сделать с поставкой:\n\n<b>{name[0]}</b>?", reply_markup=markup, parse_mode="HTML")


@dp.callback_query(F.data.startswith("move_supply_"))
async def move_supply_to_completed(call: CallbackQuery):
    supply_id = int(call.data.split("_")[2])

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE supplies SET status = 'completed' WHERE id = ?", (supply_id,))
    conn.commit()
    conn.close()

    await call.answer("✅ Поставка перемещена в 'Предыдущие'.")
    await admin_panel(call)


@dp.callback_query(F.data.startswith("full_delete_supply_"))
async def full_delete_supply(call: CallbackQuery):
    supply_id = int(call.data.split("_")[3])

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    # Удаляем все товары и саму поставку
    cur.execute("DELETE FROM items WHERE supply_id = ?", (supply_id,))
    cur.execute("DELETE FROM supplies WHERE id = ?", (supply_id,))
    conn.commit()
    conn.close()

    await call.answer("✅ Поставка и все товары удалены.")
    await admin_panel(call)

@dp.callback_query(F.data.startswith("admin_item_"))
async def admin_show_item_details(call: CallbackQuery, state: FSMContext):
    item_id = int(call.data.split("_")[2])

    # Сохраняем для удаления/редактирования
    await state.update_data(current_item_id=item_id)

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT title, price, sell_price, description, photo, is_sold, supply_id, status
        FROM items WHERE id = ?
    """, (item_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        await call.answer("Товар не найден.")
        return

    title, price, sell_price, desc, photo_path, is_sold_db, supply_id, status = row
    text = (
        f"📦 <b>{title}</b>\n\n"
        f"💰 Закупка: <b>{price}₽</b>\n"
        f"🎯 Продажа: <b>{sell_price}₽</b>\n"
        f"🏷 Статус: <b>{status}</b>\n"
        f"📦 Продажа: {'✅' if is_sold_db else '🔄'}\n\n"
        f"📝 Описание:\n{desc or 'Нет описания'}"
    )

    # === КНОПКИ ДЛЯ АДМИНА ===
    keyboard = []

    # Кнопка "Продано"
    btn_text = "❌ Убрать продажу" if is_sold_db else "✅ Отметить как проданное"
    keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=f"toggle_sold_{item_id}")])

    # Кнопки "Удалить" и "Изменить"
    keyboard.append([
        InlineKeyboardButton(text="🗑 Удалить", callback_data="admin_delete_item"),
        InlineKeyboardButton(text="✏️ Изменить", callback_data="admin_edit_item")
    ])

    # Кнопка "Назад"
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin_supply_{supply_id}")])

    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

    if photo_path and os.path.exists(photo_path):
        try:
            await call.message.delete()
        except:
            pass
        await bot.send_photo(
            chat_id=call.message.chat.id,
            photo=FSInputFile(photo_path),
            caption=text,
            reply_markup=markup,
            parse_mode="HTML"
        )
    else:
        try:
            await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        except:
            await call.message.answer(text, reply_markup=markup, parse_mode="HTML")
# === 1. Мой вклад ===
@dp.callback_query(F.data == "my_contributions")
async def my_contributions(call: CallbackQuery):
    user_id = call.from_user.id
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT s.name, c.amount, s.status
        FROM contributions c
        JOIN supplies s ON c.supply_id = s.id
        WHERE c.user_id = ?
    """, (user_id,))
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await call.answer("Вы ещё не делали вкладов.", show_alert=True)
        return

    text = "📊 Ваши вклады:\n\n"
    for name, amount, status in rows:
        profit = "—"
        percent = "—"
        if status == "completed":
            profit = round(amount * 1.3, 2)  # Пример прибыли
            percent = "30%"
        text += f"📦 {name}\n💸 Вклад: {amount}₽\n📈 Прибыль: {profit}₽\n📊 Доля: {percent}\n\n"

    await call.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ]))

# === 2. Посмотреть поставку ===
@dp.callback_query(F.data == "view_supply")
async def view_supply(call: CallbackQuery):
    buttons = [
        [InlineKeyboardButton(text="📦 Нынешняя поставка", callback_data="supply_list_current")],
        [InlineKeyboardButton(text="📦 Предыдущие поставки", callback_data="supply_list_completed")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ]
    await call.message.answer("Выберите поставку:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("supply_list_"))
async def show_supply_list(call: CallbackQuery):
    supply_type = call.data.split("_")[2]  # current или completed

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    if supply_type == "current":
        cur.execute("SELECT id, name FROM supplies WHERE status = 'active'")
    else:
        cur.execute("SELECT id, name FROM supplies WHERE status = 'completed'")
    supplies = cur.fetchall()
    conn.close()

    buttons = []
    for s in supplies:
        # Для пользователей: supply_user_1
        buttons.append([InlineKeyboardButton(text=s[1], callback_data=f"supply_user_{s[0]}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="view_supply")])

    await call.message.answer(f"Список {supply_type} поставок:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data == "admin_view_supply")
async def admin_view_supply(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Доступ запрещён.", show_alert=True)
        return

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM supplies WHERE status = 'active'")
    supplies = cur.fetchall()
    conn.close()

    if not supplies:
        await call.answer("Нет активной поставки.", show_alert=True)
        return

    buttons = []
    for s in supplies:
        buttons.append([InlineKeyboardButton(text=s[1], callback_data=f"admin_supply_{s[0]}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")])

    try:
        await call.message.edit_text("📦 Выберите поставку для управления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    except:
        await call.message.answer("📦 Выберите поставку для управления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
@dp.callback_query(F.data.startswith("supply_user_"))
async def user_show_supply_items(call: CallbackQuery):
    supply_id = int(call.data.split("_")[2])

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT name FROM supplies WHERE id = ?", (supply_id,))
    name_row = cur.fetchone()
    conn.close()

    if not name_row:
        await call.answer("Поставка не найдена.")
        return

    # Показываем только список товаров (без админских кнопок)
    await call.message.answer(
        f"📦 Товары в поставке: {name_row[0]}",
        reply_markup=get_item_list_keyboard(supply_id, for_admin=False)
    )

@dp.callback_query(F.data.startswith("admin_supply_"))
async def admin_show_supply_items(call: CallbackQuery):
    supply_id = int(call.data.split("_")[2])

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT name FROM supplies WHERE id = ?", (supply_id,))
    name_row = cur.fetchone()
    conn.close()

    if not name_row:
        await call.answer("Поставка не найдена.")
        return

    # Переподключаемся для получения товаров
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id, title, price, is_sold FROM items WHERE supply_id = ?", (supply_id,))
    items = cur.fetchall()  # ✅ Правильно: cur.fetchall()
    conn.close()

    # Формируем клавиатуру
    buttons = []
    for item in items:
        item_id, title, price, is_sold = item
        status = "✅" if is_sold else "🔄"
        text = f"{title} — {price}₽ {status}"
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"item_{item_id}_admin")])

    # Глобальные действия
    buttons.append([InlineKeyboardButton(text="🗑 Удалить все товары", callback_data=f"delete_all_{supply_id}")])
    buttons.append([InlineKeyboardButton(text="🔁 Изменить статус всех", callback_data=f"bulk_status_{supply_id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_view_supply")])

    markup = InlineKeyboardMarkup(inline_keyboard=buttons)

    await call.message.answer(f"📦 Управление поставкой: {name_row[0]}", reply_markup=markup)
@dp.callback_query(F.data.startswith("delete_all_"))
async def confirm_delete_all(call: CallbackQuery):
    supply_id = int(call.data.split("_")[2])

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить всё", callback_data=f"confirm_delete_all_{supply_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_view_supply")]
    ])
    await call.message.edit_text("Вы уверены, что хотите удалить **все товары** из этой поставки?", reply_markup=markup)

@dp.callback_query(F.data.startswith("confirm_delete_all_"))
async def delete_all_items(call: CallbackQuery):
    supply_id = int(call.data.split("_")[3])

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM items WHERE supply_id = ?", (supply_id,))
    conn.commit()
    conn.close()

    await call.message.edit_text("🗑 Все товары удалены.")
    await admin_view_supply(call)

@dp.callback_query(F.data.startswith("bulk_status_"))
async def bulk_status_prompt(call: CallbackQuery, state: FSMContext):
    supply_id = int(call.data.split("_")[2])
    await state.update_data(bulk_supply_id=supply_id)

    buttons = []
    for status in STATUSES:
        buttons.append([InlineKeyboardButton(text=status, callback_data=f"apply_bulk_status_{status}")])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="admin_view_supply")])
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await call.message.edit_text("Выберите статус для **всех товаров** в поставке:", reply_markup=markup)

@dp.callback_query(F.data.startswith("apply_bulk_status_"))
async def apply_bulk_status(call: CallbackQuery, state: FSMContext):
    status = call.data.replace("apply_bulk_status_", "").replace("_", " ")
    data = await state.get_data()
    supply_id = data["bulk_supply_id"]

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE items SET status = ? WHERE supply_id = ?", (status, supply_id))
    conn.commit()
    conn.close()

    await call.answer(f"✅ Статус всех товаров изменён на: {status}")
    await admin_view_supply(call)

@dp.callback_query(F.data == "admin_add_contribution")
async def admin_add_contribution_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Доступ запрещён.", show_alert=True)
        return
    await state.set_state(AddContribution.waiting_username)
    await call.message.answer(
        "👤 Введите <b>юзернейм</b> пользователя (например, @ivan_123 или ivan_123):",
        parse_mode="HTML"
    )
@dp.callback_query(F.data.startswith("supply_"))
async def show_supply_items(call: CallbackQuery):
    data = call.data.split("_")
    supply_id = int(data[1])
    # Определяем, админ ли вызвал
    is_admin = call.from_user.id in ADMIN_IDS

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT name FROM supplies WHERE id = ?", (supply_id,))
    name_row = cur.fetchone()
    conn.close()

    if not name_row:
        await call.answer("Поставка не найдена.")
        return

    # Отправляем список товаров
    await call.message.answer(
        f"📦 Товары в поставке: {name_row[0]}",
        reply_markup=get_item_list_keyboard(supply_id, for_admin=is_admin)
    )

@dp.callback_query(F.data.startswith("supply_"))
async def show_supply_items(call: CallbackQuery):
    data = call.data.split("_")
    supply_id = int(data[1])
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT name FROM supplies WHERE id = ?", (supply_id,))
    name = cur.fetchone()
    conn.close()
    if not name:
        await call.answer("Поставка не найдена.")
        return
    await call.message.answer(f"📦 Товары в поставке: {name[0]}", reply_markup=get_item_list_keyboard(supply_id))

# === Просмотр товара ===
@dp.callback_query(F.data.startswith("item_"))
async def show_item_details(call: CallbackQuery, state: FSMContext):
    data = call.data.split("_")
    item_id = int(data[1])
    is_admin = len(data) > 2 and data[2] == "admin"

    # Сохраняем item_id для последующих действий (удаление/изменение)
    if is_admin:
        await state.update_data(current_item_id=item_id)

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT title, price, sell_price, description, photo, is_sold, supply_id, status
        FROM items WHERE id = ?
    """, (item_id,))
    row = cur.fetchone()
    if not row:
        await call.answer("Товар не найден.")
        return
    title, price, sell_price, desc, photo_path, is_sold_db, supply_id, status = row
    text = (
        f"📦 <b>{title}</b>\n\n"
        f"💰 Закупка: <b>{price}₽</b>\n"
        f"🎯 Продажа: <b>{sell_price}₽</b>\n"
        f"🏷 Статус: <b>{status}</b>\n"
        f"📦 Продажа: {'✅' if is_sold_db else '🔄'}\n\n"
        f"📝 Описание:\n{desc or 'Нет описания'}"
    )

    # === КНОПКИ (внизу карточки) ===
    keyboard = []

    if is_admin:
        # Кнопка "Продано"
        btn_text = "❌ Убрать продажу" if is_sold_db else "✅ Отметить как проданное"
        keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=f"toggle_sold_{item_id}")])

        # Кнопки "Удалить" и "Изменить"
        keyboard.append([
            InlineKeyboardButton(text="🗑 Удалить", callback_data="admin_delete_item"),
            InlineKeyboardButton(text="✏️ Изменить", callback_data="admin_edit_item")
        ])

    # Кнопка "Назад"
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin_supply_{supply_id}")])

    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

    # Отправляем фото или текст
    if photo_path and os.path.exists(photo_path):
        try:
            await call.message.delete()  # Удаляем предыдущее сообщение (список)
        except:
            pass
        await bot.send_photo(
            chat_id=call.message.chat.id,
            photo=FSInputFile(photo_path),
            caption=text,
            reply_markup=markup,
            parse_mode="HTML"
        )
    else:
        try:
            await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        except:
            await call.message.answer(text, reply_markup=markup, parse_mode="HTML")
@dp.callback_query(F.data == "admin_delete_item")
async def admin_confirm_delete(call: CallbackQuery, state: FSMContext):
    # Предположим, что мы уже знаем item_id — он должен быть сохранён при открытии товара
    data = await state.get_data()
    item_id = data.get("current_item_id")
    if not item_id:
        await call.answer("Ошибка: не выбран товар.", show_alert=True)
        return

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT title FROM items WHERE id = ?", (item_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        await call.answer("Товар не найден.")
        return

    # Спрашиваем подтверждение
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data="confirm_delete")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_delete")]
    ])
    await call.message.answer(f"Вы уверены, что хотите удалить товар:\n\n<b>{row[0]}</b>?",
                              reply_markup=markup, parse_mode="HTML")


@dp.callback_query(F.data == "confirm_delete")
async def admin_delete_item(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    item_id = data.get("current_item_id")
    if not item_id:
        await call.answer("Ошибка.")
        return

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM items WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()

    await call.message.answer("🗑 Товар успешно удалён!")
    await state.clear()


@dp.callback_query(F.data == "cancel_delete")
async def cancel_delete(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer("❌ Удаление отменено.")

@dp.callback_query(F.data == "admin_edit_item")
async def admin_edit_item_start(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    item_id = data.get("current_item_id")
    if not item_id:
        await call.answer("Ошибка: не выбран товар.", show_alert=True)
        return

    await state.update_data(edit_item_id=item_id)

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Название", callback_data="edit_title")],
        [InlineKeyboardButton(text="💰 Цена закупки", callback_data="edit_price")],
        [InlineKeyboardButton(text="🎯 Цена продажи", callback_data="edit_sell_price")],
        [InlineKeyboardButton(text="📝 Описание", callback_data="edit_description")],
        [InlineKeyboardButton(text="🖼 Фото", callback_data="edit_photo")],
        [InlineKeyboardButton(text="🏷 Статус", callback_data="edit_status")],  # ← НОВАЯ КНОПКА
        [InlineKeyboardButton(text="❌ Отмена", callback_data="edit_cancel")]
    ])
    await call.message.answer("Что хотите изменить?", reply_markup=markup)

STATUSES = [
    "Куплен", "Едет на склад", "На складе", "Едет в МСК",
    "В МСК", "Едет в СПБ", "Наличие", "Продан"
]

@dp.callback_query(F.data == "edit_status")
async def edit_status_prompt(call: CallbackQuery):
    buttons = []
    for status in STATUSES:
        buttons.append([InlineKeyboardButton(text=status, callback_data=f"set_status_{status}")])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="edit_cancel")])
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await call.message.edit_text("Выберите новый статус:", reply_markup=markup)

@dp.callback_query(F.data.startswith("set_status_"))
async def set_status(call: CallbackQuery, state: FSMContext):
    status = call.data.replace("set_status_", "").replace("_", " ")
    data = await state.get_data()
    item_id = data["edit_item_id"]

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE items SET status = ? WHERE id = ?", (status, item_id))
    conn.commit()
    conn.close()

    await call.answer(f"✅ Статус изменён на: {status}")
    await show_item_details(CallbackQuery(
        id=call.id,
        from_user=call.from_user,
        chat_instance=call.chat_instance,
        data=f"item_{item_id}_admin",
        message=call.message
    ))

@dp.callback_query(F.data == "edit_title")
async def edit_title_prompt(call: CallbackQuery, state: FSMContext):
    await state.set_state(EditItem.waiting_new_title)
    await call.message.answer("Введите новое название:")

@dp.message(EditItem.waiting_new_title)
async def edit_title_save(message: Message, state: FSMContext):
    new_title = message.text.strip()
    data = await state.get_data()
    item_id = data["edit_item_id"]

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE items SET title = ? WHERE id = ?", (new_title, item_id))
    conn.commit()
    conn.close()

    await message.answer(f"✅ Название изменено на: <b>{new_title}</b>", parse_mode="HTML")
    await state.clear()
    await cmd_start(message)

@dp.callback_query(F.data == "edit_price")
async def edit_price_prompt(call: CallbackQuery, state: FSMContext):
    await state.set_state(EditItem.waiting_new_price)
    await call.message.answer("Введите новую цену закупки:")



@dp.message(EditItem.waiting_new_price)
async def edit_price_save(message: Message, state: FSMContext):
    try:
        new_price = float(message.text)
    except:
        await message.answer("❌ Введите число!")
        return
    data = await state.get_data()
    item_id = data["edit_item_id"]

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE items SET price = ? WHERE id = ?", (new_price, item_id))
    conn.commit()
    conn.close()

    await message.answer(f"✅ Цена закупки изменена на: <b>{new_price}₽</b>", parse_mode="HTML")
    await state.clear()
    await cmd_start(message)

@dp.callback_query(F.data == "edit_sell_price")
async def edit_sell_price_prompt(call: CallbackQuery, state: FSMContext):
    await state.set_state(EditItem.waiting_new_sell_price)
    await call.message.answer("Введите новую ожидаемую цену продажи:")

@dp.message(EditItem.waiting_new_sell_price)
async def edit_sell_price_save(message: Message, state: FSMContext):
    try:
        new_price = float(message.text)
    except:
        await message.answer("❌ Введите число!")
        return
    data = await state.get_data()
    item_id = data["edit_item_id"]

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE items SET sell_price = ? WHERE id = ?", (new_price, item_id))
    conn.commit()
    conn.close()

    await message.answer(f"✅ Цена продажи изменена на: <b>{new_price}₽</b>", parse_mode="HTML")
    await state.clear()
    await cmd_start(message)

@dp.callback_query(F.data == "edit_description")
async def edit_description_prompt(call: CallbackQuery, state: FSMContext):
    await state.set_state(EditItem.waiting_new_description)
    await call.message.answer("Введите новое описание:")

@dp.message(EditItem.waiting_new_description)
async def edit_description_save(message: Message, state: FSMContext):
    new_desc = message.text.strip()
    data = await state.get_data()
    item_id = data["edit_item_id"]

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE items SET description = ? WHERE id = ?", (new_desc, item_id))
    conn.commit()
    conn.close()

    await message.answer("✅ Описание обновлено.")
    await state.clear()
    await cmd_start(message)
@dp.callback_query(F.data == "edit_photo")
async def edit_photo_prompt(call: CallbackQuery, state: FSMContext):
    await state.set_state(EditItem.waiting_new_photo)
    await call.message.answer("Отправьте новое фото:")

@dp.message(EditItem.waiting_new_photo, F.photo)
async def edit_photo_save(message: Message, state: FSMContext):
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    filename = f"photos/{file.file_id}.jpg"
    await bot.download_file(file.file_path, filename)

    data = await state.get_data()
    item_id = data["edit_item_id"]

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE items SET photo = ? WHERE id = ?", (filename, item_id))
    conn.commit()
    conn.close()

    await message.answer("✅ Фото обновлено.")
    await state.clear()
    await cmd_start(message)

@dp.callback_query(F.data == "edit_cancel")
async def edit_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer("❌ Редактирование отменено.")

# === Переключение статуса "продано" ===
@dp.callback_query(F.data.startswith("toggle_sold_"))
async def toggle_sold(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Только админ!", show_alert=True)
        return

    item_id = int(call.data.split("_")[2])
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT is_sold, supply_id FROM items WHERE id = ?", (item_id,))
    row = cur.fetchone()
    if not row:
        await call.answer("Товар не найден.")
        return

    is_sold = 1 if row[0] == 0 else 0
    cur.execute("UPDATE items SET is_sold = ? WHERE id = ?", (is_sold, item_id))
    conn.commit()
    conn.close()

    await call.answer("Статус обновлён!", show_alert=True)

    # Повторно показываем карточку товара
    await show_item_details(CallbackQuery(
        id=call.id,
        from_user=call.from_user,
        chat_instance=call.chat_instance,
        data=f"item_{item_id}_admin",
        message=call.message
    ))

# === 3. Сделать вклад ===
@dp.callback_query(F.data == "make_contribution")
async def make_contribution(call: CallbackQuery):
    text = (
        "💳 Для внесения вклада переведите деньги на:\n\n"
        "ПРИНИМАЮ ОПЛАТУ ТОЛЬКО НА Т-БАНК!!!\n"
        "Карта: 2200 7010 4325 8000\n"
        "Телефон: +79219753645\n"
        "💬 Комментарий: Вклад в поставку\n\n"
        "После перевода нажмите кнопку ниже:"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я сделал вклад", callback_data="user_start_contribution")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])
    await call.message.edit_text(text, reply_markup=markup)

# === 4. Админская панель ===
@dp.callback_query(F.data == "admin_panel")
async def admin_panel(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Доступ запрещён.", show_alert=True)
        return
    await call.message.answer("🔧 Админ-панель:", reply_markup=get_admin_panel())

@dp.callback_query(F.data == "user_start_contribution")
async def start_contribution_flow(call: CallbackQuery, state: FSMContext):
    banks = ["Сбербанк", "Т-Банк", "Альфа-Банк", "Озон банк", "ВТБ", "Совкомбанк", "Газпромбанк"]
    buttons = [[InlineKeyboardButton(text=bank, callback_data=f"bank_{bank}")] for bank in banks]
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_main")])
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await call.message.edit_text("🏦 Выберите банк:", reply_markup=markup)
    await state.set_state(MakeContribution.waiting_bank)

@dp.callback_query(F.data.startswith("bank_"))
async def contribution_choose_bank(call: CallbackQuery, state: FSMContext):
    bank = call.data.replace("bank_", "").replace("_", " ")
    await state.update_data(bank=bank)
    await state.set_state(MakeContribution.waiting_payment_info)
    await call.message.edit_text(
        f"Вы выбрали: <b>{bank}</b>\n\n"
        "Введите номер телефона или номер карты:",
        parse_mode="HTML"
    )
@dp.message(MakeContribution.waiting_payment_info)
async def contribution_enter_info(message: Message, state: FSMContext):
    payment_info = message.text.strip()
    if not payment_info:
        await message.answer("Введите данные!")
        return

    await state.update_data(payment_info=payment_info)
    data = await state.get_data()

    text = (
        "✅ Подтвердите информацию:\n\n"
        f"🏦 Банк: <b>{data['bank']}</b>\n"
        f"📱/💳 Реквизиты: <code>{payment_info}</code>\n\n"
        "Всё верно?"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, отправить", callback_data="confirm_contribution")],
        [InlineKeyboardButton(text="✏️ Изменить", callback_data="user_start_contribution")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_main")]
    ])
    await message.answer(text, reply_markup=markup, parse_mode="HTML")
    await state.set_state(MakeContribution.waiting_confirm)

@dp.callback_query(F.data == "confirm_contribution")
async def confirm_and_send_to_admin(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user = call.from_user

    # Сохраняем заявку
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO contribution_requests (user_id, username, bank, payment_info, status)
        VALUES (?, ?, ?, ?, 'pending')
    """, (user.id, user.username, data['bank'], data['payment_info']))
    conn.commit()
    request_id = cur.lastrowid
    conn.close()

    # Уведомляем админа
    for admin_id in ADMIN_IDS:
        try:
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Подтвердить вклад", callback_data=f"approve_req_{request_id}")],
                [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_req_{request_id}")]
            ])
            await bot.send_message(
                admin_id,
                f"📬 <b>Новая заявка на вклад</b>\n"
                f"👤 Пользователь: {user.full_name} (@{user.username or 'нет'})\n"
                f"🏦 Банк: {data['bank']}\n"
                f"📱/💳: <code>{data['payment_info']}</code>",
                reply_markup=markup,
                parse_mode="HTML"
            )
        except:
            pass

    await call.message.edit_text(
        "✅ Ваша заявка отправлена администратору.\n"
        "Ожидайте подтверждения вклада.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
        ])
    )
    await state.clear()

# === Админ: Посмотреть вклады ===
@dp.callback_query(F.data == "admin_view_contributions")
async def admin_view_contributions(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT tg.username, c.user_id, s.name, c.amount
        FROM contributions c
        JOIN supplies s ON c.supply_id = s.id
        LEFT JOIN (SELECT user_id, username FROM contributions GROUP BY user_id) tg
        ON c.user_id = tg.user_id
    """)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await call.answer("Нет вкладов.", show_alert=True)
        return

    text = "📊 Все вклады:\n\n"
    for username, user_id, supply_name, amount in rows:
        username = username or f"ID:{user_id}"
        text += f"👤 {username} → {supply_name}: {amount}₽\n"

    await call.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
    ]))

# === Админ: Добавить товар ===
@dp.callback_query(F.data == "admin_add_item")
async def admin_add_item_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Доступ запрещён.", show_alert=True)
        return

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM supplies WHERE status = 'active'")
    supplies = cur.fetchall()
    conn.close()

    if not supplies:
        await call.answer("Нет активных поставок. Сначала создайте поставку.", show_alert=True)
        return

    if len(supplies) == 1:
        # Если одна — сразу переходим к вводу
        await state.update_data(supply_id=supplies[0][0])
        await state.set_state(AddItem.waiting_title)
        await call.message.answer("✏️ Введите название товара:")
    else:
        # Если несколько — даём выбор
        buttons = []
        for s in supplies:
            buttons.append([InlineKeyboardButton(text=s[1], callback_data=f"select_supply_{s[0]}")])
        buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="admin_panel")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await call.message.answer("Выберите поставку для заполнения:", reply_markup=markup)

@dp.callback_query(F.data.startswith("select_supply_"))
async def select_supply_for_item(call: CallbackQuery, state: FSMContext):
    supply_id = int(call.data.split("_")[2])
    await state.update_data(supply_id=supply_id)
    await state.set_state(AddItem.waiting_title)
    await call.message.answer("✏️ Введите название товара:")

@dp.message(AddItem.waiting_title)
async def add_item_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("💰 Введите цену закупки (в рублях):")
    await state.set_state(AddItem.waiting_price)

@dp.message(AddItem.waiting_price)
async def add_item_price(message: Message, state: FSMContext):
    try:
        price = float(message.text)
    except:
        await message.answer("❌ Ошибка: введите число!")
        return
    await state.update_data(price=price)
    await message.answer("🎯 Введите ожидаемую цену продажи:")
    await state.set_state(AddItem.waiting_sell_price)

@dp.message(AddItem.waiting_sell_price)
async def add_item_sell_price(message: Message, state: FSMContext):
    try:
        sell_price = float(message.text)
    except:
        await message.answer("❌ Ошибка: введите число!")
        return
    await state.update_data(sell_price=sell_price)
    await message.answer("📝 Введите описание товара:")
    await state.set_state(AddItem.waiting_description)

@dp.message(AddContribution.waiting_username)
async def enter_username(message: Message, state: FSMContext):
    username = message.text.strip()

    # Убираем @, если есть
    if username.startswith('@'):
        username = username[1:]

    if not username:
        await message.answer("❌ Некорректный юзернейм. Попробуйте снова.")
        return

    await state.update_data(username=username)
    await state.set_state(AddContribution.waiting_amount)
    await message.answer(f"💰 Введите сумму вклада (в рублях) для пользователя <b>@{username}</b>:", parse_mode="HTML")

@dp.message(AddContribution.waiting_amount)
async def enter_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        if amount <= 0:
            raise ValueError
    except:
        await message.answer("❌ Введите положительное число!")
        return

    data = await state.get_data()
    username = data["username"]

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    # Ищем user_id по username
    cur.execute("SELECT user_id FROM contributions WHERE username = ? LIMIT 1", (username,))
    row = cur.fetchone()

    if not row:
        # Дополнительный поиск — если username есть у кого-то, но user_id не привязан
        cur.execute("""
            SELECT user_id FROM contributions 
            WHERE username = ? 
            LIMIT 1
        """, (username,))
        row = cur.fetchone()

    if not row:
        await message.answer(f"❌ Пользователь <b>@{username}</b> не найден в системе.\n"
                             f"Он должен хотя бы раз нажать /start.", parse_mode="HTML")
        await state.clear()
        return

    user_id = row[0]

    # Получаем активную поставку
    cur.execute("SELECT id FROM supplies WHERE status = 'active' LIMIT 1")
    supply_row = cur.fetchone()
    if not supply_row:
        await message.answer("❌ Нет активной поставки. Создайте сначала поставку.")
        await state.clear()
        return

    supply_id = supply_row[0]

    # Проверяем, есть ли уже вклад
    cur.execute("SELECT amount FROM contributions WHERE user_id = ? AND supply_id = ?", (user_id, supply_id))
    existing = cur.fetchone()

    if existing:
        new_amount = existing[0] + amount
        cur.execute("UPDATE contributions SET amount = ? WHERE user_id = ? AND supply_id = ?",
                    (new_amount, user_id, supply_id))
        msg_text = f"✅ Вклад обновлён! Теперь у @{username} вклад: {new_amount}₽ в поставке #{supply_id}."
    else:
        cur.execute("INSERT INTO contributions (user_id, supply_id, amount, username) VALUES (?, ?, ?, ?)",
                    (user_id, supply_id, amount, username))
        msg_text = f"✅ Вклад на {amount}₽ добавлен для пользователя @{username} в поставку #{supply_id}."

    conn.commit()
    conn.close()

    await message.answer(msg_text)
    await state.clear()
    await message.answer("Выберите действие:", reply_markup=get_main_menu(message.from_user.id))

@dp.message(AddItem.waiting_description)
async def add_item_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await message.answer("🖼 Отправьте фото товара:")
    await state.set_state(AddItem.waiting_photo)

@dp.message(AddItem.waiting_photo, F.photo)
async def add_item_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    filename = f"photos/{file.file_id}.jpg"
    await bot.download_file(file.file_path, filename)

    # Определяем активную поставку
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id FROM supplies WHERE status = 'active' LIMIT 1")
    supply_id_row = cur.fetchone()
    supply_id = supply_id_row[0] if supply_id_row else 1

    # Получаем supply_id из FSM
    supply_id = data.get("supply_id")
    if not supply_id:
        await message.answer("❌ Ошибка: не выбрана поставка.")
        await state.clear()
        return

    cur.execute("INSERT INTO items (supply_id, title, price, sell_price, description, photo) VALUES (?, ?, ?, ?, ?, ?)",
                (supply_id, data['title'], data['price'], data['sell_price'], data['description'], filename))
    conn.commit()
    conn.close()

    await message.answer("✅ Товар успешно добавлен!")
    await state.clear()
    await message.answer("Выберите действие:", reply_markup=get_main_menu(message.from_user.id))

# === Кнопка "Назад" в главное меню ===
@dp.callback_query(F.data == "back_to_main")
async def back_to_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer("Выберите действие:", reply_markup=get_main_menu(call.from_user.id))

# === ЗАПУСК ===
async def main():
    print("✅ Бот запущен. Все сообщения сохраняются в чате.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())