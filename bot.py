import sqlite3
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

BOT_TOKEN = "8271855633:AAHAZlj8kP-mF22EFIvPFHCdITwRzbW0B4c"
ADMIN_ID = 7662708655  # <-- Apni Telegram numeric ID

# ================= DATABASE ================= #

conn = sqlite3.connect("store.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    price INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS coupons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER,
    code TEXT UNIQUE,
    used INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    product_id INTEGER,
    quantity INTEGER,
    total INTEGER,
    utr TEXT UNIQUE,
    screenshot TEXT UNIQUE,
    status TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER UNIQUE
)
""")

conn.commit()

# ================= START ================= #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()

    if user_id == ADMIN_ID:
        keyboard = [
            [InlineKeyboardButton("➕ Add Product", callback_data="add_product")],
            [InlineKeyboardButton("➕ Add Coupons", callback_data="add_coupon")],
            [InlineKeyboardButton("📦 View Products", callback_data="view_products")],
            [InlineKeyboardButton("📊 Pending Orders", callback_data="pending")],
            [InlineKeyboardButton("📈 Sales", callback_data="sales")],
            [InlineKeyboardButton("👥 Users", callback_data="users")]
        ]
        await update.message.reply_text("👑 Admin Panel",
            reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await show_products(update)

# ================= SHOW PRODUCTS ================= #

async def show_products(update):
    cursor.execute("SELECT * FROM products")
    products = cursor.fetchall()

    keyboard = []

    for p in products:
        cursor.execute("SELECT COUNT(*) FROM coupons WHERE product_id=? AND used=0", (p[0],))
        stock = cursor.fetchone()[0]

        if stock > 0:
            keyboard.append([
                InlineKeyboardButton(
                    f"{p[1]} - ₹{p[2]} ({stock} left)",
                    callback_data=f"buy_{p[0]}"
                )
            ])

    if not keyboard:
        await update.message.reply_text("❌ Out of Stock")
        return

    await update.message.reply_text("🛍 Select Product:",
        reply_markup=InlineKeyboardMarkup(keyboard))

# ================= BUTTON HANDLER ================= #

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    # ---------------- BUY ---------------- #
    if data.startswith("buy_"):
        pid = int(data.split("_")[1])
        context.user_data["product_id"] = pid

        keyboard = [
            [InlineKeyboardButton("1", callback_data="qty_1"),
             InlineKeyboardButton("2", callback_data="qty_2"),
             InlineKeyboardButton("5", callback_data="qty_5")]
        ]

        await query.message.reply_text("Select Quantity:",
            reply_markup=InlineKeyboardMarkup(keyboard))

    # ---------------- QUANTITY ---------------- #
    elif data.startswith("qty_"):
        qty = int(data.split("_")[1])
        context.user_data["quantity"] = qty

        pid = context.user_data["product_id"]
        cursor.execute("SELECT price FROM products WHERE id=?", (pid,))
        price = cursor.fetchone()[0]

        total = price * qty
        context.user_data["total"] = total

        await context.bot.send_photo(
            chat_id=user_id,
            photo=open("qr.jpg", "rb"),
            caption=f"💰 Total Amount: ₹{total}\n\n📲 Scan QR and Pay\n\nPayment ke baad 12 digit UTR bhejo."
        )

    # ---------------- ADMIN VIEW ---------------- #
    elif data == "view_products" and user_id == ADMIN_ID:
        cursor.execute("SELECT * FROM products")
        products = cursor.fetchall()
        text = "📦 Products:\n\n"
        for p in products:
            cursor.execute("SELECT COUNT(*) FROM coupons WHERE product_id=? AND used=0", (p[0],))
            stock = cursor.fetchone()[0]
            text += f"{p[0]}. {p[1]} | ₹{p[2]} | Stock: {stock}\n"
        await query.message.reply_text(text)

    # ---------------- SALES ---------------- #
    elif data == "sales" and user_id == ADMIN_ID:
        cursor.execute("SELECT COUNT(*), SUM(total) FROM orders WHERE status='confirmed'")
        count, total = cursor.fetchone()
        await query.message.reply_text(
            f"📊 Sales Report\nOrders: {count}\nRevenue: ₹{total if total else 0}"
        )

    # ---------------- USERS ---------------- #
    elif data == "users" and user_id == ADMIN_ID:
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        await query.message.reply_text(f"👥 Total Users: {total_users}")

    # ---------------- PENDING ---------------- #
    elif data == "pending" and user_id == ADMIN_ID:
        cursor.execute("SELECT * FROM orders WHERE status='pending'")
        orders = cursor.fetchall()

        if not orders:
            await query.message.reply_text("No Pending Orders")
            return

        for o in orders:
            keyboard = [
                [InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_{o[0]}"),
                 InlineKeyboardButton("❌ Reject", callback_data=f"reject_{o[0]}")]
            ]
            await query.message.reply_text(
                f"OrderID: {o[0]}\nUTR: {o[5]}\nTotal: ₹{o[4]}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    # ---------------- CONFIRM ---------------- #
    elif data.startswith("confirm_") and user_id == ADMIN_ID:
        oid = int(data.split("_")[1])

        cursor.execute("SELECT * FROM orders WHERE id=?", (oid,))
        order = cursor.fetchone()

        pid = order[2]
        qty = order[3]
        user = order[1]

        cursor.execute("SELECT id, code FROM coupons WHERE product_id=? AND used=0 LIMIT ?",
                       (pid, qty))
        coupons = cursor.fetchall()

        if len(coupons) < qty:
            await query.message.reply_text("❌ Not enough coupons")
            return

        codes = []
        for c in coupons:
            cursor.execute("UPDATE coupons SET used=1 WHERE id=?", (c[0],))
            codes.append(c[1])

        cursor.execute("UPDATE orders SET status='confirmed' WHERE id=?", (oid,))
        conn.commit()

        await context.bot.send_message(user,
            "🎉 Payment Confirmed!\n\nYour Coupons:\n\n" + "\n".join(codes))

        await query.message.reply_text("✅ Delivered Successfully")

    # ---------------- REJECT ---------------- #
    elif data.startswith("reject_") and user_id == ADMIN_ID:
        oid = int(data.split("_")[1])
        cursor.execute("UPDATE orders SET status='rejected' WHERE id=?", (oid,))
        conn.commit()
        await query.message.reply_text("❌ Order Rejected")

# ================= TEXT HANDLER ================= #

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if re.fullmatch(r"\d{12}", text):
        context.user_data["utr"] = text
        await update.message.reply_text("📸 Screenshot bhejo")
    else:
        await update.message.reply_text("❌ Invalid Input")

# ================= PHOTO HANDLER ================= #

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    utr = context.user_data.get("utr")
    pid = context.user_data.get("product_id")
    qty = context.user_data.get("quantity")
    total = context.user_data.get("total")

    if not utr or not pid:
        return

    file_id = update.message.photo[-1].file_id

    try:
        cursor.execute("""
        INSERT INTO orders (user_id, product_id, quantity, total, utr, screenshot, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, pid, qty, total, utr, file_id, "pending"))
        conn.commit()

        await update.message.reply_text("✅ Order Sent For Verification")

        await context.bot.send_message(ADMIN_ID,
            f"🆕 New Order\nUser: {user_id}\nUTR: {utr}")

    except sqlite3.IntegrityError:
        await update.message.reply_text("❌ Duplicate UTR or Screenshot")

# ================= RUN ================= #

app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
app.add_handler(MessageHandler(filters.PHOTO, photo_handler))

app.run_polling()
