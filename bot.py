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
from flask import Flask
from threading import Thread

app_web = Flask('')

@app_web.route('/')
def home():
    return "Bot is running!"

def run():
    app_web.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

BOT_TOKEN = "8271855633:AAHAZlj8kP-mF22EFIvPFHCdITwRzbW0B4c"
ADMIN_ID = 7662708655

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

    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
        (user_id,)
    )
    conn.commit()

    # ADMIN PANEL
    if user_id == ADMIN_ID:

        keyboard = [
            [InlineKeyboardButton("➕ Add Product", callback_data="add_product")],
            [InlineKeyboardButton("➕ Add Coupons", callback_data="add_coupon")],
            [InlineKeyboardButton("➖ Delete Coupon", callback_data="delete_coupon")],
            [InlineKeyboardButton("🗑 Delete Product", callback_data="delete_product")],
            [InlineKeyboardButton("📦 View Products", callback_data="view_products")],
            [InlineKeyboardButton("📊 Pending Orders", callback_data="pending")],
            [InlineKeyboardButton("📈 Sales", callback_data="sales")],
            [InlineKeyboardButton("👥 Users", callback_data="users")],
            [InlineKeyboardButton("💬 Support", callback_data="support")]
            [InlineKeyboardButton("📥 Bulk Coupons", callback_data="bulk_coupon")],
        ]

        await update.message.reply_text(
            "👑 ADMIN PANEL",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # USER SIDE
    else:

        cursor.execute("SELECT * FROM products")
        products = cursor.fetchall()

        keyboard = []

        for p in products:

            cursor.execute(
                "SELECT COUNT(*) FROM coupons WHERE product_id=? AND used=0",
                (p[0],)
            )

            stock = cursor.fetchone()[0]

            if stock > 0:
                keyboard.append([
                    InlineKeyboardButton(
                        f"{p[1]} - ₹{p[2]} ({stock} left)",
                        callback_data=f"buy_{p[0]}"
                    )
                ])

        if not keyboard:
            await update.message.reply_text("❌ Out Of Stock")
            return

        await update.message.reply_text(
            "🛍 Select Product:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

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
        await update.message.reply_text("❌ Out Of Stock")
        return

    await update.message.reply_text("🛍 Select Product:",
        reply_markup=InlineKeyboardMarkup(keyboard))

# ================= BUTTON HANDLER ================= #

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id

    # ---------------- SUPPORT ----------------
    if data == "support":
        context.user_data.clear()
        context.user_data["support_mode"] = True

        await query.message.reply_text(
            "💬 Send your problem. Our support team will reply soon."
        )

    # ---------------- BULK COUPON ----------------
    elif data == "bulk_coupon" and user_id == ADMIN_ID:
        context.user_data["bulk_coupon"] = True
        await query.message.reply_text(
            "Send ProductID then coupon codes.\n\nExample:\n\n1\nCODE1\nCODE2\nCODE3"
        )

    # ---------------- BUY PRODUCT ----------------
    elif data.startswith("buy_"):

        pid = int(data.split("_")[1])

        cursor.execute(
            "SELECT COUNT(*) FROM coupons WHERE product_id=? AND used=0",
            (pid,)
        )

        stock = cursor.fetchone()[0]

        if stock == 0:
            await query.message.reply_text("❌ Out Of Stock")
            return

        context.user_data["product_id"] = pid

        qty_buttons = [1, 2, 5, 10]
        buttons = []

        available = [
            InlineKeyboardButton(str(q), callback_data=f"qty_{q}")
            for q in qty_buttons if q <= stock
        ]

        for i in range(0, len(available), 2):
            buttons.append(available[i:i+2])

        await query.message.reply_text(
            f"Available Stock: {stock}\n\nSelect Quantity:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    # ---------------- SELECT QUANTITY ----------------
    elif data.startswith("qty_"):

        qty = int(data.split("_")[1])
        pid = context.user_data.get("product_id")

        cursor.execute(
            "SELECT COUNT(*) FROM coupons WHERE product_id=? AND used=0",
            (pid,)
        )

        stock = cursor.fetchone()[0]

        if qty > stock:
            await query.message.reply_text("❌ Stock changed. Try again.")
            return

        cursor.execute("SELECT price FROM products WHERE id=?", (pid,))
        price = cursor.fetchone()[0]

        total = price * qty

        context.user_data["quantity"] = qty
        context.user_data["total"] = total
        context.user_data["awaiting_utr"] = True

        await context.bot.send_photo(
            chat_id=user_id,
            photo=open("qr.jpg", "rb"),
            caption=f"💰 Total: ₹{total}\n\n📲 Scan QR & Pay\n\nSend 12 digit UTR."
        )

    # ---------------- ADMIN PANEL ----------------
    elif user_id == ADMIN_ID:

        if data == "add_product":
            context.user_data["adding_product"] = True
            await query.message.reply_text("Send: ProductName - Price")

        elif data == "add_coupon":
            context.user_data["adding_coupon"] = True
            await query.message.reply_text("Send: ProductID CODE")

        elif data == "delete_coupon":
            context.user_data["deleting_coupon"] = True
            await query.message.reply_text("Send Coupon Code")

        elif data == "delete_product":
            context.user_data["deleting_product"] = True
            await query.message.reply_text("Send Product ID")

        elif data == "view_products":

            cursor.execute("SELECT * FROM products")
            products = cursor.fetchall()

            text = "📦 Products:\n\n"

            for p in products:

                cursor.execute(
                    "SELECT COUNT(*) FROM coupons WHERE product_id=? AND used=0",
                    (p[0],)
                )

                stock = cursor.fetchone()[0]

                text += f"{p[0]}. {p[1]} | ₹{p[2]} | Stock: {stock}\n"

            await query.message.reply_text(text)

        elif data == "pending":

            cursor.execute("SELECT * FROM orders WHERE status='pending'")
            orders = cursor.fetchall()

            if not orders:
                await query.message.reply_text("No Pending Orders")
                return

            for o in orders:

                keyboard = [[
                    InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_{o[0]}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"reject_{o[0]}")
                ]]

                await query.message.reply_text(
                    f"OrderID: {o[0]}\nUser: {o[1]}\nUTR: {o[5]}\nTotal: ₹{o[4]}",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

        elif data.startswith("confirm_"):

            oid = int(data.split("_")[1])

            cursor.execute("SELECT * FROM orders WHERE id=?", (oid,))
            order = cursor.fetchone()

            pid = order[2]
            qty = order[3]
            user = order[1]

            cursor.execute(
                "SELECT id, code FROM coupons WHERE product_id=? AND used=0 LIMIT ?",
                (pid, qty)
            )

            coupons = cursor.fetchall()

            codes = []

            for c in coupons:
                cursor.execute("UPDATE coupons SET used=1 WHERE id=?", (c[0],))
                codes.append(c[1])

            cursor.execute(
                "UPDATE orders SET status='confirmed' WHERE id=?",
                (oid,)
            )

            conn.commit()

            await context.bot.send_message(
                user,
                "🎉 Payment Confirmed!\n\nYour Coupons:\n\n" + "\n".join(codes)
            )

            await query.message.reply_text("✅ Delivered")

        elif data.startswith("reject_"):

            oid = int(data.split("_")[1])

            cursor.execute(
                "UPDATE orders SET status='rejected' WHERE id=?",
                (oid,)
            )

            conn.commit()

            await query.message.reply_text("❌ Rejected")

        elif data == "sales":

            cursor.execute(
                "SELECT COUNT(*), SUM(total) FROM orders WHERE status='confirmed'"
            )

            count, total = cursor.fetchone()

            await query.message.reply_text(
                f"📊 Orders: {count}\nRevenue: ₹{total if total else 0}"
            )

        elif data == "users":

            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]

            await query.message.reply_text(
                f"👥 Total Users: {total_users}"
            )

# ================= TEXT HANDLER ================= #

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id
    text = update.message.text.strip()

    # ================= SUPPORT =================

    if context.user_data.get("support_mode"):

        await context.bot.send_message(
            ADMIN_ID,
            f"📩 Support Request\n\nUser: {user_id}\n\nMessage:\n{text}"
        )

        context.user_data.clear()

        await update.message.reply_text(
            "✅ Your message has been sent to support."
        )

        return

    # ================= ADD PRODUCT =================

    if context.user_data.get("adding_product") and user_id == ADMIN_ID:

        try:
            name, price = text.split("-")

            cursor.execute(
                "INSERT INTO products (name, price) VALUES (?, ?)",
                (name.strip(), int(price.strip()))
            )

            conn.commit()
            context.user_data.clear()

            await update.message.reply_text("✅ Product Added")

        except:
            await update.message.reply_text("❌ Format: ProductName - Price")

        return

    # ================= ADD COUPON =================

    elif context.user_data.get("adding_coupon") and user_id == ADMIN_ID:

        try:
            pid, code = text.split()

            cursor.execute(
                "INSERT INTO coupons (product_id, code) VALUES (?, ?)",
                (int(pid), code)
            )

            conn.commit()
            context.user_data.clear()

            await update.message.reply_text("✅ Coupon Added")

        except:
            await update.message.reply_text("❌ Format: ProductID CODE")

        return

    # ================= BULK COUPON =================

    elif context.user_data.get("bulk_coupon") and user_id == ADMIN_ID:

        lines = text.split("\n")

        product_id = int(lines[0])
        codes = lines[1:]

        added = 0

        for code in codes:
            try:
                cursor.execute(
                    "INSERT INTO coupons (product_id, code) VALUES (?, ?)",
                    (product_id, code.strip())
                )
                added += 1
            except:
                pass

        conn.commit()
        context.user_data.clear()

        await update.message.reply_text(f"✅ {added} Coupons Added Successfully")

        return

    # ================= DELETE COUPON =================

    elif context.user_data.get("deleting_coupon") and user_id == ADMIN_ID:

        cursor.execute(
            "DELETE FROM coupons WHERE code=?",
            (text,)
        )

        conn.commit()
        context.user_data.clear()

        await update.message.reply_text("🗑 Coupon Deleted")

        return

    # ================= DELETE PRODUCT =================

    elif context.user_data.get("deleting_product") and user_id == ADMIN_ID:

        cursor.execute(
            "DELETE FROM products WHERE id=?",
            (int(text),)
        )

        conn.commit()
        context.user_data.clear()

        await update.message.reply_text("🗑 Product Deleted")

        return

    # ================= USER UTR PAYMENT =================

    elif context.user_data.get("awaiting_utr"):

        if not re.fullmatch(r"\d{12}", text):

            await update.message.reply_text("❌ Send valid 12 digit UTR")

            return

        cursor.execute(
            "SELECT id FROM orders WHERE utr=?",
            (text,)
        )

        if cursor.fetchone():

            await update.message.reply_text("❌ UTR already used")

            return

        pid = context.user_data.get("product_id")
        qty = context.user_data.get("quantity")
        total = context.user_data.get("total")

        cursor.execute("""
        INSERT INTO orders (user_id, product_id, quantity, total, utr, screenshot, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            pid,
            qty,
            total,
            text,
            "no_screenshot",
            "pending"
        ))

        conn.commit()
        context.user_data.clear()

        await update.message.reply_text(
            "✅ Payment Submitted.\n⏳ Waiting for admin approval."
        )

        await context.bot.send_message(
            ADMIN_ID,
            f"🆕 New Order\nUser: {user_id}\nUTR: {text}\nAmount: ₹{total}"
    )

# ================= RUN ================= #

app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))


keep_alive()
app.run_polling()

