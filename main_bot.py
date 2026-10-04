import os
import io
import threading
import urllib.parse
from flask import Flask
import telebot
from telebot import types

# --- Flask Server Setup for Render Health Checks ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive and running 24/7 on Render!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# --- Bot Tokens ---
USER_BOT_TOKEN = "8965574767:AAHmB1pigzewZew01Qwp9DtoiInu3uPSHnI"
ADMIN_BOT_TOKEN = "8865341663:AAHs7uNhBBB3kY0pnmD7gOjXx038WFkJjaA"

user_bot = telebot.TeleBot(USER_BOT_TOKEN)
admin_bot = telebot.TeleBot(ADMIN_BOT_TOKEN)

# --- In-Memory Trackers ---
users = {}
tasks = []                 
completed_tasks = set()    
pending_user_tasks = set() 

admin_chat_ids = set()
user_states = {}           
admin_states = {}

pending_proofs = {}        
proof_counter = 1

pending_withdrawals = {}   
withdraw_counter = 1

config = {
    "refer_bonus": 20,
    "rate_coins": 20,
    "rate_inr": 10,
    "min_withdraw_inr": 10.0
}

def get_coin_rate():
    return config["rate_inr"] / config["rate_coins"]

def sanitize_url(url):
    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://") or url.startswith("t.me/")):
        return "https://" + url
    return url

def get_user_display(uid):
    u = users.get(uid, {})
    name = u.get("name", "User")
    username = u.get("username")
    return f"{name} (@{username})" if username else name

# ==========================================
#              1. USER BOT
# ==========================================

def get_user_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("📋 Tasks", "💰 Balance", "👥 Refer & Earn", "💸 Withdraw", "💬 Support")
    return markup

@user_bot.message_handler(commands=['start'])
def handle_user_start(message):
    uid = message.from_user.id
    name = message.from_user.first_name or "User"
    username = message.from_user.username
    args = message.text.split()
    referrer = int(args[1]) if len(args) > 1 and args[1].isdigit() and int(args[1]) != uid else None

    if uid not in users:
        users[uid] = {"balance": 0, "name": name, "username": username, "referred_by": referrer}
        if referrer and referrer in users:
            bonus = config["refer_bonus"]
            users[referrer]["balance"] += bonus
            try:
                user_bot.send_message(referrer, f"🎉 Referral Bonus! A friend joined using your link. You earned +{bonus} Coins!")
            except:
                pass
    else:
        users[uid]["name"] = name
        users[uid]["username"] = username

    user_bot.send_message(
        uid,
        f"👋 Welcome {name}!\n\n"
        "Complete authentic tasks and earn Google Play Redeem Codes or direct UPI Cash!\n"
        f"💰 *Current Rate:* {config['rate_coins']} Coins = ₹{config['rate_inr']} INR\n"
        f"⚡ *Min Withdrawal:* ₹{config['min_withdraw_inr']:.2f} INR",
        parse_mode="Markdown",
        reply_markup=get_user_menu()
    )

@user_bot.message_handler(func=lambda m: m.text == "💰 Balance")
def show_balance(message):
    uid = message.from_user.id
    bal = users.get(uid, {}).get("balance", 0)
    inr_value = bal * get_coin_rate()
    user_bot.send_message(
        uid, 
        f"💳 *Account Wallet*\n\n"
        f"• Current Balance: *{bal} Coins*\n"
        f"• Estimated Value: *₹{inr_value:.2f} INR*\n\n"
        f"_(Rate: {config['rate_coins']} Coins = ₹{config['rate_inr']} | Min Withdrawal: ₹{config['min_withdraw_inr']:.2f})_", 
        parse_mode="Markdown"
    )

@user_bot.message_handler(func=lambda m: m.text == "👥 Refer & Earn")
def show_referral(message):
    uid = message.from_user.id
    bot_username = user_bot.get_me().username
    ref_link = f"https://t.me/{bot_username}?start={uid}"
    bonus = config["refer_bonus"]
    bonus_inr = bonus * get_coin_rate()

    share_text = "Join now and earn Google Play Redeem Codes & cash with me! 🎁🔥"
    tg_share_url = f"https://t.me/share/url?url={urllib.parse.quote(ref_link)}&text={urllib.parse.quote(share_text)}"

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🚀 Share / Copy Invite Link", url=tg_share_url))

    msg_text = (
        f"👥 *Referral Program*\n\n"
        f"Earn *{bonus} Coins* (≈ ₹{bonus_inr:.2f}) for every user who joins!\n\n"
        f"👇 *Your Personal Referral Code:*\n`{ref_link}`\n\n"
        f"_(Tap the link to copy)_"
    )
    user_bot.send_message(uid, msg_text, parse_mode="Markdown", reply_markup=markup)

@user_bot.message_handler(func=lambda m: m.text == "📋 Tasks")
def list_tasks(message):
    uid = message.from_user.id

    if not tasks:
        user_bot.send_message(uid, "ℹ️ No tasks available at the moment. Please check back later!")
        return

    available_tasks = [t for t in tasks if (uid, t["id"]) not in completed_tasks and (uid, t["id"]) not in pending_user_tasks]

    if not available_tasks:
        user_bot.send_message(uid, "🎉 You have completed all currently available tasks! New tasks will appear here once added.")
        return

    markup = types.InlineKeyboardMarkup()
    for t in available_tasks:
        badge = "📸 [Photo Proof]" if t["proof_type"] == "photo" else "✍️ [Text/Article]"
        markup.add(types.InlineKeyboardButton(f"{t['title']} (+{t['reward']} Coins) {badge}", callback_data=f"tsk_view_{t['id']}"))

    user_bot.send_message(uid, "📋 *Available Tasks:*", parse_mode="Markdown", reply_markup=markup)

@user_bot.callback_query_handler(func=lambda c: c.data.startswith("tsk_view_"))
def view_task_details(call):
    uid = call.from_user.id
    tid = int(call.data.split("_")[2])

    if (uid, tid) in completed_tasks or (uid, tid) in pending_user_tasks:
        user_bot.answer_callback_query(call.id, "You have already submitted or completed this task!", show_alert=True)
        try:
            user_bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        return

    task = next((t for t in tasks if t["id"] == tid), None)
    if not task:
        user_bot.answer_callback_query(call.id, "Task not found.")
        return

    markup = types.InlineKeyboardMarkup()
    if task["url"] and task["url"] != "None":
        markup.add(types.InlineKeyboardButton("🔗 Open Reference Link", url=sanitize_url(task["url"])))

    action_btn_text = "📸 Submit Screenshot" if task["proof_type"] == "photo" else "✍️ Submit Text / Story"
    markup.add(types.InlineKeyboardButton(action_btn_text, callback_data=f"sub_prf_{task['id']}"))

    task_inr = task['reward'] * get_coin_rate()
    text = (
        f"📌 *{task['title']}*\n"
        f"💰 Reward: *{task['reward']} Coins* (≈ ₹{task_inr:.2f})\n\n"
        f"📝 *Instructions:*\n{task['instruction']}\n\n"
        f"Tap the submit button below to send your verification proof."
    )

    user_bot.send_message(call.message.chat.id, text, parse_mode="Markdown", reply_markup=markup)
    user_bot.answer_callback_query(call.id)

@user_bot.callback_query_handler(func=lambda c: c.data.startswith("sub_prf_"))
def request_proof_upload(call):
    uid = call.from_user.id
    tid = int(call.data.split("_")[2])

    if (uid, tid) in completed_tasks or (uid, tid) in pending_user_tasks:
        user_bot.answer_callback_query(call.id, "Task already submitted!", show_alert=True)
        return

    task = next((t for t in tasks if t["id"] == tid), None)
    prompt_text = "Please upload your screenshot photo now:" if task["proof_type"] == "photo" else "Please write or paste your text submission below and send it:"

    msg = user_bot.send_message(call.message.chat.id, f"📝 *Submission Active*\n\n{prompt_text}", parse_mode="Markdown")
    user_states[uid] = {"action": "submitting_proof", "task_id": tid, "prompt_msg_id": msg.message_id}
    user_bot.answer_callback_query(call.id)

@user_bot.message_handler(content_types=['photo'])
def handle_user_photo(message):
    global proof_counter
    uid = message.from_user.id
    state = user_states.get(uid)

    if not state or state.get("action") != "submitting_proof":
        return

    tid = state.get("task_id")
    task = next((t for t in tasks if t["id"] == tid), None)
    if not task or task["proof_type"] != "photo":
        user_bot.reply_to(message, "⚠️ This task requires a text submission, not a photo.")
        return

    user_states.pop(uid, None)
    pending_user_tasks.add((uid, tid))

    try:
        user_bot.delete_message(message.chat.id, state.get("prompt_msg_id"))
    except:
        pass

    photo_id = message.photo[-1].file_id

    try:
        file_info = user_bot.get_file(photo_id)
        photo_bytes = user_bot.download_file(file_info.file_path)

        sub_id = proof_counter
        proof_counter += 1
        pending_proofs[sub_id] = {
            "type": "photo",
            "user_id": uid,
            "task_id": tid,
            "reward": task['reward'],
            "task_title": task['title'],
            "photo_bytes": photo_bytes
        }

        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ Approve", callback_data=f"adm_apr_{sub_id}"),
            types.InlineKeyboardButton("❌ Reject", callback_data=f"adm_rej_{sub_id}")
        )

        user_display = get_user_display(uid)
        caption = (
            f"📩 *New Photo Proof*\n\n"
            f"🆔 Submission: `#{sub_id}`\n"
            f"👤 User: *{user_display}*\n"
            f"📌 Task: {task['title']}\n"
            f"💰 Reward: {task['reward']} Coins (≈ ₹{task['reward'] * get_coin_rate():.2f})"
        )

        for admin_id in admin_chat_ids:
            try:
                img_stream = io.BytesIO(photo_bytes)
                img_stream.name = f"proof_{sub_id}.jpg"
                admin_bot.send_photo(admin_id, img_stream, caption=caption, parse_mode="Markdown", reply_markup=markup)
            except Exception as e:
                print(f"Admin send error: {e}")

        user_bot.reply_to(message, "✅ Photo proof submitted! Your task is now locked and sent for review.")

    except Exception as e:
        pending_user_tasks.discard((uid, tid))
        user_bot.reply_to(message, "⚠️ Failed to process image. Please try again.")

@user_bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get("action") == "submitting_proof")
def handle_user_text_proof(message):
    global proof_counter
    uid = message.from_user.id
    state = user_states.pop(uid, None)
    tid = state.get("task_id")

    task = next((t for t in tasks if t["id"] == tid), None)
    if not task or task["proof_type"] != "text":
        user_bot.reply_to(message, "⚠️ This task requires a screenshot, not text. Please submit a photo.")
        return

    pending_user_tasks.add((uid, tid))

    try:
        user_bot.delete_message(message.chat.id, state.get("prompt_msg_id"))
    except:
        pass

    sub_id = proof_counter
    proof_counter += 1
    pending_proofs[sub_id] = {
        "type": "text",
        "user_id": uid,
        "task_id": tid,
        "reward": task['reward'],
        "task_title": task['title'],
        "text_content": message.text
    }

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Approve", callback_data=f"adm_apr_{sub_id}"),
        types.InlineKeyboardButton("❌ Reject", callback_data=f"adm_rej_{sub_id}")
    )

    user_display = get_user_display(uid)
    admin_msg = (
        f"📝 *New Text Submission*\n\n"
        f"🆔 Submission: `#{sub_id}`\n"
        f"👤 User: *{user_display}*\n"
        f"📌 Task: {task['title']}\n"
        f"💰 Reward: {task['reward']} Coins (≈ ₹{task['reward'] * get_coin_rate():.2f})\n\n"
        f"📄 *Submission:*\n_{message.text}_"
    )

    for admin_id in admin_chat_ids:
        try:
            admin_bot.send_message(admin_id, admin_msg, parse_mode="Markdown", reply_markup=markup)
        except:
            pass

    user_bot.reply_to(message, "✅ Text submitted successfully! Your submission is now locked under admin review.")

# --- Withdraw System ---
@user_bot.message_handler(func=lambda m: m.text == "💸 Withdraw")
def show_withdraw_menu(message):
    uid = message.from_user.id
    bal = users.get(uid, {}).get("balance", 0)
    inr_value = bal * get_coin_rate()

    if inr_value < config["min_withdraw_inr"]:
        user_bot.send_message(
            uid,
            f"⚠️️ *Insufficient Balance for Withdrawal!*\n\n"
            f"Minimum withdrawal starts from *₹{config['min_withdraw_inr']:.2f} INR*.\n"
            f"Your current balance: *{bal} Coins* (≈ ₹{inr_value:.2f} INR).\n\n"
            f"Please complete more tasks or invite friends to reach at least ₹{config['min_withdraw_inr']:.2f}!",
            parse_mode="Markdown"
        )
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🎁 Google Play Redeem Code", callback_data="wth_type_code"),
        types.InlineKeyboardButton("⚡ UPI Transfer (Bank / UPI)", callback_data="wth_type_upi"),
        types.InlineKeyboardButton("🏦 Direct Bank Transfer (Coming Soon)", callback_data="wth_bank")
    )
    user_bot.send_message(
        message.chat.id, 
        f"💸 *Withdrawal Portal*\n\n"
        f"• Available Wallet: *{bal} Coins* (₹{inr_value:.2f} INR)\n"
        f"• Minimum Payout: *₹{config['min_withdraw_inr']:.2f} INR*\n\n"
        f"Select your desired payout option:", 
        parse_mode="Markdown", 
        reply_markup=markup
    )

@user_bot.callback_query_handler(func=lambda c: c.data == "wth_bank")
def withdraw_bank_coming_soon(call):
    user_bot.answer_callback_query(
        call.id,
        "⚠️ Coming Soon! Bank transfer is not available yet. Please use UPI or Redeem Code.",
        show_alert=True
    )

@user_bot.callback_query_handler(func=lambda c: c.data in ["wth_type_code", "wth_type_upi"])
def withdraw_amount_prompt(call):
    uid = call.from_user.id
    payout_type = "Google Play Redeem Code" if call.data == "wth_type_code" else "UPI Transfer"
    bal = users.get(uid, {}).get("balance", 0)
    max_inr = bal * get_coin_rate()

    if max_inr < config["min_withdraw_inr"]:
        user_bot.answer_callback_query(call.id, f"Minimum ₹{config['min_withdraw_inr']:.2f} required.", show_alert=True)
        return

    user_states[uid] = {"action": "waiting_withdraw_amount", "payout_type": payout_type}
    user_bot.send_message(
        call.message.chat.id,
        f"💵 *{payout_type} Payout*\n\n"
        f"• Available Balance: *₹{max_inr:.2f} INR* ({bal} Coins)\n"
        f"• Minimum Amount: *₹{config['min_withdraw_inr']:.2f} INR*\n\n"
        f"👉 How much money (in ₹) do you want to withdraw? (e.g. 10, 20, 50):",
        parse_mode="Markdown"
    )
    user_bot.answer_callback_query(call.id)

@user_bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get("action") == "waiting_withdraw_amount")
def process_withdraw_amount(message):
    uid = message.from_user.id
    state = user_states.get(uid, {})
    payout_type = state.get("payout_type", "Google Play Redeem Code")
    bal = users.get(uid, {}).get("balance", 0)
    max_inr = bal * get_coin_rate()

    try:
        amount = float(message.text.strip())
    except:
        user_bot.reply_to(message, "❌ Invalid amount! Please enter a valid number (e.g. 10 or 20):")
        return

    if amount < config["min_withdraw_inr"]:
        user_bot.reply_to(
            message, 
            f"⚠️ Withdrawal amount must be at least *₹{config['min_withdraw_inr']:.2f} INR*!\n"
            f"Please enter an amount of ₹{config['min_withdraw_inr']:.2f} or more:",
            parse_mode="Markdown"
        )
        return

    if amount > max_inr:
        user_bot.reply_to(
            message, 
            f"❌ Insufficient balance!\n"
            f"You requested ₹{amount:.2f}, but your available balance is *₹{max_inr:.2f} INR*.\n"
            f"Please enter an amount within your balance:",
            parse_mode="Markdown"
        )
        return

    coins_needed = round(amount / get_coin_rate())

    if payout_type == "UPI Transfer":
        user_states[uid] = {"action": "waiting_upi_id", "withdraw_amount": amount, "coins_needed": coins_needed}
        user_bot.send_message(
            uid,
            f"⚡ *UPI Payout Details:*\n"
            f"• Amount: *₹{amount:.2f} INR*\n"
            f"• Coins to deduct: *{coins_needed} Coins*\n\n"
            f"👉 Please enter your valid *UPI ID* (e.g. `yourname@oksbi` or `9876543210@paytm`):",
            parse_mode="Markdown"
        )
    else:
        global withdraw_counter
        user_states.pop(uid, None)
        users[uid]["balance"] -= coins_needed

        w_id = withdraw_counter
        withdraw_counter += 1
        pending_withdrawals[w_id] = {
            "user_id": uid,
            "coins": coins_needed,
            "amount": amount,
            "type": "code",
            "target": "Google Play Store"
        }

        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🎁 Send Redeem Code", callback_data=f"adm_wcode_{w_id}"),
            types.InlineKeyboardButton("❌ Reject & Refund", callback_data=f"adm_wrej_{w_id}")
        )

        user_display = get_user_display(uid)
        admin_alert = (
            f"🚨 *New Redeem Code Request #{w_id}*\n\n"
            f"👤 User: *{user_display}*\n"
            f"🎁 Item: Google Play Redeem Code\n"
            f"💵 Amount: *₹{amount:.2f} INR*\n"
            f"💰 Coins Deducted: *{coins_needed} Coins*\n\n"
            f"Click 'Send Redeem Code' below to enter and deliver the code:"
        )

        for admin_id in admin_chat_ids:
            try:
                admin_bot.send_message(admin_id, admin_alert, parse_mode="Markdown", reply_markup=markup)
            except:
                pass

        user_bot.reply_to(
            message,
            f"✅ *Redeem Request Submitted!*\n\n"
            f"• Item: Google Play Redeem Code (₹{amount:.2f} INR)\n"
            f"• Coins Deducted: *{coins_needed} Coins*\n"
            f"• Remaining Balance: *{users[uid]['balance']} Coins*\n\n"
            f"⏳ *Please wait!* Admin is reviewing your request and generating your redeem code. It will be sent right here shortly.",
            parse_mode="Markdown"
        )

@user_bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get("action") == "waiting_upi_id")
def process_upi_submission(message):
    global withdraw_counter
    uid = message.from_user.id
    state = user_states.pop(uid, None)

    upi_id = message.text.strip()
    if "@" not in upi_id or len(upi_id) < 5:
        user_bot.reply_to(message, "❌ Invalid UPI ID! Click 💸 Withdraw to try again.")
        return

    amount = state.get("withdraw_amount")
    coins_needed = state.get("coins_needed")

    bal = users.get(uid, {}).get("balance", 0)
    if bal < coins_needed:
        user_bot.reply_to(message, "⚠️ Balance insufficient for withdrawal.")
        return

    users[uid]["balance"] -= coins_needed

    w_id = withdraw_counter
    withdraw_counter += 1
    pending_withdrawals[w_id] = {
        "user_id": uid,
        "coins": coins_needed,
        "amount": amount,
        "type": "upi",
        "target": upi_id
    }

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Approve & Paid", callback_data=f"adm_wapp_{w_id}"),
        types.InlineKeyboardButton("❌ Reject & Refund", callback_data=f"adm_wrej_{w_id}")
    )

    user_display = get_user_display(uid)
    admin_alert = (
        f"🚨 *New UPI Payout Request #{w_id}*\n\n"
        f"👤 User: *{user_display}*\n"
        f"💳 UPI ID: `{upi_id}`\n"
        f"💰 Coins Deducted: *{coins_needed} Coins*\n"
        f"💵 Payout Amount: *₹{amount:.2f} INR*\n\n"
        f"Send the money to the UPI ID, then tap Approve:"
    )

    for admin_id in admin_chat_ids:
        try:
            admin_bot.send_message(admin_id, admin_alert, parse_mode="Markdown", reply_markup=markup)
        except:
            pass

    user_bot.reply_to(
        message, 
        f"✅ *UPI Payout Request Submitted!*\n\n"
        f"• Requested Amount: *₹{amount:.2f} INR*\n"
        f"• Destination UPI: `{upi_id}`\n"
        f"• Coins Deducted: *{coins_needed} Coins*\n\n"
        f"⏳ Admin is verifying and processing your payment. You will receive a confirmation message once completed!", 
        parse_mode="Markdown"
    )

# Support system
@user_bot.message_handler(func=lambda m: m.text == "💬 Support")
def handle_support(message):
    uid = message.from_user.id
    user_states[uid] = {"action": "waiting_support_message"}
    user_bot.send_message(uid, "💬 Please describe your problem or question in detail. Support will reply to you soon:")

@user_bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get("action") == "waiting_support_message")
def submit_support_ticket(message):
    uid = message.from_user.id
    user_states.pop(uid, None)

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✍️ Reply to User", callback_data=f"adm_reply_{uid}"))

    user_display = get_user_display(uid)
    text = f"🆘 *Support Ticket*\n\n👤 User: *{user_display}*\n📝 Message:\n_{message.text}_"
    for admin_id in admin_chat_ids:
        try:
            admin_bot.send_message(admin_id, text, parse_mode="Markdown", reply_markup=markup)
        except:
            pass

    user_bot.reply_to(message, "✅ Your support request has been delivered. We will get back to you shortly.")

# ==========================================
#              2. ADMIN BOT
# ==========================================

def get_admin_quick_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        "📩 Pending Proofs",
        "💸 Pending Payouts",
        "➕ Add Task",
        "📋 View Tasks",
        "⚙️ Settings",
        "👥 User Balances",
        "📢 Broadcast"
    )
    return markup

@admin_bot.message_handler(commands=['start', 'admin'])
def handle_admin_start(message):
    admin_chat_ids.add(message.chat.id)
    admin_bot.send_message(
        message.chat.id,
        "👑 *Admin Control Panel*\n\nManage tasks, proofs, settings, and payouts below:",
        parse_mode="Markdown",
        reply_markup=get_admin_quick_menu()
    )

# --- Settings ---
@admin_bot.message_handler(func=lambda m: m.text == "⚙️ Settings")
def admin_quick_settings(message):
    rate_text = f"{config['rate_coins']} Coins = ₹{config['rate_inr']} INR"
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(f"🪙 Change Coin Rate (Current: {rate_text})", callback_data="adm_menu_set_rate"),
        types.InlineKeyboardButton(f"🎁 Edit Refer Bonus (Current: {config['refer_bonus']} Coins)", callback_data="adm_menu_set_refer"),
        types.InlineKeyboardButton(f"📉 Edit Min Withdraw INR (Current: ₹{config['min_withdraw_inr']:.2f})", callback_data="adm_menu_set_min_w")
    )
    admin_bot.send_message(message.chat.id, "⚙️ *Bot Configuration Settings:*", parse_mode="Markdown", reply_markup=markup)

@admin_bot.callback_query_handler(func=lambda c: c.data == "adm_menu_set_rate")
def admin_set_rate_step1(call):
    msg = admin_bot.send_message(call.message.chat.id, "🪙 Step 1: Enter the number of Coins (e.g. 20):")
    admin_bot.register_next_step_handler(msg, admin_set_rate_step2)
    admin_bot.answer_callback_query(call.id)

def admin_set_rate_step2(message):
    if not message.text.isdigit() or int(message.text) <= 0:
        admin_bot.send_message(message.chat.id, "❌ Invalid input! Cancelled.")
        return
    coins = int(message.text)
    msg = admin_bot.send_message(message.chat.id, f"Step 2: Enter equivalent value in ₹ INR for {coins} coins (e.g. 10):")
    admin_bot.register_next_step_handler(msg, admin_set_rate_step3, coins)

def admin_set_rate_step3(message, coins):
    try:
        inr = float(message.text)
        if inr <= 0:
            raise ValueError
    except:
        admin_bot.send_message(message.chat.id, "❌ Invalid INR amount! Cancelled.")
        return

    config["rate_coins"] = coins
    config["rate_inr"] = inr

    admin_bot.send_message(
        message.chat.id, 
        f"✅ *Coin Rate Successfully Updated!*\n\n• New Rate: *{coins} Coins = ₹{inr} INR*\n• 1 Coin = ₹{get_coin_rate():.3f} INR", 
        parse_mode="Markdown"
    )

# --- View & Delete Tasks ---
@admin_bot.message_handler(func=lambda m: m.text == "📋 View Tasks")
def admin_quick_view_tasks(message):
    if not tasks:
        admin_bot.send_message(message.chat.id, "No tasks currently active.")
        return

    admin_bot.send_message(message.chat.id, f"📋 *Active Tasks ({len(tasks)}):*")
    for t in tasks:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(f"🗑 Delete Task #{t['id']}", callback_data=f"adm_deltask_{t['id']}"))

        text = (
            f"📌 *Task #{t['id']}: {t['title']}*\n"
            f"💰 Reward: {t['reward']} Coins (≈ ₹{t['reward'] * get_coin_rate():.2f})\n"
            f"📝 Type: {t['proof_type'].capitalize()}\n"
            f"🔗 Link: `{t['url']}`\n"
            f"ℹ️ Instructions: _{t['instruction']}_"
        )
        admin_bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=markup)

@admin_bot.callback_query_handler(func=lambda c: c.data.startswith("adm_deltask_"))
def admin_delete_task(call):
    tid = int(call.data.split("_")[2])
    global tasks
    task_to_del = next((t for t in tasks if t["id"] == tid), None)

    if not task_to_del:
        admin_bot.answer_callback_query(call.id, "Task not found or already deleted.", show_alert=True)
        return

    tasks = [t for t in tasks if t["id"] != tid]
    admin_bot.edit_message_text(f"🗑 *Task #{tid} has been permanently deleted.*", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
    admin_bot.answer_callback_query(call.id, "Task deleted successfully.")

# --- Payouts Handler ---
@admin_bot.message_handler(func=lambda m: m.text == "💸 Pending Payouts")
def admin_quick_pending_payouts(message):
    if not pending_withdrawals:
        admin_bot.send_message(message.chat.id, "✅ There are no pending payout requests.")
        return

    admin_bot.send_message(message.chat.id, f"📋 *Found {len(pending_withdrawals)} Pending Payout(s):*", parse_mode="Markdown")

    for w_id, item in list(pending_withdrawals.items()):
        markup = types.InlineKeyboardMarkup(row_width=2)
        user_display = get_user_display(item['user_id'])
        if item["type"] == "code":
            markup.add(
                types.InlineKeyboardButton("🎁 Send Redeem Code", callback_data=f"adm_wcode_{w_id}"),
                types.InlineKeyboardButton("❌ Reject & Refund", callback_data=f"adm_wrej_{w_id}")
            )
            text = (
                f"🆔 Payout ID: `#{w_id}`\n"
                f"👤 User: *{user_display}*\n"
                f"🎁 Type: *Google Play Redeem Code*\n"
                f"💰 Coins: {item['coins']} Coins\n"
                f"💵 Amount: *₹{item['amount']:.2f} INR*"
            )
        else:
            markup.add(
                types.InlineKeyboardButton("✅ Approve & Paid", callback_data=f"adm_wapp_{w_id}"),
                types.InlineKeyboardButton("❌ Reject & Refund", callback_data=f"adm_wrej_{w_id}")
            )
            text = (
                f"🆔 Payout ID: `#{w_id}`\n"
                f"👤 User: *{user_display}*\n"
                f"💳 UPI ID: `{item['target']}`\n"
                f"💰 Coins: {item['coins']} Coins\n"
                f"💵 Amount: *₹{item['amount']:.2f} INR*"
            )
        admin_bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=markup)

@admin_bot.callback_query_handler(func=lambda c: c.data.startswith("adm_wcode_"))
def admin_prompt_redeem_code(call):
    w_id = int(call.data.split("_")[2])
    payout = pending_withdrawals.get(w_id)
    if not payout:
        admin_bot.answer_callback_query(call.id, "Payout already processed.", show_alert=True)
        return

    user_display = get_user_display(payout['user_id'])
    msg = admin_bot.send_message(
        call.message.chat.id, 
        f"✍️️ Enter the Google Play Redeem Code for User *{user_display}* (Amount: ₹{payout['amount']:.2f}):",
        parse_mode="Markdown"
    )
    admin_bot.register_next_step_handler(msg, deliver_redeem_code, w_id, call.message.message_id)
    admin_bot.answer_callback_query(call.id)

def deliver_redeem_code(message, w_id, original_msg_id):
    code = message.text.strip()
    payout = pending_withdrawals.pop(w_id, None)

    if not payout:
        admin_bot.send_message(message.chat.id, "⚠️ Payout already handled or expired.")
        return

    uid = payout["user_id"]
    amount = payout["amount"]

    try:
        user_bot.send_message(
            uid,
            f"🎉 *Redeem Code Delivered!*\n\n"
            f"Here is your Google Play Store Redeem Code worth *₹{amount:.2f} INR*:\n\n"
            f"🎁 Code: `{code}`\n\n"
            f"_(Tap the code above to copy it directly into Google Play Store)_",
            parse_mode="Markdown"
        )
        admin_bot.send_message(message.chat.id, f"✅ Successfully delivered redeem code to User `{get_user_display(uid)}`!", parse_mode="Markdown")
    except Exception as e:
        admin_bot.send_message(message.chat.id, f"⚠️ Failed to deliver code to user: {e}")

    try:
        admin_bot.edit_message_text(f"🆔 Payout ID: `#{w_id}`\n\n✅ *Code Delivered Successfully*", message.chat.id, original_msg_id, parse_mode="Markdown")
    except:
        pass

@admin_bot.callback_query_handler(func=lambda c: c.data.startswith(("adm_wapp_", "adm_wrej_")))
def handle_payout_action(call):
    parts = call.data.split("_")
    action = parts[1]
    w_id = int(parts[2])

    payout = pending_withdrawals.pop(w_id, None)
    if not payout:
        admin_bot.answer_callback_query(call.id, "Payout already processed.", show_alert=True)
        return

    uid = payout["user_id"]
    coins = payout["coins"]
    amount = payout["amount"]

    if action == "wapp":
        try:
            user_bot.send_message(
                uid,
                f"🎉 *Payment Successful!*\n\n"
                f"Your payout of *₹{amount:.2f} INR* has been transferred to your UPI ID `{payout['target']}`.\n"
                f"Thank you for using our platform!",
                parse_mode="Markdown"
            )
        except:
            pass
        status_text = "✅ *Approved & Payment Sent*"
    else:
        users.setdefault(uid, {"balance": 0, "referred_by": None})
        users[uid]["balance"] += coins
        try:
            user_bot.send_message(
                uid,
                f"❌ *Withdrawal Rejected!*\n\n"
                f"Your payout request of ₹{amount:.2f} INR was rejected by admin.\n"
                f"🔄 *{coins} Coins* have been refunded back to your wallet.",
                parse_mode="Markdown"
            )
        except:
            pass
        status_text = "❌ *Rejected & Refunded*"

    try:
        admin_bot.edit_message_text(f"{call.message.text}\n\n{status_text}", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
    except:
        pass
    admin_bot.answer_callback_query(call.id, "Payout updated.")

# --- Pending Proofs ---
@admin_bot.message_handler(func=lambda m: m.text == "📩 Pending Proofs")
def admin_quick_pending_proofs(message):
    if not pending_proofs:
        admin_bot.send_message(message.chat.id, "✅ There are no pending proofs to review.")
        return

    admin_bot.send_message(message.chat.id, f"📋 *Found {len(pending_proofs)} Pending Review(s):*", parse_mode="Markdown")

    for sub_id, item in list(pending_proofs.items()):
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ Approve", callback_data=f"adm_apr_{sub_id}"),
            types.InlineKeyboardButton("❌ Reject", callback_data=f"adm_rej_{sub_id}")
        )
        user_display = get_user_display(item['user_id'])
        if item["type"] == "photo":
            caption = (
                f"🆔 Submission: `#{sub_id}`\n"
                f"👤 User: *{user_display}*\n"
                f"📌 Task: {item['task_title']}\n"
                f"💰 Reward: {item['reward']} Coins (≈ ₹{item['reward'] * get_coin_rate():.2f})"
            )
            try:
                img_stream = io.BytesIO(item["photo_bytes"])
                img_stream.name = f"proof_{sub_id}.jpg"
                admin_bot.send_photo(message.chat.id, img_stream, caption=caption, parse_mode="Markdown", reply_markup=markup)
            except Exception as e:
                print(f"Error rendering proof: {e}")
        else:
            text_body = (
                f"📝 *Text Submission #{sub_id}*\n\n"
                f"👤 User: *{user_display}*\n"
                f"📌 Task: {item['task_title']}\n"
                f"💰 Reward: {item['reward']} Coins (≈ ₹{item['reward'] * get_coin_rate():.2f})\n\n"
                f"📄 *Submission:*\n_{item['text_content']}_"
            )
            admin_bot.send_message(message.chat.id, text_body, parse_mode="Markdown", reply_markup=markup)

# --- Task Creation Engine ---
@admin_bot.message_handler(func=lambda m: m.text == "➕ Add Task")
def admin_quick_add_task(message):
    msg = admin_bot.send_message(message.chat.id, "Enter Task Title (e.g. Write an Essay or Download App):")
    admin_bot.register_next_step_handler(msg, admin_add_step_instruction)

def admin_add_step_instruction(message):
    title = message.text
    msg = admin_bot.send_message(message.chat.id, "Enter Task Description/Instructions for user:")
    admin_bot.register_next_step_handler(msg, admin_add_step_url, title)

def admin_add_step_url(message, title):
    instruction = message.text
    msg = admin_bot.send_message(message.chat.id, "Enter Link/URL (or send 'None' if no link needed):")
    admin_bot.register_next_step_handler(msg, admin_add_step_reward, title, instruction)

def admin_add_step_reward(message, title, instruction):
    url = message.text
    msg = admin_bot.send_message(message.chat.id, "Enter Reward Coins (numbers only):")
    admin_bot.register_next_step_handler(msg, admin_add_step_type, title, instruction, url)

def admin_add_step_type(message, title, instruction, url):
    if not message.text.isdigit():
        admin_bot.send_message(message.chat.id, "Invalid number! Aborted.")
        return
    reward = int(message.text)
    admin_states[message.chat.id] = {
        "title": title,
        "instruction": instruction,
        "url": url,
        "reward": reward
    }

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("📸 Screenshot Photo Required", callback_data="tsk_type_photo"),
        types.InlineKeyboardButton("✍️ Text Submission / Essay", callback_data="tsk_type_text")
    )
    admin_bot.send_message(message.chat.id, "Select verification type required from user:", reply_markup=markup)

@admin_bot.callback_query_handler(func=lambda c: c.data in ["tsk_type_photo", "tsk_type_text"])
def finalize_task_creation(call):
    data = admin_states.get(call.message.chat.id)
    if not data:
        admin_bot.send_message(call.message.chat.id, "Session expired. Try again.")
        return

    proof_type = "photo" if call.data == "tsk_type_photo" else "text"
    new_id = len(tasks) + 1
    tasks.append({
        "id": new_id,
        "title": data["title"],
        "instruction": data["instruction"],
        "url": data["url"],
        "reward": data["reward"],
        "proof_type": proof_type
    })

    admin_bot.send_message(
        call.message.chat.id,
        f"✅ *Task Published!*\n\nTitle: {data['title']}\nReward: {data['reward']} Coins (≈ ₹{data['reward'] * get_coin_rate():.2f})\nProof Mode: {proof_type.capitalize()}",
        parse_mode="Markdown"
    )
    admin_bot.answer_callback_query(call.id)

@admin_bot.callback_query_handler(func=lambda c: c.data == "adm_menu_set_min_w")
def admin_set_min_withdraw(call):
    msg = admin_bot.send_message(call.message.chat.id, f"Current minimum withdraw: ₹{config['min_withdraw_inr']:.2f} INR.\nEnter new minimum INR amount:")
    admin_bot.register_next_step_handler(msg, save_min_w)
    admin_bot.answer_callback_query(call.id)

def save_min_w(message):
    try:
        val = float(message.text.strip())
        if val <= 0:
            raise ValueError
        config["min_withdraw_inr"] = val
        admin_bot.send_message(message.chat.id, f"✅ Minimum withdraw updated to ₹{val:.2f} INR!")
    except:
        admin_bot.send_message(message.chat.id, "❌ Invalid number. Must be greater than 0.")

@admin_bot.message_handler(func=lambda m: m.text == "👥 User Balances")
def admin_quick_user_balances(message):
    if not users:
        admin_bot.send_message(message.chat.id, "No users registered yet.")
        return

    report = "👥 *Registered Users & Balances:*\n\n"
    for uid, data in list(users.items())[:30]:
        display = get_user_display(uid)
        report += f"• *{display}*: {data['balance']} Coins (≈ ₹{data['balance'] * get_coin_rate():.2f})\n"
    report += f"\nTotal Users: {len(users)}"
    admin_bot.send_message(message.chat.id, report, parse_mode="Markdown")

@admin_bot.message_handler(func=lambda m: m.text == "📢 Broadcast")
def admin_quick_broadcast(message):
    msg = admin_bot.send_message(message.chat.id, "Enter the message text to broadcast to ALL users:")
    admin_bot.register_next_step_handler(msg, execute_broadcast)

def execute_broadcast(message):
    text = f"📢 *Announcement:*\n\n{message.text}"
    count = 0
    for uid in users:
        try:
            user_bot.send_message(uid, text, parse_mode="Markdown")
            count += 1
        except:
            pass
    admin_bot.send_message(message.chat.id, f"✅ Broadcast sent successfully to {count} users.")

@admin_bot.callback_query_handler(func=lambda c: c.data == "adm_menu_set_refer")
def admin_set_refer(call):
    msg = admin_bot.send_message(call.message.chat.id, f"Current referral bonus: {config['refer_bonus']} Coins.\nEnter new amount:")
    admin_bot.register_next_step_handler(msg, save_refer_bonus)
    admin_bot.answer_callback_query(call.id)

def save_refer_bonus(message):
    if message.text.isdigit():
        config["refer_bonus"] = int(message.text)
        admin_bot.send_message(message.chat.id, f"✅ Referral bonus updated to {config['refer_bonus']} Coins!")
    else:
        admin_bot.send_message(message.chat.id, "Invalid number. Update failed.")

# --- Admin Review: Approve / Reject Execution ---
@admin_bot.callback_query_handler(func=lambda c: c.data.startswith(("adm_apr_", "adm_rej_")))
def handle_proof_action(call):
    parts = call.data.split("_")
    action = parts[1]
    sub_id = int(parts[2])

    data = pending_proofs.pop(sub_id, None)

    if not data:
        admin_bot.answer_callback_query(call.id, "This submission was already handled.")
        return

    uid = data["user_id"]
    tid = data["task_id"]
    reward = data["reward"]

    pending_user_tasks.discard((uid, tid))

    if action == "apr":
        completed_tasks.add((uid, tid))
        users.setdefault(uid, {"balance": 0, "name": "User", "username": None, "referred_by": None})
        users[uid]["balance"] += reward
        try:
            user_bot.send_message(uid, f"🎉 Your task proof has been approved! You received +{reward} Coins (≈ ₹{reward * get_coin_rate():.2f}).")
        except:
            pass
        status_text = "✅ *Approved*"
    else:
        try:
            user_bot.send_message(uid, f"❌ Your submission for *{data['task_title']}* was rejected by admin. Task has been reset.", parse_mode="Markdown")
        except:
            pass
        status_text = "❌ *Rejected*"

    try:
        if data["type"] == "photo":
            admin_bot.edit_message_caption(f"{call.message.caption}\n\n{status_text}", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
        else:
            admin_bot.edit_message_text(f"{call.message.text}\n\n{status_text}", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
    except:
        pass

    admin_bot.answer_callback_query(call.id, "Review recorded.")

@admin_bot.callback_query_handler(func=lambda c: c.data.startswith("adm_reply_"))
def prepare_support_reply(call):
    uid = int(call.data.split("_")[2])
    user_display = get_user_display(uid)
    msg = admin_bot.send_message(call.message.chat.id, f"Write your reply to User *{user_display}*:", parse_mode="Markdown")
    admin_bot.register_next_step_handler(msg, send_support_reply, uid)
    admin_bot.answer_callback_query(call.id)

def send_support_reply(message, uid):
    reply_text = message.text
    try:
        user_bot.send_message(uid, f"📩 *Support Reply:*\n\n{reply_text}", parse_mode="Markdown")
        admin_bot.send_message(message.chat.id, "✅ Reply sent successfully to user!")
    except:
        admin_bot.send_message(message.chat.id, "⚠️ Failed to deliver message. The user might have blocked the bot.")

# ==========================================
#             START POLLING & FLASK
# ==========================================

def run_user_bot():
    print("User Bot started...")
    user_bot.infinity_polling(timeout=10, long_polling_timeout=5)

def run_admin_bot():
    print("Admin Bot started...")
    admin_bot.infinity_polling(timeout=10, long_polling_timeout=5)

if __name__ == "__main__":
    # ১. ইউজার বট থ্রেড
    t_user = threading.Thread(target=run_user_bot)
    t_user.daemon = True
    t_user.start()

    # ২. অ্যাডমিন বট থ্রেড
    t_admin = threading.Thread(target=run_admin_bot)
    t_admin.daemon = True
    t_admin.start()

    # ৩. Render-এর জন্য Flask মেইন থ্রেডে চলবে
    run_flask()
