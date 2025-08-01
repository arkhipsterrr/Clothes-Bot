import asyncio
import os
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import asyncpg
from datetime import datetime

# === НАСТРОЙКИ ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [1453081434]  # Заменить на свой ID

PAYMENT_DETAILS = (
    "💳 Для внесения вклада переведите деньги на:\n\n"
    "Принимаю ТОЛЬКО Т-БАНК!!!\n"
    "Карта: 2200 7010 4325 8000\n"
    "Телефон: +79219753645\n"
    "💬 Комментарий: Вклад в поставку"
)

# === ПАПКИ ===
os.makedirs("photos", exist_ok=True)

# === БАЗА ДАННЫХ ===
async def init_db():
    conn = await asyncpg.connect(
        host=os.getenv("PGHOST"),
        port=os.getenv("PGPORT"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        database=os.getenv("PGDATABASE")
    )

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS supplies (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT DEFAULT 'active'
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id SERIAL PRIMARY KEY,
            supply_id INTEGER,
            title TEXT,
            price REAL,
            sell_price REAL,
            description TEXT,
            photo TEXT,
            is_sold INTEGER DEFAULT 0,
            status TEXT DEFAULT 'Куплен'
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS contributions (
            user_id INTEGER,
            supply_id INTEGER,
            amount REAL,
            username TEXT,
            PRIMARY KEY (user_id, supply_id)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS contribution_requests (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            username TEXT,
            bank TEXT,
            payment_info TEXT,
            status TEXT DEFAULT 'pending'
        )
    """)

    row = await conn.fetchrow("SELECT 1 FROM supplies LIMIT 1")
    if not row:
        await conn.execute(
            "INSERT INTO supplies (name, status) VALUES ($1, 'active')",
            f"Поставка от {datetime.now().strftime('%d.%m.%Y')}"
        )

    await conn.close()

# === FSM ===
class AddItem(StatesGroup):
    waiting_title = State()
    waiting_price = State()
    waiting_sell_price = State()
    waiting_description = State()
    waiting_photo = State()

class AddContribution(StatesGroup):
    waiting_username = State()
    waiting_amount = State()

class MakeContribution(StatesGroup):
    waiting_bank = State()
    waiting_payment_info = State()
    waiting_confirm = State()

class EditItem(StatesGroup):
    waiting_new_title = State()
    waiting_new_price = State()
    waiting_new_sell_price = State()
    waiting_new_description = State()
    waiting_new_photo = State()

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
    # Создаётся динамически
    pass

def get_item_list_keyboard(supply_id, for_admin=False):
    # Создаётся динамически
    pass

def get_admin_panel():
    buttons = [
        [InlineKeyboardButton(text="📋 Посмотреть вклады людей", callback_data="admin_view_contributions")],
        [InlineKeyboardButton(text="➕ Добавить вклад", callback_data="admin_add_contribution")],
        [InlineKeyboardButton(text="📦 Заполнить поставку", callback_data="admin_add_item")],
        [InlineKeyboardButton(text="🔍 Управлять поставкой", callback_data="admin_view_supply")],
        [InlineKeyboardButton(text="🆕 Создать поставку", callback_data="admin_create_supply")],
        [InlineKeyboardButton(text="🗑 Удалить поставку", callback_data="admin_delete_supply")],
        [InlineKeyboardButton(text="📬 Заявки на вклады", callback_data="admin_view_requests")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# === ОСНОВНЫЕ ОБРАБОТЧИКИ ===
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username

    await state.clear()

    conn = await asyncpg.connect(
        host=os.getenv("PGHOST"),
        port=os.getenv("PGPORT"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        database=os.getenv("PGDATABASE")
    )

    row = await conn.fetchrow("SELECT 1 FROM contributions WHERE user_id = $1", user_id)
    if not row:
        await conn.execute("INSERT INTO contributions (user_id, username, amount) VALUES ($1, $2, 0)", user_id, username)
    else:
        await conn.execute("UPDATE contributions SET username = $1 WHERE user_id = $2", username, user_id)

    await conn.close()

    await message.answer("👋 Добро пожаловать! Выберите действие:", reply_markup=get_main_menu(user_id))

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer("Выберите действие:", reply_markup=get_main_menu(call.from_user.id))

@dp.callback_query(F.data == "my_contributions")
async def my_contributions(call: CallbackQuery):
    user_id = call.from_user.id

    conn = await asyncpg.connect(
        host=os.getenv("PGHOST"),
        port=os.getenv("PGPORT"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        database=os.getenv("PGDATABASE")
    )

    rows = await conn.fetch("""
        SELECT s.name, c.amount, s.status
        FROM contributions c
        JOIN supplies s ON c.supply_id = s.id
        WHERE c.user_id = $1
    """, user_id)

    await conn.close()

    if not rows:
        await call.answer("Вы ещё не делали вкладов.", show_alert=True)
        return

    text = "📊 Ваши вклады:\n\n"
    for row in rows:
        name, amount, status = row
        profit = "—"
        percent = "—"
        if status == "completed":
            profit = round(amount * 1.3, 2)
            percent = "30%"
        text += f"📦 {name}\n💸 Вклад: {amount}₽\n📈 Прибыль: {profit}₽\n📊 Доля: {percent}\n\n"

    await call.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ]))

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
    supply_type = call.data.split("_")[2]
    conn = await asyncpg.connect(
        host=os.getenv("PGHOST"),
        port=os.getenv("PGPORT"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        database=os.getenv("PGDATABASE")
    )

    if supply_type == "current":
        supplies = await conn.fetch("SELECT id, name FROM supplies WHERE status = 'active'")
    else:
        supplies = await conn.fetch("SELECT id, name FROM supplies WHERE status = 'completed'")

    await conn.close()

    buttons = []
    for s in supplies:
        buttons.append([InlineKeyboardButton(text=s["name"], callback_data=f"supply_user_{s['id']}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="view_supply")])
    await call.message.answer(f"Список {supply_type} поставок:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("supply_user_"))
async def user_show_supply_items(call: CallbackQuery):
    supply_id = int(call.data.split("_")[2])

    conn = await asyncpg.connect(
        host=os.getenv("PGHOST"),
        port=os.getenv("PGPORT"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        database=os.getenv("PGDATABASE")
    )

    name_row = await conn.fetchrow("SELECT name FROM supplies WHERE id = $1", supply_id)
    if not name_row:
        await call.answer("Поставка не найдена.")
        return

    items = await conn.fetch("SELECT id, title, price, is_sold FROM items WHERE supply_id = $1", supply_id)
    await conn.close()

    buttons = []
    for item in items:
        item_id, title, price, is_sold = item["id"], item["title"], item["price"], item["is_sold"]
        status = "✅" if is_sold else "🔄"
        buttons.append([InlineKeyboardButton(text=f"{title} — {price}₽ {status}", callback_data=f"user_item_{item_id}")])

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="view_supply")])
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await call.message.answer(f"📦 Товары в поставке: {name_row['name']}", reply_markup=markup)

@dp.callback_query(F.data.startswith("user_item_"))
async def user_show_item_details(call: CallbackQuery):
    item_id = int(call.data.split("_")[2])

    conn = await asyncpg.connect(
        host=os.getenv("PGHOST"),
        port=os.getenv("PGPORT"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        database=os.getenv("PGDATABASE")
    )

    row = await conn.fetchrow("""
        SELECT title, price, sell_price, description, photo, is_sold, supply_id, status
        FROM items WHERE id = $1
    """, item_id)
    await conn.close()

    if not row:
        await call.answer("Товар не найден.")
        return

    title, price, sell_price, desc, photo_path, is_sold_db, supply_id, status = row

    arrival_text = "🚚 Приедет примерно: <b>20–30 дней</b>"
    if sell_price < 5000:
        sale_time = "⏱ Продажа: <b>Меньше недели</b>"
    elif 5000 <= sell_price < 10000:
        sale_time = "⏱ Продажа: <b>5–10 дней</b>"
    elif 10000 <= sell_price < 15000:
        sale_time = "⏱ Продажа: <b>10–20 дней</b>"
    else:
        sale_time = "⏱ Продажа: <b>3 недели – 2 месяца</b>"

    money_time = "💰 Деньги: <b>через 1–2 дня после продажи</b>"

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
        await call.message.answer(text, reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data == "make_contribution")
async def make_contribution(call: CallbackQuery):
    text = (
        "💳 Для внесения вклада переведите деньги на:\n\n"
        "Принимаю ТОЛЬКО Т-БАНК!!!\n"
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

    conn = await asyncpg.connect(
        host=os.getenv("PGHOST"),
        port=os.getenv("PGPORT"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        database=os.getenv("PGDATABASE")
    )

    req_id = await conn.fetchval("""
        INSERT INTO contribution_requests (user_id, username, bank, payment_info, status)
        VALUES ($1, $2, $3, $4, 'pending') RETURNING id
    """, user.id, user.username, data['bank'], data['payment_info'])

    await conn.close()

    for admin_id in ADMIN_IDS:
        try:
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Подтвердить вклад", callback_data=f"approve_req_{req_id}")],
                [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_req_{req_id}")]
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

@dp.callback_query(F.data == "admin_panel")
async def admin_panel(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Доступ запрещён.", show_alert=True)
        return
    await call.message.answer("🔧 Админ-панель:", reply_markup=get_admin_panel())

@dp.callback_query(F.data == "admin_view_contributions")
async def admin_view_contributions(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return

    conn = await asyncpg.connect(
        host=os.getenv("PGHOST"),
        port=os.getenv("PGPORT"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        database=os.getenv("PGDATABASE")
    )

    rows = await conn.fetch("""
        SELECT tg.username, c.user_id, s.name, c.amount
        FROM contributions c
        JOIN supplies s ON c.supply_id = s.id
        LEFT JOIN (SELECT user_id, username FROM contributions GROUP BY user_id) tg
        ON c.user_id = tg.user_id
    """)
    await conn.close()

    if not rows:
        await call.answer("Нет вкладов.", show_alert=True)
        return

    text = "📊 Все вклады:\n\n"
    for row in rows:
        username, user_id, supply_name, amount = row["username"], row["user_id"], row["name"], row["amount"]
        username = username or f"ID:{user_id}"
        text += f"👤 {username} → {supply_name}: {amount}₽\n"

    await call.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
    ]))

@dp.callback_query(F.data == "admin_add_contribution")
async def admin_add_contribution_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(AddContribution.waiting_username)
    await call.message.answer("👤 Введите <b>юзернейм</b> пользователя (например, @ivan_123 или ivan_123):", parse_mode="HTML")

@dp.message(AddContribution.waiting_username)
async def enter_username(message: Message, state: FSMContext):
    username = message.text.strip()
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
        if amount <= 0: raise ValueError
    except:
        await message.answer("❌ Введите положительное число!")
        return

    data = await state.get_data()
    username = data["username"]

    conn = await asyncpg.connect(
        host=os.getenv("PGHOST"),
        port=os.getenv("PGPORT"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        database=os.getenv("PGDATABASE")
    )

    row = await conn.fetchrow("SELECT user_id FROM contributions WHERE username = $1 LIMIT 1", username)
    if not row:
        row = await conn.fetchrow("SELECT user_id FROM contributions WHERE username = $1 LIMIT 1", username)
    if not row:
        await message.answer(f"❌ Пользователь <b>@{username}</b> не найден в системе.\nОн должен хотя бы раз нажать /start.", parse_mode="HTML")
        await state.clear()
        return

    user_id = row["user_id"]

    supply_row = await conn.fetchrow("SELECT id FROM supplies WHERE status = 'active' LIMIT 1")
    if not supply_row:
        await message.answer("❌ Нет активной поставки. Создайте сначала поставку.")
        await state.clear()
        return
    supply_id = supply_row["id"]

    existing = await conn.fetchrow("SELECT amount FROM contributions WHERE user_id = $1 AND supply_id = $2", user_id, supply_id)
    if existing:
        new_amount = existing["amount"] + amount
        await conn.execute("UPDATE contributions SET amount = $1 WHERE user_id = $2 AND supply_id = $3", new_amount, user_id, supply_id)
        msg_text = f"✅ Вклад обновлён! Теперь у @{username} вклад: {new_amount}₽ в поставке #{supply_id}."
    else:
        await conn.execute("INSERT INTO contributions (user_id, supply_id, amount, username) VALUES ($1, $2, $3, $4)", user_id, supply_id, amount, username)
        msg_text = f"✅ Вклад на {amount}₽ добавлен для пользователя @{username} в поставку #{supply_id}."

    await conn.close()

    await message.answer(msg_text)
    await state.clear()
    await cmd_start(message, state)

# === ЗАПУСК ===
async def main():
    print("✅ Бот запущен.")
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())