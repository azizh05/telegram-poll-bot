
# =========================
# TELEGRAM ADVANCED POLL BOT
# Production Single File
# =========================

import asyncio
import sqlite3
import csv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# ---------------- CONFIG ----------------

BOT_TOKEN = "PUT_YOUR_BOT_TOKEN_HERE"   # Replace before running
DB_FILE = "polls.db"

# ---------------- DATABASE ----------------

db = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS polls (
    poll_id TEXT PRIMARY KEY,
    chat_id INTEGER,
    message_id INTEGER,
    question TEXT,
    options TEXT,
    votes TEXT,
    open INTEGER,
    multi INTEGER,
    anonymous INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS votes (
    poll_id TEXT,
    user_id INTEGER,
    username TEXT,
    option INTEGER,
    PRIMARY KEY (poll_id, user_id, option)
)
""")

db.commit()

# ---------------- HELPERS ----------------

async def is_admin(update):
    member = await update.effective_chat.get_member(update.effective_user.id)
    return member.status in ("administrator", "creator")

# ---------------- CREATE POLL ----------------

async def create_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        await update.message.reply_text("⛔ Only admins can create polls.")
        return

    args = context.args
    if len(args) < 6:
        await update.message.reply_text(
            'Usage:\n/poll "Question" "A" "B" "C" 60 single public'
        )
        return

    question = args[0]
    options = args[1:-3]
    duration = int(args[-3])
    multi = 1 if args[-2].lower() == "multi" else 0
    anonymous = 1 if args[-1].lower() == "anonymous" else 0

    poll_id = f"{update.effective_chat.id}:{update.message.id}"
    votes = [0] * len(options)

    cursor.execute(
        "INSERT INTO polls VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (poll_id, update.effective_chat.id, 0, question,
         "|".join(options), "|".join(map(str, votes)), 1, multi, anonymous)
    )
    db.commit()

    keyboard = [[InlineKeyboardButton(opt, callback_data=f"{poll_id}:{i}")] for i, opt in enumerate(options)]

    msg = await update.message.reply_text(
        f"📊 *{question}*\n\n"
        f"{'👤 Public voting (everyone sees voters)' if not anonymous else '🕶 Anonymous voting'}\n"
        f"{'☑ Multiple choice' if multi else '🔘 Single choice'}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

    cursor.execute("UPDATE polls SET message_id=? WHERE poll_id=?", (msg.message_id, poll_id))
    db.commit()

    asyncio.create_task(close_poll_later(poll_id, duration, context))

# ---------------- HANDLE VOTE ----------------

async def handle_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    poll_id, option_index = query.data.rsplit(":", 1)
    option_index = int(option_index)

    cursor.execute("SELECT * FROM polls WHERE poll_id=?", (poll_id,))
    poll = cursor.fetchone()

    if not poll or poll[6] == 0:
        await query.answer("⛔ Poll closed", show_alert=True)
        return

    _, chat_id, msg_id, question, options, votes, open_, multi, anonymous = poll
    options = options.split("|")
    votes = list(map(int, votes.split("|")))

    user = query.from_user

    cursor.execute("SELECT * FROM votes WHERE poll_id=? AND user_id=?", (poll_id, user.id))
    existing = cursor.fetchall()

    if existing and not multi:
        await query.answer("You already voted!", show_alert=True)
        return

    cursor.execute(
        "INSERT OR IGNORE INTO votes VALUES (?, ?, ?, ?)",
        (poll_id, user.id, user.username or user.first_name, option_index)
    )
    votes[option_index] += 1

    cursor.execute("UPDATE polls SET votes=? WHERE poll_id=?", ("|".join(map(str, votes)), poll_id))
    db.commit()

    await update_poll_display(poll_id, context)

# ---------------- DISPLAY UPDATE ----------------

async def update_poll_display(poll_id, context):
    cursor.execute("SELECT * FROM polls WHERE poll_id=?", (poll_id,))
    poll = cursor.fetchone()

    _, chat_id, msg_id, question, options, votes, open_, multi, anonymous = poll
    options = options.split("|")
    votes = list(map(int, votes.split("|")))
    total = sum(votes)

    lines = [f"📊 *{question}*\n"]

    for i, opt in enumerate(options):
        count = votes[i]
        percent = (count / total * 100) if total else 0
        bar = "█" * int(percent // 5)
        lines.append(f"{opt}\n{bar} {count} ({percent:.0f}%)\n")

        if not anonymous:
            cursor.execute("SELECT username FROM votes WHERE poll_id=? AND option=?", (poll_id, i))
            names = [r[0] for r in cursor.fetchall()]
            if names:
                lines.append("👥 " + ", ".join(names) + "\n")

    lines.append(f"🗳 Total votes: {total}")

    if not open_:
        lines.append("\n⛔ Poll closed")

    keyboard = None
    if open_:
        keyboard = [[InlineKeyboardButton(opt, callback_data=f"{poll_id}:{i}")] for i, opt in enumerate(options)]

    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=msg_id,
        text="\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
        parse_mode="Markdown"
    )

# ---------------- AUTO CLOSE ----------------

async def close_poll_later(poll_id, delay, context):
    await asyncio.sleep(delay)
    cursor.execute("UPDATE polls SET open=0 WHERE poll_id=?", (poll_id,))
    db.commit()
    await update_poll_display(poll_id, context)

# ---------------- MANUAL CLOSE ----------------

async def close_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to the poll to close it.")
        return

    poll_id = f"{update.effective_chat.id}:{update.message.reply_to_message.message_id}"

    cursor.execute("UPDATE polls SET open=0 WHERE poll_id=?", (poll_id,))
    db.commit()

    await update_poll_display(poll_id, context)
    await update.message.reply_text("✅ Poll closed.")

# ---------------- START BOT ----------------

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("poll", create_poll))
    app.add_handler(CommandHandler("closepoll", close_poll))
    app.add_handler(CallbackQueryHandler(handle_vote))

    print("Advanced Poll Bot running...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
