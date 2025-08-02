import asyncio
import os
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import asyncpg # Changed from sqlite3
from datetime import datetime
from dotenv import load_dotenv # For loading environment variables

load_dotenv() # Load environment variables from .env file

# === НАСТРОЙКИ ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")  # Get from environment or default
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "1453081434").split(',')))  # Get from environment or default
PAYMENT_DETAILS = (
    "💳 Реквизиты для вклада:\n"
    "Принимаю ТОЛЬКО Т-БАНК!!!\n"
    "Карта: 2200 7010 4325 8000\n"
    "Телефон: +79219753645\n"
    "💬 Комментарий: Вклад в поставку"
)

# === ПАПКИ ===
os.makedirs("photos", exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL") # Railway provides this env var

# === БАЗА ДАННЫХ ===
async def init_db():
    conn = None
    try:
        conn = await asyncpg.connect(DATABASE_URL)

        # === Поставки ===
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS supplies (
                id BIGSERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT DEFAULT 'active'
            )
        """)

        # === Товары ===
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id BIGSERIAL PRIMARY KEY,
                supply_id INTEGER,
                title TEXT,
                price REAL,
                sell_price REAL,
                description TEXT,
                photo TEXT,
                is_sold BOOLEAN DEFAULT FALSE, -- Changed from INTEGER to BOOLEAN
                status TEXT DEFAULT 'Куплен', -- Added default for new column
                FOREIGN KEY(supply_id) REFERENCES supplies(id) ON DELETE CASCADE
            )
        """)

        # === Вклады ===
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contributions (
                user_id BIGINT,
                supply_id INTEGER,
                amount REAL,
                username TEXT,
                PRIMARY KEY (user_id, supply_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contribution_requests (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT,
                username TEXT,
                bank TEXT,
                payment_info TEXT,
                status TEXT DEFAULT 'pending'  -- pending, approved, rejected
            )
        """)

        # === ДОБАВЛЯЕМ СТОЛБЕЦ status, ЕСЛИ ЕГО НЕТ ===
        # Check if 'status' column exists in 'items' table
        column_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'items' AND column_name = 'status'
            );
        """)
        if not column_exists:
            await conn.execute("ALTER TABLE items ADD COLUMN status TEXT DEFAULT 'Куплен'")

        # === Создаём тестовую поставку, если нет ===
        count = await conn.fetchval("SELECT COUNT(*) FROM supplies")
        if count == 0:
            await conn.execute("INSERT INTO supplies (name, status) VALUES ('Поставка #1', 'active')")

    except Exception as e:
        print(f"Error initializing database: {e}")
    finally:
        if conn:
            await conn.close()

# Call init_db in main async function
# asyncio.run(init_db()) - this will be called in main()

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

class EditContribution(StatesGroup):
    waiting_new_amount = State()

# === БОТ ===
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Helper function for database connection
async def get_db_conn():
    return await asyncpg.connect(DATABASE_URL)

# === КЛАВИАТУРЫ ===
def get_main_menu(user_id):
    buttons = [
        [InlineKeyboardButton(text="1️⃣ Мой вклад", callback_data="my_contributions")],
        [InlineKeyboardButton(text="2️⃣ Посмотреть поставку", callback_data="view_supply")],
        [InlineKeyboardButton(text="3️⃣ Сделать вклад", callback_data="make_contribution")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="my_stats")],
        [InlineKeyboardButton(text="❓ Вопросы", callback_data="faq")]
    ]
    if user_id in ADMIN_IDS:
        buttons.append([InlineKeyboardButton(text="🔧 Админская панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def get_supply_list_keyboard(supply_type):
    conn = await get_db_conn()
    supplies = []
    try:
        if supply_type == "current":
            supplies = await conn.fetch("SELECT id, name FROM supplies WHERE status = 'active'")
        else:
            supplies = await conn.fetch("SELECT id, name FROM supplies WHERE status = 'completed'")
    finally:
        await conn.close()

    buttons = []
    for s in supplies:
        buttons.append([InlineKeyboardButton(text=s['name'], callback_data=f"supply_{s['id']}_{supply_type}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def get_item_list_keyboard(supply_id, for_admin=False):
    conn = await get_db_conn()
    items = []
    try:
        items = await conn.fetch("SELECT id, title, price, is_sold FROM items WHERE supply_id = $1", supply_id)
    finally:
        await conn.close()

    buttons = []
    for item in items:
        item_id, title, price, is_sold = item['id'], item['title'], item['price'], item['is_sold']
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
        [InlineKeyboardButton(text="📬 Заявки на вклады", callback_data="admin_view_requests")],
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

    conn = await get_db_conn()
    requests = []
    try:
        requests = await conn.fetch("SELECT id, user_id, username, bank, payment_info FROM contribution_requests WHERE status = 'pending'")
    finally:
        await conn.close()

    if not requests:
        await call.answer("Нет новых заявок.", show_alert=True)
        return

    for req in requests:
        req_id, user_id, username, bank, info = req['id'], req['user_id'], req['username'], req['bank'], req['payment_info']
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


@dp.callback_query(F.data == "faq")
async def show_faq(call: CallbackQuery):
    faq_text = (
        "❓ <b>Часто задаваемые вопросы</b>\n\n"

        "1️⃣ <b>Как вернуть деньги за вклад?</b>\n"
        "Деньги за вклад можно вернуть только при условии, что они ещё не потрачены на покупку. Об этом можно спросить у админа @arkhipster\n\n"

        "2️⃣ <b>Как рассчитывается процент вклада?</b>\n"
        "Процент вклада рассчитывается по формуле:\n<code>(Сумма вашего вклада / сумма всех вкладчиков) * 0.8</code>\n"
        "20% с суммы вашего вклада идёт на поддержание бота, обеспечение услуг доставки, продажи и поиска вещей, которые ГАРАНТИРОВАННО продадутся с наценкой.\n\n"

        "3️⃣ <b>Что делать, если процент вклада уменьшается?</b>\n"
        "Чем больше общей суммы вклада, тем меньше ваш процент. Но это не значит, что вы получите меньше денег — чем больше сумма всех вкладов, тем больше вещей я могу заказать за одну поставку.\n\n"

        "4️⃣ <b>Как часто бывают поставки?</b>\n"
        "Каждая новая поставка появляется, как только предыдущая была полностью выкуплена и отправлена в РФ (в основном это занимает 1–2 недели).\n\n"

        "5️⃣ <b>Сколько я получу, если вложу 10 000 рублей?</b>\n"
        "Примерный заработок оценивается в 20–100% от изначальной стоимости.\n\n"

        "6️⃣ <b>Есть ли гарантии, что я получу деньги, даже если товар не продаётся?</b>\n"
        "Если товар не продаётся, я возвращаю сумму вашего вклада.\n\n"

        "7️⃣ <b>Как понять, что товар не продался?</b>\n"
        "Если товар лежит на продаже больше двух месяцев (для товаров дороже 15 000₽ — максимум 3 месяца), считается, что он не продался."
    )

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])

    await call.message.edit_text(faq_text, reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data == "my_stats")
async def my_stats(call: CallbackQuery):
    user_id = call.from_user.id

    conn = await get_db_conn()
    contrib_rows = []
    try:
        # === 1. Все вклады пользователя ===
        contrib_rows = await conn.fetch("""
            SELECT s.name, s.status, c.amount
            FROM contributions c
            JOIN supplies s ON c.supply_id = s.id
            WHERE c.user_id = $1
        """, user_id)

        if not contrib_rows:
            await call.answer("Вы ещё не делали вкладов.", show_alert=True)
            return

        # 1. Общая сумма вкладов
        total_invested = sum(row['amount'] for row in contrib_rows)

        # 2. Прибыль от продаж (только завершённые поставки)
        total_profit = 0
        for row in contrib_rows:
            supply_name, status, amount = row['name'], row['status'], row['amount']
            if status == "completed":
                profit = amount * 0.3  # 30% прибыли
                total_profit += profit

        # 3. Самый большой вклад
        biggest_contrib = max(contrib_rows, key=lambda x: x['amount'])
        biggest_contrib_amount = biggest_contrib['amount']
        biggest_contrib_supply = biggest_contrib['name']

        # 4. Количество поставок
        num_supplies = len(contrib_rows)

        # 5. Самая удачная поставка (по коэффициенту прибыли)
        best_supply = None
        best_ratio = 0
        for row in contrib_rows:
            supply_name, status, amount = row['name'], row['status'], row['amount']
            if status == "completed":
                profit = amount * 0.3
                ratio = profit / amount  # можно умножить на 100 для %
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_supply = supply_name

        # 6. Место в топе
        top_rows = await conn.fetch("""
            SELECT user_id, SUM(amount) as total
            FROM contributions
            GROUP BY user_id
            ORDER BY total DESC
        """)
    finally:
        await conn.close()

    my_total = total_invested
    my_rank = 1
    for row in top_rows:
        if row['total'] >= my_total:
            my_rank += 1
        else:
            break
    my_rank -= 1  # исправляем смещение

    # === Формируем текст ===
    text = (
        "📊 <b>Ваша статистика</b>\n\n"
        f"💸 Всего вложено: <b>{total_invested}₽</b>\n"
        f"💰 Получено с продаж: <b>{total_profit:.2f}₽</b>\n"
        f"🏆 Самый большой вклад: <b>{biggest_contrib_amount}₽</b> {biggest_contrib_supply}\n"
        f"🏅 Место в топе по вкладам за все время: <b>{my_rank}</b>\n"
        f"🎯 Самая удачная поставка: <b>{best_supply or 'Нет завершённых'}</b>\n"
        f"📦 Участвовал в поставках: <b>{num_supplies}</b>\n"
    )

    # === Кнопка "Назад" ===
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])

    await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data.startswith("approve_req_"))
async def approve_contribution_request(call: CallbackQuery, state: FSMContext):
    req_id = int(call.data.split("_")[2])

    conn = await get_db_conn()
    row = None
    try:
        row = await conn.fetchrow("SELECT user_id, bank, payment_info FROM contribution_requests WHERE id = $1", req_id)
    finally:
        await conn.close()

    if not row:
        await call.answer("Заявка не найдена.")
        return

    user_id, bank, info = row['user_id'], row['bank'], row['payment_info']

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

    conn = await get_db_conn()
    try:
        # Получаем последнюю активную поставку
        supply_id = await get_latest_active_supply_id()
        if not supply_id:
            await message.answer("❌ Нет активной поставки.")
            await state.clear()
            return

        # Проверяем, есть ли уже вклад
        existing = await conn.fetchrow("SELECT amount FROM contributions WHERE user_id = $1 AND supply_id = $2", user_id, supply_id)

        async with conn.transaction():
            if existing:
                new_amount = existing['amount'] + amount
                await conn.execute("UPDATE contributions SET amount = $1 WHERE user_id = $2 AND supply_id = $3",
                                    new_amount, user_id, supply_id)
            else:
                await conn.execute("INSERT INTO contributions (user_id, supply_id, amount) VALUES ($1, $2, $3)",
                                    user_id, supply_id, amount)

            # Обновляем статус заявки
            await conn.execute("UPDATE contribution_requests SET status = 'approved' WHERE id = $1", req_id)
    finally:
        await conn.close()

    # Уведомляем пользователя
    try:
        await bot.send_message(
            user_id,
            f"✅ Ваш вклад на {amount}₽ подтверждён!\n"
            f"Он добавлен в поставку #{supply_id}."
        )
    except Exception as e:
        print(f"Failed to send message to user {user_id}: {e}")

    await message.answer("✅ Вклад подтверждён и добавлен.")
    await state.clear()
    await cmd_start(message)

# === ОСНОВНЫЕ ОБРАБОТЧИКИ ===

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username

    await state.clear()

    conn = await get_db_conn()
    try:
        # Получаем последнюю активную поставку
        supply_row = await conn.fetchrow("SELECT id FROM supplies WHERE status = 'active' ORDER BY id DESC LIMIT 1")
        supply_id = None
        if not supply_row:
            # Если нет — создаём
            supply_id = await conn.fetchval(
                "INSERT INTO supplies (name, status) VALUES ($1, 'active') RETURNING id",
                f"Поставка от {datetime.now().strftime('%d.%m.%Y')}"
            )
        else:
            supply_id = supply_row['id']

        # Проверяем, есть ли уже вклад в ЭТОЙ поставке
        existing_contribution = await conn.fetchrow("SELECT 1 FROM contributions WHERE user_id = $1 AND supply_id = $2", user_id, supply_id)
        if not existing_contribution:
            await conn.execute("INSERT INTO contributions (user_id, supply_id, amount, username) VALUES ($1, $2, 0, $3)", user_id, supply_id, username)
        else:
            await conn.execute("UPDATE contributions SET username = $1 WHERE user_id = $2 AND supply_id = $3", username, user_id, supply_id)
    finally:
        await conn.close()

    await message.answer("👋 Добро пожаловать! Выберите действие:", reply_markup=get_main_menu(user_id))


async def get_latest_active_supply_id():
    conn = await get_db_conn()
    row = None
    try:
        row = await conn.fetchrow("SELECT id FROM supplies WHERE status = 'active' ORDER BY id DESC LIMIT 1")
    finally:
        await conn.close()
    return row['id'] if row else None


@dp.callback_query(F.data.startswith("user_item_"))
async def user_show_item_details(call: CallbackQuery):
    item_id = int(call.data.split("_")[2])
    user_id = call.from_user.id

    conn = await get_db_conn()
    row = None
    try:
        row = await conn.fetchrow("""
            SELECT title, price, sell_price, description, photo, is_sold, supply_id, status
            FROM items WHERE id = $1
        """, item_id)
        if not row:
            await call.answer("Товар не найден.")
            return

        title, price, sell_price, desc, photo_path, is_sold_db, supply_id, status = \
            row['title'], row['price'], row['sell_price'], row['description'], row['photo'], \
            row['is_sold'], row['supply_id'], row['status']

        # === РАСЧЁТ ДОЛИ ВКЛАДА ===
        contrib_row = await conn.fetchrow("SELECT amount FROM contributions WHERE user_id = $1 AND supply_id = $2", user_id, supply_id)
        user_contribution = contrib_row['amount'] if contrib_row else 0

        all_contribs = await conn.fetch("SELECT user_id, amount FROM contributions WHERE supply_id = $1", supply_id)
        total = sum(c['amount'] for c in all_contribs)

        share = 0
        if total != 0:
            share = (user_contribution / total) * 100

        if user_id in ADMIN_IDS:
            other_users = [c['user_id'] for c in all_contribs if c['user_id'] not in ADMIN_IDS]
            N = len(other_users)
            if N > 0:
                share = min(share + 20.0, 100)
        else:
            admin_in_supply = any(c['user_id'] in ADMIN_IDS for c in all_contribs)
            if admin_in_supply:
                other_users = [c['user_id'] for c in all_contribs if c['user_id'] not in ADMIN_IDS]
                N = len(other_users)
                if N > 0:
                    deduction = 20.0 / N
                    share = max(share - deduction, 0)
    finally:
        await conn.close()

    # === СРОКИ ===
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
        f"🏷 Статус: <b>{status}</b>\n"
        f"📊 Ваша доля: <b>{share:.1f}%</b>\n\n"
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

@dp.callback_query(F.data == "admin_create_supply")
async def admin_create_supply(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Доступ запрещён.", show_alert=True)
        return

    name = f"Поставка от {datetime.now().strftime('%d.%m.%Y')}"

    conn = await get_db_conn()
    try:
        await conn.execute("INSERT INTO supplies (name, status) VALUES ($1, 'active')", name)
    finally:
        await conn.close()

    await call.answer(f"✅ Поставка '{name}' создана!", show_alert=True)
    await admin_panel(call)

@dp.callback_query(F.data == "admin_delete_supply")
async def admin_delete_supply_start(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Доступ запрещён.", show_alert=True)
        return

    conn = await get_db_conn()
    supplies = []
    try:
        supplies = await conn.fetch("SELECT id, name FROM supplies WHERE status = 'active'")
    finally:
        await conn.close()

    if not supplies:
        await call.answer("Нет активных поставок.", show_alert=True)
        return

    buttons = []
    for s in supplies:
        buttons.append([InlineKeyboardButton(text=s['name'], callback_data=f"confirm_delete_supply_{s['id']}")])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="admin_panel")])

    await call.message.answer("Выберите поставку для удаления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@dp.callback_query(F.data.startswith("confirm_delete_supply_"))
async def confirm_delete_supply(call: CallbackQuery):
    supply_id = int(call.data.split("_")[3])

    conn = await get_db_conn()
    name = None
    try:
        name = await conn.fetchval("SELECT name FROM supplies WHERE id = $1", supply_id)
    finally:
        await conn.close()

    if not name:
        await call.answer("Поставка не найдена.")
        return

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 В предыдущие", callback_data=f"move_supply_{supply_id}")],
        [InlineKeyboardButton(text="💀 Удалить полностью", callback_data=f"full_delete_supply_{supply_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_panel")]
    ])
    await call.message.edit_text(f"Что сделать с поставкой:\n\n<b>{name}</b>?", reply_markup=markup, parse_mode="HTML")


@dp.callback_query(F.data.startswith("move_supply_"))
async def move_supply_to_completed(call: CallbackQuery):
    supply_id = int(call.data.split("_")[2])

    conn = await get_db_conn()
    try:
        await conn.execute("UPDATE supplies SET status = 'completed' WHERE id = $1", supply_id)
    finally:
        await conn.close()

    await call.answer("✅ Поставка перемещена в 'Предыдущие'.")
    await admin_panel(call)


@dp.callback_query(F.data.startswith("full_delete_supply_"))
async def full_delete_supply(call: CallbackQuery):
    supply_id = int(call.data.split("_")[3])

    conn = await get_db_conn()
    try:
        async with conn.transaction():
            await conn.execute("DELETE FROM items WHERE supply_id = $1", supply_id)
            await conn.execute("DELETE FROM supplies WHERE id = $1", supply_id)
    finally:
        await conn.close()

    await call.answer("✅ Поставка и все товары удалены.")
    await admin_panel(call)

@dp.callback_query(F.data.startswith("admin_item_"))
async def admin_show_item_details(call: CallbackQuery, state: FSMContext):
    item_id = int(call.data.split("_")[2])

    await state.update_data(current_item_id=item_id)

    conn = await get_db_conn()
    row = None
    try:
        row = await conn.fetchrow("""
            SELECT title, price, sell_price, description, photo, is_sold, supply_id, status
            FROM items WHERE id = $1
        """, item_id)
    finally:
        await conn.close()

    if not row:
        await call.answer("Товар не найден.")
        return

    title, price, sell_price, desc, photo_path, is_sold_db, supply_id, status = \
        row['title'], row['price'], row['sell_price'], row['description'], row['photo'], \
        row['is_sold'], row['supply_id'], row['status']
    text = (
        f"📦 <b>{title}</b>\n\n"
        f"💰 Закупка: <b>{price}₽</b>\n"
        f"🎯 Продажа: <b>{sell_price}₽</b>\n"
        f"🏷 Статус: <b>{status}</b>\n"
        f"📦 Продажа: {'✅' if is_sold_db else '🔄'}\n\n"
        f"📝 Описание:\n{desc or 'Нет описания'}"
    )

    keyboard = []

    btn_text = "❌ Убрать продажу" if is_sold_db else "✅ Отметить как проданное"
    keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=f"toggle_sold_{item_id}")])

    keyboard.append([
        InlineKeyboardButton(text="🗑 Удалить", callback_data="admin_delete_item"),
        InlineKeyboardButton(text="✏️ Изменить", callback_data="admin_edit_item")
    ])

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

    conn = await get_db_conn()
    all_supplies = []
    contrib_dict = {}
    try:
        all_supplies = await conn.fetch("SELECT id, name FROM supplies WHERE status IN ('active', 'completed')")
        contrib_rows = await conn.fetch("SELECT supply_id, amount FROM contributions WHERE user_id = $1", user_id)
        contrib_dict = {row['supply_id']: row['amount'] for row in contrib_rows}
    finally:
        await conn.close()

    if not all_supplies:
        await call.answer("Нет поставок.", show_alert=True)
        return

    buttons = []
    for s_id, s_name in [(s['id'], s['name']) for s in all_supplies]:
        amount = contrib_dict.get(s_id, 0)
        buttons.append([InlineKeyboardButton(text=f"{s_name} — {amount}₽", callback_data=f"user_supply_{s_id}")])

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")])

    await call.message.answer("📦 Ваши поставки:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
# === 2. Посмотреть поставку ===
@dp.callback_query(F.data == "view_supply")
async def view_supply(call: CallbackQuery):
    buttons = [
        [InlineKeyboardButton(text="🚚 Нынешняя поставка", callback_data="supply_list_current")],
        [InlineKeyboardButton(text="📦 Предыдущие поставки", callback_data="supply_list_completed")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ]
    await call.message.answer("Выберите поставку:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("user_supply_"))
async def user_show_supply_details(call: CallbackQuery):
    supply_id = int(call.data.split("_")[2])
    user_id = call.from_user.id

    conn = await get_db_conn()
    supply_name = None
    supply_status = None
    user_amount = 0
    total_profit = 0
    expected_earnings = 0
    share = 0
    bank = "Не указаны"
    payment_info = "Не указаны"

    try:
        supply_row = await conn.fetchrow("SELECT name, status FROM supplies WHERE id = $1", supply_id)
        if not supply_row:
            await call.answer("Поставка не найдена.")
            return
        supply_name, supply_status = supply_row['name'], supply_row['status']

        contrib_row = await conn.fetchrow("SELECT amount FROM contributions WHERE user_id = $1 AND supply_id = $2", user_id, supply_id)
        user_amount = contrib_row['amount'] if contrib_row else 0

        items = await conn.fetch("SELECT price, sell_price FROM items WHERE supply_id = $1", supply_id)

        if items:
            total_cost = sum(item['price'] for item in items)
            total_revenue = sum(item['sell_price'] for item in items)
            total_profit = total_revenue - total_cost

            total_contrib = await conn.fetchval("SELECT COALESCE(SUM(amount), 0) FROM contributions WHERE supply_id = $1", supply_id)

            if total_contrib > 0:
                share = user_amount / total_contrib
            else:
                share = 0

            if user_id in ADMIN_IDS:
                other_share = 1 - share
                bonus = 0.2 * other_share
                share = min(share + bonus, 1)

            expected_earnings = round(total_profit * share, 2)

        req_row = await conn.fetchrow("SELECT bank, payment_info FROM contribution_requests WHERE user_id = $1 AND status = 'pending' ORDER BY id DESC LIMIT 1", user_id)
        bank = req_row['bank'] if req_row else "Не указаны"
        payment_info = req_row['payment_info'] if req_row else "Не указаны"

    finally:
        await conn.close()

    text = (
        f"📦 <b>{supply_name}</b>\n\n"
        f"🚚 Приедет: <b>20–30 дней</b>\n"
        f"⏱ Продажа: <b>зависит от цены</b>\n"
        f"💰 Предполагаемый заработок: <b>{expected_earnings}₽</b>\n"
        f"💸 Ваш вклад: <b>{user_amount}₽</b>\n"
        f"📊 Ваша доля: <b>{share*100:.1f}%</b>\n\n"
        f"🏦 Банк: <b>{bank}</b>\n"
        f"📱/💳 Реквизиты: <code>{payment_info}</code>"
    )

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить реквизиты", callback_data="user_start_contribution")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_contributions")]
    ])

    await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data.startswith("supply_list_"))
async def show_supply_list(call: CallbackQuery):
    supply_type = call.data.split("_")[2]

    conn = await get_db_conn()
    supplies = []
    try:
        if supply_type == "current":
            supplies = await conn.fetch("SELECT id, name FROM supplies WHERE status = 'active'")
        else:
            supplies = await conn.fetch("SELECT id, name FROM supplies WHERE status = 'completed'")
    finally:
        await conn.close()

    buttons = []
    for s in supplies:
        buttons.append([InlineKeyboardButton(text=s['name'], callback_data=f"supply_user_{s['id']}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="view_supply")])
    await call.message.answer(f"Список {supply_type} поставок:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data == "admin_view_supply")
async def admin_view_supply(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Доступ запрещён.", show_alert=True)
        return

    conn = await get_db_conn()
    supplies = []
    try:
        supplies = await conn.fetch("SELECT id, name FROM supplies WHERE status = 'active'")
    finally:
        await conn.close()

    if not supplies:
        await call.answer("Нет активной поставки.", show_alert=True)
        return

    buttons = []
    for s in supplies:
        buttons.append([InlineKeyboardButton(text=s['name'], callback_data=f"admin_supply_{s['id']}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")])
    try:
        await call.message.edit_text("📦 Выберите поставку для управления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    except:
        await call.message.answer("📦 Выберите поставку для управления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("supply_user_"))
async def user_show_supply_items(call: CallbackQuery):
    supply_id = int(call.data.split("_")[2])
    conn = await get_db_conn()
    name_row = None
    try:
        name_row = await conn.fetchrow("SELECT name FROM supplies WHERE id = $1", supply_id)
    finally:
        await conn.close()

    if not name_row:
        await call.answer("Поставка не найдена.")
        return

    await call.message.answer(
        f"📦 Товары в поставке: {name_row['name']}",
        reply_markup=await get_item_list_keyboard(supply_id, for_admin=False)
    )

@dp.callback_query(F.data.startswith("admin_supply_"))
async def admin_show_supply_items(call: CallbackQuery):
    supply_id = int(call.data.split("_")[2])
    conn = await get_db_conn()
    name_row = None
    items = []
    try:
        name_row = await conn.fetchrow("SELECT name FROM supplies WHERE id = $1", supply_id)
        if not name_row:
            await call.answer("Поставка не найдена.")
            return
        items = await conn.fetch("SELECT id, title, price, is_sold FROM items WHERE supply_id = $1", supply_id)
    finally:
        await conn.close()

    buttons = []
    for item in items:
        item_id, title, price, is_sold = item['id'], item['title'], item['price'], item['is_sold']
        status = "✅" if is_sold else "🔄"
        text = f"{title} — {price}₽ {status}"
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"admin_item_{item_id}")]) # Changed callback to admin_item_

    buttons.append([InlineKeyboardButton(text="🗑 Удалить все товары", callback_data=f"delete_all_{supply_id}")])
    buttons.append([InlineKeyboardButton(text="🔁 Изменить статус всех", callback_data=f"bulk_status_{supply_id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_view_supply")])
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await call.message.answer(f"📦 Управление поставкой: {name_row['name']}", reply_markup=markup)

@dp.callback_query(F.data.startswith("delete_all_"))
async def confirm_delete_all(call: CallbackQuery):
    supply_id = int(call.data.split("_")[2])
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить всё", callback_data=f"confirm_delete_all_{supply_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_view_supply")]
    ])
    await call.message.edit_text("Вы уверены, что хотите удалить **все товары** из этой поставки?", reply_markup=markup, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("confirm_delete_all_"))
async def delete_all_items(call: CallbackQuery):
    supply_id = int(call.data.split("_")[3])
    conn = await get_db_conn()
    try:
        await conn.execute("DELETE FROM items WHERE supply_id = $1", supply_id)
    finally:
        await conn.close()
    await call.message.edit_text("🗑 Все товары удалены.")
    await admin_view_supply(call)

STATUSES = ["Куплен", "В пути", "На складе", "Отправлен", "Продан"] # Define STATUSES for bulk_status_prompt

@dp.callback_query(F.data.startswith("bulk_status_"))
async def bulk_status_prompt(call: CallbackQuery, state: FSMContext):
    supply_id = int(call.data.split("_")[2])
    await state.update_data(bulk_supply_id=supply_id)
    buttons = []
    for status in STATUSES:
        buttons.append([InlineKeyboardButton(text=status, callback_data=f"apply_bulk_status_{status.replace(' ', '_')}")]) # Replace spaces for callback data
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="admin_view_supply")])
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await call.message.edit_text("Выберите статус для **всех товаров** в поставке:", reply_markup=markup, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("apply_bulk_status_"))
async def apply_bulk_status(call: CallbackQuery, state: FSMContext):
    status = call.data.replace("apply_bulk_status_", "").replace("_", " ")
    data = await state.get_data()
    supply_id = data["bulk_supply_id"]
    conn = await get_db_conn()
    try:
        await conn.execute("UPDATE items SET status = $1 WHERE supply_id = $2", status, supply_id)
    finally:
        await conn.close()
    await call.answer(f"✅ Статус всех товаров изменён на: {status}")
    await admin_view_supply(call)

@dp.callback_query(F.data == "admin_add_contribution")
async def admin_add_contribution_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Доступ запрещён.", show_alert=True)
        return

    conn = await get_db_conn()
    supplies = []
    try:
        supplies = await conn.fetch("SELECT id, name FROM supplies WHERE status = 'active'")
    finally:
        await conn.close()

    if not supplies:
        await call.answer("Нет активных поставок. Сначала создайте новую поставку.")
        return

    # If only one active supply, proceed directly, else let admin choose
    if len(supplies) == 1:
        await state.update_data(supply_id=supplies[0]['id'])
        await state.set_state(AddContribution.waiting_username)
        await call.message.answer("👤 Введите <b>юзернейм</b> пользователя (например, @ivan_123 или ivan_123):", parse_mode="HTML")
    else:
        buttons = []
        for s in supplies:
            buttons.append([InlineKeyboardButton(text=s['name'], callback_data=f"select_supply_for_contrib_{s['id']}")])
        buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="admin_panel")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await call.message.answer("📦 В какую поставку добавить вклад?", reply_markup=markup)

@dp.callback_query(F.data.startswith("select_supply_for_contrib_"))
async def select_supply_for_contribution(call: CallbackQuery, state: FSMContext):
    supply_id = int(call.data.split("_")[4])
    await state.update_data(supply_id=supply_id)
    await state.set_state(AddContribution.waiting_username)
    await call.message.answer("👤 Введите <b>юзернейм</b> пользователя (например, @ivan_123 или ivan_123):", parse_mode="HTML")

@dp.callback_query(F.data.startswith("supply_"))
async def show_supply_items(call: CallbackQuery):
    data = call.data.split("_")
    supply_id = int(data[1])
    is_admin = call.from_user.id in ADMIN_IDS
    conn = await get_db_conn()
    name_row = None
    try:
        name_row = await conn.fetchrow("SELECT name FROM supplies WHERE id = $1", supply_id)
    finally:
        await conn.close()

    if not name_row:
        await call.answer("Поставка не найдена.")
        return

    await call.message.answer(
        f"📦 Товары в поставке: {name_row['name']}",
        reply_markup=await get_item_list_keyboard(supply_id, for_admin=is_admin)
    )

# The original code had a duplicate `show_supply_items` function. I'm keeping only one,
# the one that was more complete, and adjusting the callback_data handling.

# New handlers for adding/editing items (placeholder for now, as they were not fully provided in original)
# This requires knowing the FSM states and corresponding message handlers.
# I'll add the general structure based on existing FSMs for AddItem, EditItem.

# Handler for "toggle_sold"
@dp.callback_query(F.data.startswith("toggle_sold_"))
async def toggle_item_sold_status(call: CallbackQuery):
    item_id = int(call.data.split("_")[2])
    conn = await get_db_conn()
    try:
        # Get current status
        current_status = await conn.fetchval("SELECT is_sold FROM items WHERE id = $1", item_id)
        new_status = not current_status
        await conn.execute("UPDATE items SET is_sold = $1 WHERE id = $2", new_status, item_id)
    finally:
        await conn.close()
    await call.answer("Статус товара изменён.")
    # Refresh item details view
    await admin_show_item_details(call, dp.fsm.storage) # Pass storage to reuse state

# Handler for "admin_delete_item" (requires item_id from state)
@dp.callback_query(F.data == "admin_delete_item")
async def admin_delete_item(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    item_id = data.get("current_item_id")
    if not item_id:
        await call.answer("Ошибка: товар не выбран.")
        return

    conn = await get_db_conn()
    try:
        await conn.execute("DELETE FROM items WHERE id = $1", item_id)
    finally:
        await conn.close()
    await call.answer("Товар удалён.")
    await state.clear()
    await admin_panel(call) # Return to admin panel

# Handler for "admin_edit_item" (starts FSM)
@dp.callback_query(F.data == "admin_edit_item")
async def admin_edit_item_start(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    item_id = data.get("current_item_id")
    if not item_id:
        await call.answer("Ошибка: товар не выбран для редактирования.")
        return

    conn = await get_db_conn()
    item_data = None
    try:
        item_data = await conn.fetchrow("SELECT title, price, sell_price, description, photo FROM items WHERE id = $1", item_id)
    finally:
        await conn.close()

    if not item_data:
        await call.answer("Ошибка: товар не найден.")
        return

    await state.update_data(
        item_to_edit_id=item_id,
        original_title=item_data['title'],
        original_price=item_data['price'],
        original_sell_price=item_data['sell_price'],
        original_description=item_data['description'],
        original_photo=item_data['photo']
    )
    await state.set_state(EditItem.waiting_new_title)
    await call.message.answer(f"Введите новое название товара (текущее: {item_data['title']}):")

@dp.message(EditItem.waiting_new_title)
async def process_new_item_title(message: Message, state: FSMContext):
    await state.update_data(new_title=message.text)
    await state.set_state(EditItem.waiting_new_price)
    data = await state.get_data()
    await message.answer(f"Введите новую закупочную цену (текущая: {data['original_price']}):")

@dp.message(EditItem.waiting_new_price)
async def process_new_item_price(message: Message, state: FSMContext):
    try:
        new_price = float(message.text)
        if new_price <= 0: raise ValueError
        await state.update_data(new_price=new_price)
        await state.set_state(EditItem.waiting_new_sell_price)
        data = await state.get_data()
        await message.answer(f"Введите новую цену продажи (текущая: {data['original_sell_price']}):")
    except ValueError:
        await message.answer("Неверный формат цены. Введите число.")

@dp.message(EditItem.waiting_new_sell_price)
async def process_new_item_sell_price(message: Message, state: FSMContext):
    try:
        new_sell_price = float(message.text)
        if new_sell_price <= 0: raise ValueError
        await state.update_data(new_sell_price=new_sell_price)
        await state.set_state(EditItem.waiting_new_description)
        data = await state.get_data()
        await message.answer(f"Введите новое описание товара (текущее: {data['original_description'] or 'Нет описания'}):")
    except ValueError:
        await message.answer("Неверный формат цены. Введите число.")

@dp.message(EditItem.waiting_new_description)
async def process_new_item_description(message: Message, state: FSMContext):
    await state.update_data(new_description=message.text)
    await state.set_state(EditItem.waiting_new_photo)
    await message.answer("Отправьте новое фото товара или нажмите 'Пропустить' для сохранения без изменения фото.",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Пропустить", callback_data="skip_photo_edit")]]))

@dp.message(EditItem.waiting_new_photo, F.photo)
async def process_new_item_photo(message: Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    file = await bot.get_file(file_id)
    filename = f"photos/{file.file_id}.jpg"
    await bot.download_file(file.file_path, filename)
    await state.update_data(new_photo=filename)
    await save_edited_item(message, state)

@dp.callback_query(EditItem.waiting_new_photo, F.data == "skip_photo_edit")
async def skip_item_photo_edit(call: CallbackQuery, state: FSMContext):
    await state.update_data(new_photo=None) # Keep existing photo
    await save_edited_item(call.message, state)


async def save_edited_item(message: Message, state: FSMContext):
    data = await state.get_data()
    item_id = data['item_to_edit_id']
    new_title = data['new_title']
    new_price = data['new_price']
    new_sell_price = data['new_sell_price']
    new_description = data['new_description']
    new_photo = data.get('new_photo') # This will be None if skipped, or path if new photo uploaded

    conn = await get_db_conn()
    try:
        if new_photo is not None:
            await conn.execute(
                "UPDATE items SET title = $1, price = $2, sell_price = $3, description = $4, photo = $5 WHERE id = $6",
                new_title, new_price, new_sell_price, new_description, new_photo, item_id
            )
        else: # Keep existing photo
            await conn.execute(
                "UPDATE items SET title = $1, price = $2, sell_price = $3, description = $4 WHERE id = $5",
                new_title, new_price, new_sell_price, new_description, item_id
            )
    finally:
        await conn.close()

    await message.answer("✅ Товар успешно изменён!")
    await state.clear()
    await message.answer("Выберите действие:", reply_markup=get_main_menu(message.from_user.id))

# Handler for "admin_add_item" (starts FSM)
@dp.callback_query(F.data == "admin_add_item")
async def admin_add_item_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Доступ запрещён.", show_alert=True)
        return

    conn = await get_db_conn()
    supplies = []
    try:
        supplies = await conn.fetch("SELECT id, name FROM supplies WHERE status = 'active'")
    finally:
        await conn.close()

    if not supplies:
        await call.answer("Нет активных поставок. Сначала создайте новую поставку.")
        return

    # If only one active supply, proceed directly, else let admin choose
    if len(supplies) == 1:
        await state.update_data(supply_id=supplies[0]['id'])
        await state.set_state(AddItem.waiting_title)
        await call.message.answer("📦 Введите название товара:")
    else:
        buttons = []
        for s in supplies:
            buttons.append([InlineKeyboardButton(text=s['name'], callback_data=f"select_supply_add_item_{s['id']}")])
        buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="admin_panel")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await call.message.answer("Выберите поставку, в которую хотите добавить товар:", reply_markup=markup)

@dp.callback_query(F.data.startswith("select_supply_add_item_"))
async def select_supply_for_add_item(call: CallbackQuery, state: FSMContext):
    supply_id = int(call.data.split("_")[4])
    await state.update_data(supply_id=supply_id)
    await state.set_state(AddItem.waiting_title)
    await call.message.answer("📦 Введите название товара:")

@dp.message(AddItem.waiting_title)
async def add_item_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(AddItem.waiting_price)
    await message.answer("💰 Введите закупочную цену (число):")

@dp.message(AddItem.waiting_price)
async def add_item_price(message: Message, state: FSMContext):
    try:
        price = float(message.text)
        if price <= 0: raise ValueError
        await state.update_data(price=price)
        await state.set_state(AddItem.waiting_sell_price)
        await message.answer("🎯 Введите цену продажи (число):")
    except ValueError:
        await message.answer("Неверный формат цены. Введите число.")

@dp.message(AddItem.waiting_sell_price)
async def add_item_sell_price(message: Message, state: FSMContext):
    try:
        sell_price = float(message.text)
        if sell_price <= 0: raise ValueError
        await state.update_data(sell_price=sell_price)
        await state.set_state(AddItem.waiting_description)
        await message.answer("📝 Введите описание товара:")
    except ValueError:
        await message.answer("Неверный формат цены. Введите число.")

@dp.message(AddItem.waiting_description)
async def add_item_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(AddItem.waiting_photo)
    await message.answer("📸 Отправьте фото товара:")

@dp.message(AddItem.waiting_photo, F.photo)
async def add_item_photo(message: Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    file = await bot.get_file(file_id)
    filename = f"photos/{file.file_id}.jpg"
    await bot.download_file(file.file_path, filename)
    await state.update_data(photo=filename)

    data = await state.get_data()
    supply_id = data.get("supply_id") # Get supply_id from FSM

    if not supply_id:
        await message.answer("❌ Ошибка: не выбрана поставка.")
        await state.clear()
        return

    conn = await get_db_conn()
    try:
        await conn.execute(
            "INSERT INTO items (supply_id, title, price, sell_price, description, photo) VALUES ($1, $2, $3, $4, $5, $6)",
            supply_id, data['title'], data['price'], data['sell_price'], data['description'], filename
        )
    finally:
        await conn.close()

    await message.answer("✅ Товар успешно добавлен!")
    await state.clear()
    await message.answer("Выберите действие:", reply_markup=get_main_menu(message.from_user.id))

# === Кнопка "Назад" в главное меню ===
@dp.callback_query(F.data == "back_to_main")
async def back_to_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Выберите действие:", reply_markup=get_main_menu(call.from_user.id))

# === Админская панель ===
@dp.callback_query(F.data == "admin_panel")
async def admin_panel(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Доступ запрещён.", show_alert=True)
        return
    await call.message.edit_text("⚙️ Админская панель:", reply_markup=get_admin_panel())

# === Make Contribution (User) ===
@dp.callback_query(F.data == "make_contribution")
async def make_contribution_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(MakeContribution.waiting_bank)
    await call.message.answer(
        "🏦 Введите название вашего банка (например, Сбербанк, Тинькофф):"
    )

@dp.message(MakeContribution.waiting_bank)
async def process_user_bank(message: Message, state: FSMContext):
    await state.update_data(bank=message.text)
    await state.set_state(MakeContribution.waiting_payment_info)
    await message.answer(
        "📱 Введите номер телефона или карты, на который будут переведены деньги в случае возврата/выплаты:"
    )

@dp.message(MakeContribution.waiting_payment_info)
async def process_user_payment_info(message: Message, state: FSMContext):
    await state.update_data(payment_info=message.text)
    data = await state.get_data()
    bank = data['bank']
    payment_info = data['payment_info']

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_contribution_details")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_contribution")]
    ])

    await message.answer(
        f"Проверьте ваши реквизиты:\n"
        f"🏦 Банк: <b>{bank}</b>\n"
        f"📱/💳: <code>{payment_info}</code>\n\n"
        "Всё верно?",
        reply_markup=markup,
        parse_mode="HTML"
    )
    await state.set_state(MakeContribution.waiting_confirm)


@dp.callback_query(MakeContribution.waiting_confirm, F.data == "confirm_contribution_details")
async def confirm_user_contribution(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = call.from_user.id
    username = call.from_user.username
    bank = data['bank']
    payment_info = data['payment_info']

    conn = await get_db_conn()
    try:
        # Check if an existing request needs to be updated or new one inserted
        existing_req = await conn.fetchrow(
            "SELECT id FROM contribution_requests WHERE user_id = $1 AND status = 'pending'",
            user_id
        )
        if existing_req:
            await conn.execute(
                "UPDATE contribution_requests SET username = $1, bank = $2, payment_info = $3 WHERE id = $4",
                username, bank, payment_info, existing_req['id']
            )
        else:
            await conn.execute(
                "INSERT INTO contribution_requests (user_id, username, bank, payment_info) VALUES ($1, $2, $3, $4)",
                user_id, username, bank, payment_info
            )
    finally:
        await conn.close()

    await state.clear()
    await call.answer("✅ Ваши реквизиты сохранены. Теперь вы можете сделать вклад.", show_alert=True)
    await call.message.edit_text(PAYMENT_DETAILS + "\n\nСообщите админу о своём вкладе, чтобы он был подтверждён.", parse_mode="HTML")
    await call.message.answer("Выберите действие:", reply_markup=get_main_menu(user_id))


@dp.callback_query(MakeContribution.waiting_confirm, F.data == "cancel_contribution")
async def cancel_user_contribution(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer("❌ Ввод реквизитов отменён.", show_alert=True)
    await call.message.edit_text("Выберите действие:", reply_markup=get_main_menu(call.from_user.id))

# User starts editing their contribution details (used from user_show_supply_details)
@dp.callback_query(F.data == "user_start_contribution")
async def user_start_contribution_edit(call: CallbackQuery, state: FSMContext):
    await make_contribution_start(call, state)


# New handlers for admin_view_contributions
@dp.callback_query(F.data == "admin_view_contributions")
async def admin_view_contributions(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Доступ запрещён.", show_alert=True)
        return

    conn = await get_db_conn()
    contributions = []
    try:
        contributions = await conn.fetch("""
            SELECT c.user_id, c.username, s.name as supply_name, c.amount
            FROM contributions c
            JOIN supplies s ON c.supply_id = s.id
            ORDER BY supply_name, c.amount DESC
        """)
    finally:
        await conn.close()

    if not contributions:
        await call.answer("Вкладов пока нет.", show_alert=True)
        return

    text = "📊 <b>Все вклады:</b>\n\n"
    current_supply_name = ""
    for contrib in contributions:
        if contrib['supply_name'] != current_supply_name:
            text += f"\n📦 <b>{contrib['supply_name']}</b>\n"
            current_supply_name = contrib['supply_name']
        text += f"  👤 @{contrib['username'] or contrib['user_id']}: {contrib['amount']}₽\n"

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
    ])

    await call.message.answer(text, reply_markup=markup, parse_mode="HTML")


@dp.callback_query(F.data.startswith("reject_req_"))
async def reject_contribution_request(call: CallbackQuery):
    req_id = int(call.data.split("_")[2])

    conn = await get_db_conn()
    try:
        row = await conn.fetchrow("SELECT user_id, username FROM contribution_requests WHERE id = $1", req_id)
        if not row:
            await call.answer("Заявка не найдена.")
            return
        user_id = row['user_id']
        username = row['username']

        await conn.execute("UPDATE contribution_requests SET status = 'rejected' WHERE id = $1", req_id)
    finally:
        await conn.close()

    try:
        await bot.send_message(user_id, f"❌ Ваша заявка на вклад была отклонена.")
    except Exception as e:
        print(f"Failed to notify user {user_id} about rejected request: {e}")

    await call.answer("Заявка отклонена.")
    await admin_view_requests(call) # Refresh the list of pending requests

# Main function to run the bot
async def main():
    await init_db() # Initialize database before starting bot
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())