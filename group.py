import logging
from telegram import Update, ChatPermissions
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import BadRequest
import sqlite3
import re

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot token from BotFather
BOT_TOKEN = "8305370901:AAHZkm2LQ7-D5vXTpmGFzExo4je_TcQG-RE"

# Initialize database
def init_db():
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS blocked_words (
            chat_id INTEGER,
            word TEXT,
            PRIMARY KEY (chat_id, word)
        )
    ''')
    
    conn.commit()
    conn.close()

# Admin check function
async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type == 'private':
        return True
    
    admins = await context.bot.get_chat_administrators(chat.id)
    admin_ids = [admin.user.id for admin in admins]
    
    return user.id in admin_ids

# NEW: Username se user find karne ka better function
async def get_user_by_username(update: Update, context: ContextTypes.DEFAULT_TYPE, username: str):
    try:
        username = username.replace('@', '').strip().lower()
        logger.info(f"Searching for username: {username}")
        
        # Method 1: Chat members mein search karo (admins tak limited)
        admins = await context.bot.get_chat_administrators(update.effective_chat.id)
        for admin in admins:
            if admin.user.username and admin.user.username.lower() == username:
                return admin.user
        
        # Method 2: Recent messages mein search karo
        # Last 50 messages check karo
        try:
            messages = await update.effective_chat.get_messages(limit=50)
            for message in messages:
                if message.from_user and message.from_user.username:
                    if message.from_user.username.lower() == username:
                        return message.from_user
        except:
            pass
        
        # Method 3: Agar bot ko user ka pata hai (forwarded messages, etc.)
        # Yeh limited hai but try karte hain
        
        return None
        
    except Exception as e:
        logger.error(f"Error finding user by username: {e}")
        return None

# IMPROVED: User extraction function
async def extract_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Method 1: Reply to message (most reliable)
        if update.message.reply_to_message:
            return update.message.reply_to_message.from_user
        
        # Method 2: Username as argument
        if context.args:
            user_ref = context.args[0].strip()
            
            # Username format check (@username)
            if user_ref.startswith('@'):
                username = user_ref[1:]
                user = await get_user_by_username(update, context, username)
                
                if user:
                    return user
                else:
                    await update.message.reply_text(
                        f"❌ User @{username} not found in recent chat history.\n\n"
                        f"**Please try:**\n"
                        f"• Reply to user's message with command\n"
                        f"• Make sure user has sent messages recently\n"
                        f"• Or use user ID if available"
                    )
                    return None
            
            # User ID try karo
            elif user_ref.isdigit():
                try:
                    user_id = int(user_ref)
                    chat_member = await context.bot.get_chat_member(update.effective_chat.id, user_id)
                    return chat_member.user
                except BadRequest:
                    await update.message.reply_text("❌ User ID not found in this chat")
                    return None
            
            else:
                # Try as username without @
                user = await get_user_by_username(update, context, user_ref)
                if user:
                    return user
                else:
                    await update.message.reply_text(
                        f"❌ User @{user_ref} not found.\n\n"
                        f"**Please use:**\n"
                        f"• /mute @username\n"
                        f"• Or reply to user's message with /mute"
                    )
                    return None
        
        await update.message.reply_text(
            "❌ Usage:\n"
            "/mute @username\n"
            "Or reply to user's message with /mute"
        )
        return None
        
    except Exception as e:
        logger.error(f"Error in extract_user: {e}")
        return None

# Blocked words management
def add_blocked_word(chat_id, word):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO blocked_words (chat_id, word) VALUES (?, ?)', (chat_id, word.lower()))
    conn.commit()
    conn.close()

def remove_blocked_word(chat_id, word):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM blocked_words WHERE chat_id = ? AND word = ?', (chat_id, word.lower()))
    conn.commit()
    conn.close()

def get_blocked_words(chat_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT word FROM blocked_words WHERE chat_id = ?', (chat_id,))
    words = [row[0] for row in cursor.fetchall()]
    conn.close()
    return words

# Command handlers - USERNAME FOCUSED
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 **Admin Bot Started!**\n\n"
        "**Available commands:**\n"
        "/ban @username - Ban user\n" 
        "/unban @username - Unban user\n"
        "/mute @username - Mute user\n"
        "/unmute @username - Unmute user\n"
        "/kick @username - Kick user\n"
        "/purge - Delete messages (reply to first message)\n"
        "/filter word - Add blocked word\n"
        "/blockedwords - Show blocked words\n"
        "/removefilter word - Remove blocked word\n\n"
        "**Username usage:** /mute @username\n"
        "**Reply usage:** Reply to user's message with /mute",
        parse_mode='HTML'
    )

async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ You need to be an admin to use this command.")
        return
    
    user = await extract_user(update, context)
    
    if not user:
        return  # Error message already sent
    
    try:
        # Check if target is admin
        chat_member = await context.bot.get_chat_member(update.effective_chat.id, user.id)
        if chat_member.status in ['administrator', 'creator']:
            await update.message.reply_text("❌ Cannot mute an administrator.")
            return
        
        permissions = ChatPermissions(
            can_send_messages=False,
            can_send_media_messages=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False
        )
        await context.bot.restrict_chat_member(update.effective_chat.id, user.id, permissions)
        await update.message.reply_text(f"✅ @{user.username or user.first_name} has been muted!")
            
    except BadRequest as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def unmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ You need to be an admin to use this command.")
        return
    
    user = await extract_user(update, context)
    
    if not user:
        return
    
    try:
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True
        )
        await context.bot.restrict_chat_member(update.effective_chat.id, user.id, permissions)
        await update.message.reply_text(f"✅ @{user.username or user.first_name} has been unmuted!")
            
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ You need to be an admin to use this command.")
        return
    
    user = await extract_user(update, context)
    
    if not user:
        return
    
    try:
        # Check if target is admin
        chat_member = await context.bot.get_chat_member(update.effective_chat.id, user.id)
        if chat_member.status in ['administrator', 'creator']:
            await update.message.reply_text("❌ Cannot ban an administrator.")
            return
        
        await context.bot.ban_chat_member(update.effective_chat.id, user.id)
        await update.message.reply_text(f"✅ @{user.username or user.first_name} has been banned!")
        
    except BadRequest as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ You need to be an admin to use this command.")
        return
    
    user = await extract_user(update, context)
    
    if not user:
        return
    
    try:
        await context.bot.unban_chat_member(update.effective_chat.id, user.id)
        await update.message.reply_text(f"✅ @{user.username or user.first_name} has been unbanned!")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def kick_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ You need to be an admin to use this command.")
        return
    
    user = await extract_user(update, context)
    
    if not user:
        return
    
    try:
        # Check if target is admin
        chat_member = await context.bot.get_chat_member(update.effective_chat.id, user.id)
        if chat_member.status in ['administrator', 'creator']:
            await update.message.reply_text("❌ Cannot kick an administrator.")
            return
        
        await context.bot.ban_chat_member(update.effective_chat.id, user.id)
        await context.bot.unban_chat_member(update.effective_chat.id, user.id)
        await update.message.reply_text(f"✅ @{user.username or user.first_name} has been kicked!")
            
    except BadRequest as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# Purge and filter commands (same as before)
async def purge_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ You need to be an admin to use this command.")
        return
    
    try:
        if update.message.reply_to_message:
            start_message_id = update.message.reply_to_message.message_id
            end_message_id = update.message.message_id
            
            deleted_count = 0
            for message_id in range(start_message_id, end_message_id + 1):
                try:
                    await context.bot.delete_message(update.effective_chat.id, message_id)
                    deleted_count += 1
                except:
                    continue
            
            msg = await update.message.reply_text(f"✅ Purged {deleted_count} messages!")
            
        else:
            await update.message.reply_text("❌ Please reply to the first message you want to delete from.")
            
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def add_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ You need to be an admin to use this command.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /filter <word>")
        return
    
    word = ' '.join(context.args).lower()
    add_blocked_word(update.effective_chat.id, word)
    await update.message.reply_text(f"✅ Added '{word}' to blocked words list!")

async def remove_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ You need to be an admin to use this command.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /removefilter <word>")
        return
    
    word = ' '.join(context.args).lower()
    remove_blocked_word(update.effective_chat.id, word)
    await update.message.reply_text(f"✅ Removed '{word}' from blocked words list!")

async def show_blocked_words(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ You need to be an admin to use this command.")
        return
    
    words = get_blocked_words(update.effective_chat.id)
    if words:
        await update.message.reply_text(f"🚫 **Blocked Words:**\n" + "\n".join(f"• {word}" for word in words))
    else:
        await update.message.reply_text("📝 No blocked words set for this chat.")

# Message handler for blocked words
async def check_blocked_words(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private':
        return
    
    if await is_admin(update, context):
        return
    
    message_text = update.message.text or update.message.caption
    if not message_text:
        return
    
    blocked_words = get_blocked_words(update.effective_chat.id)
    message_lower = message_text.lower()
    
    for word in blocked_words:
        if word in message_lower:
            try:
                await update.message.delete()
                user = update.effective_user
                warning_msg = await update.effective_chat.send_message(
                    f"⚠️ {user.mention_html()} used a blocked word!",
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"Error handling blocked word: {e}")
            break

def main():
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ban", ban_user))
    application.add_handler(CommandHandler("unban", unban_user))
    application.add_handler(CommandHandler("mute", mute_user))
    application.add_handler(CommandHandler("unmute", unmute_user))
    application.add_handler(CommandHandler("kick", kick_user))
    application.add_handler(CommandHandler("purge", purge_messages))
    application.add_handler(CommandHandler("filter", add_filter))
    application.add_handler(CommandHandler("removefilter", remove_filter))
    application.add_handler(CommandHandler("blockedwords", show_blocked_words))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_blocked_words))
    
    application.run_polling()
    print("Bot is running...")

if __name__ == '__main__':
    main()