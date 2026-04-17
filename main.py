import html
import logging
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("SHOPPING_BOT_DB_PATH", BASE_DIR / "shopping_bot.db"))
CHECKLIST_KEY = "checklists"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def column_exists(connection: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    columns = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(column["name"] == column_name for column in columns)


def add_column_if_missing(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    if not column_exists(connection, table_name, column_name):
        connection.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
        )


def init_db() -> None:
    with closing(get_connection()) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS shopping_list_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                item_name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS shopping_list_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                item_name TEXT,
                created_at TEXT NOT NULL
            );
            """
        )

        add_column_if_missing(connection, "shopping_list_items", "chat_id", "INTEGER")
        add_column_if_missing(connection, "shopping_list_items", "added_by_user_id", "INTEGER")
        add_column_if_missing(connection, "shopping_list_items", "added_by_name", "TEXT")
        add_column_if_missing(
            connection,
            "shopping_list_items",
            "status",
            "TEXT NOT NULL DEFAULT 'active'",
        )
        add_column_if_missing(connection, "shopping_list_items", "completed_at", "TEXT")
        add_column_if_missing(
            connection,
            "shopping_list_items",
            "completed_by_user_id",
            "INTEGER",
        )
        add_column_if_missing(
            connection,
            "shopping_list_items",
            "completed_by_name",
            "TEXT",
        )

        add_column_if_missing(connection, "shopping_list_events", "chat_id", "INTEGER")
        add_column_if_missing(connection, "shopping_list_events", "actor_name", "TEXT")
        add_column_if_missing(connection, "shopping_list_events", "item_id", "INTEGER")

        connection.execute(
            """
            UPDATE shopping_list_items
            SET chat_id = user_id
            WHERE chat_id IS NULL
            """
        )
        connection.execute(
            """
            UPDATE shopping_list_items
            SET added_by_user_id = user_id
            WHERE added_by_user_id IS NULL
            """
        )
        connection.execute(
            """
            UPDATE shopping_list_events
            SET chat_id = user_id
            WHERE chat_id IS NULL
            """
        )

        connection.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_shopping_list_items_chat_id_status
            ON shopping_list_items(chat_id, status, id);

            CREATE INDEX IF NOT EXISTS idx_shopping_list_events_chat_id_created_at
            ON shopping_list_events(chat_id, created_at);
            """
        )
        connection.commit()


def get_actor_name(update: Update) -> str:
    user = update.effective_user
    if user.full_name:
        return user.full_name
    if user.username:
        return f"@{user.username}"
    return str(user.id)


def log_event(
    chat_id: int,
    user_id: int,
    actor_name: str,
    event_type: str,
    item_name: str | None = None,
    item_id: int | None = None,
) -> None:
    with closing(get_connection()) as connection:
        connection.execute(
            """
            INSERT INTO shopping_list_events (
                chat_id,
                user_id,
                actor_name,
                event_type,
                item_name,
                item_id,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (chat_id, user_id, actor_name, event_type, item_name, item_id, utc_now_iso()),
        )
        connection.commit()


def add_list_item(chat_id: int, user_id: int, actor_name: str, item_name: str) -> int:
    with closing(get_connection()) as connection:
        cursor = connection.execute(
            """
            INSERT INTO shopping_list_items (
                chat_id,
                user_id,
                added_by_user_id,
                added_by_name,
                item_name,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, 'active', ?)
            """,
            (chat_id, user_id, user_id, actor_name, item_name, utc_now_iso()),
        )
        item_id = cursor.lastrowid
        connection.commit()

    log_event(chat_id, user_id, actor_name, "add", item_name, item_id)
    return item_id


def add_list_items(chat_id: int, user_id: int, actor_name: str, items: list[str]) -> list[int]:
    item_ids = []
    for item_name in items:
        item_ids.append(add_list_item(chat_id, user_id, actor_name, item_name))
    return item_ids


def get_active_items(chat_id: int) -> list[sqlite3.Row]:
    with closing(get_connection()) as connection:
        return connection.execute(
            """
            SELECT id, item_name, added_by_name
            FROM shopping_list_items
            WHERE chat_id = ? AND status = 'active'
            ORDER BY id
            """,
            (chat_id,),
        ).fetchall()


def get_items_by_ids(item_ids: list[int]) -> list[sqlite3.Row]:
    if not item_ids:
        return []

    placeholders = ",".join("?" for _ in item_ids)
    with closing(get_connection()) as connection:
        rows = connection.execute(
            f"""
            SELECT id, chat_id, item_name, status, added_by_name, completed_by_name
            FROM shopping_list_items
            WHERE id IN ({placeholders})
            """,
            item_ids,
        ).fetchall()

    rows_by_id = {row["id"]: row for row in rows}
    return [rows_by_id[item_id] for item_id in item_ids if item_id in rows_by_id]


def complete_item_by_id(
    chat_id: int,
    user_id: int,
    actor_name: str,
    item_id: int,
) -> sqlite3.Row | None:
    with closing(get_connection()) as connection:
        selected_item = connection.execute(
            """
            SELECT id, chat_id, item_name, status
            FROM shopping_list_items
            WHERE id = ?
            """,
            (item_id,),
        ).fetchone()

        if selected_item is None or selected_item["chat_id"] != chat_id:
            return None

        if selected_item["status"] != "active":
            return selected_item

        connection.execute(
            """
            UPDATE shopping_list_items
            SET status = 'bought',
                completed_at = ?,
                completed_by_user_id = ?,
                completed_by_name = ?
            WHERE id = ?
            """,
            (utc_now_iso(), user_id, actor_name, item_id),
        )
        connection.commit()

    log_event(chat_id, user_id, actor_name, "buy", selected_item["item_name"], item_id)
    return get_items_by_ids([item_id])[0]


def complete_item(chat_id: int, user_id: int, actor_name: str, selector: str) -> sqlite3.Row | None:
    items = get_active_items(chat_id)
    selected_item_id = None

    if selector.isdigit():
        index = int(selector) - 1
        if 0 <= index < len(items):
            selected_item_id = items[index]["id"]
    else:
        normalized_selector = selector.casefold()
        for item in items:
            if item["item_name"].casefold() == normalized_selector:
                selected_item_id = item["id"]
                break

    if selected_item_id is None:
        return None

    return complete_item_by_id(chat_id, user_id, actor_name, selected_item_id)


def clear_list_items(chat_id: int, user_id: int, actor_name: str) -> int:
    with closing(get_connection()) as connection:
        active_items = connection.execute(
            """
            SELECT id, item_name
            FROM shopping_list_items
            WHERE chat_id = ? AND status = 'active'
            """,
            (chat_id,),
        ).fetchall()

        if not active_items:
            return 0

        connection.execute(
            """
            UPDATE shopping_list_items
            SET status = 'cleared',
                completed_at = ?,
                completed_by_user_id = ?,
                completed_by_name = ?
            WHERE chat_id = ? AND status = 'active'
            """,
            (utc_now_iso(), user_id, actor_name, chat_id),
        )
        connection.commit()

    for item in active_items:
        log_event(chat_id, user_id, actor_name, "clear_item", item["item_name"], item["id"])

    log_event(chat_id, user_id, actor_name, "clear_list")
    return len(active_items)


def message_mentions_bot(message_text: str | None, bot_username: str | None) -> bool:
    if not message_text or not bot_username:
        return False

    pattern = rf"(?<!\w)@{re.escape(bot_username)}(?!\w)"
    return re.search(pattern, message_text, flags=re.IGNORECASE) is not None


def extract_items_from_text(message_text: str, bot_username: str) -> list[str]:
    mention_pattern = rf"(?<!\w)@{re.escape(bot_username)}(?!\w)"
    text_without_mentions = re.sub(
        mention_pattern,
        "",
        message_text,
        flags=re.IGNORECASE,
    ).strip()

    if not text_without_mentions:
        return []

    raw_lines = [line.strip() for line in text_without_mentions.splitlines() if line.strip()]
    if len(raw_lines) == 1:
        raw_lines = [
            part.strip()
            for part in re.split(r"[;,]", raw_lines[0])
            if part.strip()
        ]

    items = []
    for line in raw_lines:
        normalized = re.sub(r"^\s*(?:[-*•]+|\d+[.)]\s+)", "", line).strip()
        if normalized:
            items.append(normalized)

    return items


def build_checklist_text(rows: list[sqlite3.Row]) -> str:
    if not rows:
        return "Список пуст."

    lines = ["<b>Чеклист покупок</b>"]
    active_count = 0

    for row in rows:
        item_name = html.escape(row["item_name"])
        if row["status"] == "active":
            lines.append(f"⬜ {item_name}")
            active_count += 1
        elif row["status"] == "bought":
            completed_by = html.escape(row["completed_by_name"] or "неизвестно")
            lines.append(f"✅ <s>{item_name}</s> — купил(а) {completed_by}")
        else:
            lines.append(f"➖ <s>{item_name}</s>")

    if active_count == 0:
        lines.append("")
        lines.append("Все позиции из этого чеклиста уже обработаны.")

    return "\n".join(lines)


def build_checklist_keyboard(rows: list[sqlite3.Row]) -> InlineKeyboardMarkup | None:
    buttons = []
    for row in rows:
        if row["status"] != "active":
            continue

        label = row["item_name"]
        if len(label) > 40:
            label = f"{label[:37]}..."
        buttons.append(
            [InlineKeyboardButton(f"Куплено: {label}", callback_data=f"buy:{row['id']}")]
        )

    if not buttons:
        return None

    return InlineKeyboardMarkup(buttons)


def get_checklist_store(application: Application) -> dict[str, dict[str, list[int]]]:
    return application.bot_data.setdefault(CHECKLIST_KEY, {})


def checklist_store_key(chat_id: int, message_id: int) -> str:
    return f"{chat_id}:{message_id}"


async def send_checklist(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    item_ids: list[int] | None = None,
) -> None:
    chat_id = update.effective_chat.id
    if item_ids is None:
        item_ids = [row["id"] for row in get_active_items(chat_id)]

    rows = get_items_by_ids(item_ids)
    text = build_checklist_text(rows)
    keyboard = build_checklist_keyboard(rows)
    sent_message = await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )

    checklist_store = get_checklist_store(context.application)
    checklist_store[checklist_store_key(chat_id, sent_message.message_id)] = {
        "item_ids": item_ids,
    }


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    actor_name = get_actor_name(update)
    log_event(chat_id, user_id, actor_name, "start")

    await update.message.reply_text(
        "Добро пожаловать! Список общий для всего чата.\n"
        "/add item - добавить товар\n"
        "/list - показать активный список\n"
        "/buy 2 - отметить товар купленным по номеру\n"
        "/clear - очистить активный список\n"
        "\n"
        "Новый режим:\n"
        "Если отметить бота и написать список, я добавлю все позиции.\n"
        "Если просто отметить бота без текста, пришлю чеклист с кнопками."
    )


async def add_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    actor_name = get_actor_name(update)
    item = " ".join(context.args).strip()

    if not item:
        await update.message.reply_text("Укажите товар: /add название")
        return

    add_list_item(chat_id, user_id, actor_name, item)
    await update.message.reply_text(f"{actor_name} добавил(а): {item}")


async def show_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    actor_name = get_actor_name(update)
    items = get_active_items(chat_id)
    log_event(chat_id, user_id, actor_name, "list_view")

    if items:
        lines = [
            f"{index}. {item['item_name']} — добавил(а) {item['added_by_name'] or 'неизвестно'}"
            for index, item in enumerate(items, start=1)
        ]
        text = "Общий список покупок:\n" + "\n".join(lines)
    else:
        text = "Список пуст"

    await update.message.reply_text(text)


async def buy_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    actor_name = get_actor_name(update)
    selector = " ".join(context.args).strip()

    if not selector:
        await update.message.reply_text("Укажите номер или название товара: /buy 2")
        return

    selected_item = complete_item(chat_id, user_id, actor_name, selector)
    if selected_item is None:
        await update.message.reply_text(
            "Не удалось найти товар. Используйте номер из /list или точное название."
        )
        return

    if selected_item["status"] != "bought":
        await update.message.reply_text("Этот товар уже не находится в активном списке.")
        return

    await update.message.reply_text(f"{actor_name} купил(а): {selected_item['item_name']}")


async def clear_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    actor_name = get_actor_name(update)
    cleared_count = clear_list_items(chat_id, user_id, actor_name)

    if cleared_count:
        await update.message.reply_text(
            f"{actor_name} очистил(а) список. Убрано позиций: {cleared_count}"
        )
    else:
        await update.message.reply_text("Список уже был пуст")


async def handle_bot_mention(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None:
        return

    bot_username = context.bot.username
    if not message_mentions_bot(update.message.text, bot_username):
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    actor_name = get_actor_name(update)
    items = extract_items_from_text(update.message.text, bot_username)

    if not items:
        log_event(chat_id, user_id, actor_name, "checklist_requested")
        await send_checklist(update, context)
        return

    add_list_items(chat_id, user_id, actor_name, items)
    log_event(chat_id, user_id, actor_name, "bulk_add", ", ".join(items))
    await update.message.reply_text(
        "Добавил в общий список:\n" + "\n".join(f"• {item}" for item in items)
    )


async def handle_checklist_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    if query is None or query.message is None or query.data is None:
        return

    await query.answer()

    if not query.data.startswith("buy:"):
        return

    try:
        item_id = int(query.data.split(":", maxsplit=1)[1])
    except ValueError:
        await query.answer("Не удалось распознать товар.", show_alert=True)
        return

    chat_id = query.message.chat_id
    user_id = query.from_user.id
    actor_name = query.from_user.full_name or query.from_user.username or str(user_id)

    updated_item = complete_item_by_id(chat_id, user_id, actor_name, item_id)
    if updated_item is None:
        await query.answer("Этот чеклист устарел.", show_alert=True)
        return

    checklist_store = get_checklist_store(context.application)
    store_key = checklist_store_key(chat_id, query.message.message_id)
    checklist_data = checklist_store.get(store_key)
    if checklist_data is None:
        checklist_data = {"item_ids": [item_id]}

    item_ids = checklist_data["item_ids"]
    if item_id not in item_ids:
        item_ids.append(item_id)

    rows = get_items_by_ids(item_ids)
    text = build_checklist_text(rows)
    keyboard = build_checklist_keyboard(rows)

    await query.edit_message_text(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


def main() -> None:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
    if bot_token == "YOUR_BOT_TOKEN":
        raise RuntimeError(
            "Укажите токен бота в переменной окружения TELEGRAM_BOT_TOKEN."
        )

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    init_db()
    logger.info("Using database at %s", DB_PATH)

    app = Application.builder().token(bot_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_item))
    app.add_handler(CommandHandler("list", show_list))
    app.add_handler(CommandHandler("buy", buy_item))
    app.add_handler(CommandHandler("clear", clear_list))
    app.add_handler(CallbackQueryHandler(handle_checklist_callback, pattern=r"^buy:\d+$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_bot_mention))
    app.run_polling()


if __name__ == "__main__":
    main()
