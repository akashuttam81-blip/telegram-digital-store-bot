import telebot
import sqlite3
from telebot import types

TOKEN = "8271855633:AAHAZlj8kP-mF22EFIvPFHCdITwRzbW0B4c"
ADMIN_ID = 7662708655  # apna telegram id
QR_IMAGE = "qr.png"  # yahan apna fixed QR image rakhein

bot = telebot.TeleBot(TOKEN)

conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()

# ================= DATABASE =================

cursor.execute("""CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY
)""")

cursor.execute("""CREATE TABLE IF NOT EXISTS coupons(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    amount INTEGER,
    code TEXT
)""")

cursor.execute("""CREATE TABLE IF NOT EXISTS settings(
    amount INTEGER PRIMARY KEY,
    price INTEGER
)""")

cursor.execute("""CREATE TABLE IF NOT EXISTS payments(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount INTEGER,
    qty INTEGER,
    utr TEXT UNIQUE,
    status TEXT
)""")

conn.commit()

# Default prices
cursor.execute("INSERT OR IGNORE INTO settings VALUES(500,20)")
cursor.execute("INSERT OR IGNORE INTO settings VALUES(1000,110)")
conn.commit()


# ================= START =================

@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    cursor.execute("INSERT OR IGNORE INTO users VALUES(?)",(user_id,))
    conn.commit()

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("₹500 Coupon","₹1000 Coupon")
    markup.add("Stock")

    if user_id == ADMIN_ID:
        markup.add("Admin Panel")

    bot.send_message(user_id,"Select option:",reply_markup=markup)


# ================= STOCK =================

@bot.message_handler(func=lambda m: m.text=="Stock")
def stock(message):
    cursor.execute("SELECT COUNT(*) FROM coupons WHERE amount=500")
    s500 = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM coupons WHERE amount=1000")
    s1000 = cursor.fetchone()[0]

    bot.reply_to(message,f"📦 Stock\n500₹ = {s500}\n1000₹ = {s1000}")


# ================= BUY =================

@bot.message_handler(func=lambda m: m.text in ["₹500 Coupon","₹1000 Coupon"])
def buy_coupon(message):
    amount = 500 if "500" in message.text else 1000
    bot.send_message(message.chat.id,"Quantity bhejein (number)")
    bot.register_next_step_handler(message,process_qty,amount)


def process_qty(message,amount):
    try:
        qty = int(message.text)

        cursor.execute("SELECT price FROM settings WHERE amount=?",(amount,))
        price = cursor.fetchone()[0]

        total = price * qty

        bot.send_message(message.chat.id,f"Total Payment: ₹{total}\nQR scan karein aur UTR bhejein.")
        bot.send_photo(message.chat.id,open(QR_IMAGE,"rb"))

        bot.register_next_step_handler(message,process_utr,amount,qty)

    except:
        bot.send_message(message.chat.id,"Invalid quantity")


def process_utr(message,amount,qty):
    utr = message.text
    user_id = message.from_user.id

    try:
        cursor.execute("INSERT INTO payments(user_id,amount,qty,utr,status) VALUES(?,?,?,?,?)",
                       (user_id,amount,qty,utr,"pending"))
        conn.commit()

        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ Confirm",callback_data="approve_"+utr),
            types.InlineKeyboardButton("❌ Wrong",callback_data="reject_"+utr)
        )

        bot.send_message(ADMIN_ID,
            f"New Payment\nUser:{user_id}\nAmount:{amount}\nQty:{qty}\nUTR:{utr}",
            reply_markup=markup)

        bot.send_message(user_id,"⏳ Payment Pending Admin Approval")

    except:
        bot.send_message(user_id,"❌ Duplicate UTR Blocked")


# ================= ADMIN CALLBACK =================

@bot.callback_query_handler(func=lambda call: True)
def callback(call):

    if call.from_user.id != ADMIN_ID:
        return

    action, utr = call.data.split("_")

    cursor.execute("SELECT user_id,amount,qty FROM payments WHERE utr=? AND status='pending'",(utr,))
    data = cursor.fetchone()

    if not data:
        return

    user_id,amount,qty = data

    if action=="approve":

        cursor.execute("SELECT id,code FROM coupons WHERE amount=? LIMIT ?",(amount,qty))
        coupons = cursor.fetchall()

        if len(coupons) < qty:
            bot.send_message(user_id,"❌ Out Of Stock")
            return

        codes = ""
        for c in coupons:
            codes += c[1]+"\n"
            cursor.execute("DELETE FROM coupons WHERE id=?",(c[0],))

        cursor.execute("UPDATE payments SET status='approved' WHERE utr=?",(utr,))
        conn.commit()

        bot.send_message(user_id,f"✅ Payment Approved\nYour Coupons:\n{codes}")

    elif action=="reject":
        cursor.execute("UPDATE payments SET status='rejected' WHERE utr=?",(utr,))
        conn.commit()
        bot.send_message(user_id,"❌ Payment Marked Wrong")

    bot.answer_callback_query(call.id,"Done")


# ================= ADMIN PANEL =================

@bot.message_handler(func=lambda m: m.text=="Admin Panel")
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        return

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("Add Coupon","Set Price")
    markup.add("Users Count","Broadcast")
    markup.add("Back")

    bot.send_message(message.chat.id,"Admin Panel:",reply_markup=markup)


# Add Coupon
@bot.message_handler(func=lambda m: m.text=="Add Coupon")
def add_coupon(message):
    bot.send_message(message.chat.id,"Format:\namount code\nExample:\n500 ABCD123")
    bot.register_next_step_handler(message,save_coupon)


def save_coupon(message):
    try:
        amount,code = message.text.split()
        cursor.execute("INSERT INTO coupons(amount,code) VALUES(?,?)",(int(amount),code))
        conn.commit()
        bot.send_message(message.chat.id,"✅ Coupon Added")
    except:
        bot.send_message(message.chat.id,"Invalid format")


# Set Price
@bot.message_handler(func=lambda m: m.text=="Set Price")
def set_price(message):
    bot.send_message(message.chat.id,"Format:\namount price\nExample:\n500 25")
    bot.register_next_step_handler(message,save_price)


def save_price(message):
    try:
        amount,price = message.text.split()
        cursor.execute("UPDATE settings SET price=? WHERE amount=?",(int(price),int(amount)))
        conn.commit()
        bot.send_message(message.chat.id,"✅ Price Updated")
    except:
        bot.send_message(message.chat.id,"Invalid format")


# Users Count
@bot.message_handler(func=lambda m: m.text=="Users Count")
def users_count(message):
    if message.from_user.id==ADMIN_ID:
        cursor.execute("SELECT COUNT(*) FROM users")
        total = cursor.fetchone()[0]
        bot.send_message(message.chat.id,f"Total Users: {total}")


# Broadcast
@bot.message_handler(func=lambda m: m.text=="Broadcast")
def broadcast(message):
    bot.send_message(message.chat.id,"Send broadcast message")
    bot.register_next_step_handler(message,send_broadcast)


def send_broadcast(message):
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()

    for u in users:
        try:
            bot.send_message(u[0],message.text)
        except:
            pass

    bot.send_message(message.chat.id,"✅ Broadcast Sent")


print("Pro Coupon Bot Running...")
bot.polling()
