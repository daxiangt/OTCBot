import logging
import logging.handlers  
import asyncio
from functools import partial
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.helpers import escape_markdown
from telegram.constants import ParseMode, MessageEntityType
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackQueryHandler,
    JobQueue,
)
import datetime
import sys
import csv
from pythonjsonlogger import jsonlogger 

from Monitor import monitor_group_chats
from MarkPx import mark_px


# --- FILE PATHS ---
# Define the paths to your CSV files.
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_DIR = SCRIPT_DIR / "Config"
TOKEN_CSV_PATH = CONFIG_DIR / "TGToken.csv"
USERS_CSV_PATH = CONFIG_DIR / "Allowed_User.csv"
LARGE_GROUPS_CSV_PATH = CONFIG_DIR / "Group_List_Large.csv"
ALL_GROUPS_CSV_PATH = CONFIG_DIR / "Group_List_All.csv"
MONITOR_GROUPS_CSV_PATH = CONFIG_DIR / "Monitor_List.csv"
LOGS_DIR = SCRIPT_DIR / "logs"
# ------------------

# --- Conversation states ---
CHOOSING_GROUP = 0
GETTING_LEGS = 1

#--- Start time ---
BOT_START_TIME = datetime.datetime.now()

# --- logging configuration ---
# This new setup replaces the old logging.basicConfig() to provide daily
# rotating JSON log files and keep the console output clean.

# 1. Create the logs directory if it doesn't exist
LOGS_DIR.mkdir(exist_ok=True)

# 2. Get the root logger instance
# By configuring the root logger, all loggers in the application inherit this setup.
root_logger = logging.getLogger()

# 3. Set the global logging level to INFO.
root_logger.setLevel(logging.INFO)

# 4. Create a JSON formatter for structured logs.
json_formatter = jsonlogger.JsonFormatter(
    '%(asctime)s %(name)s %(levelname)s %(message)s'
)

# 5. Create a TimedRotatingFileHandler for daily log file rotation.
# This handler writes logs to a file, creating a new one every day at midnight.
file_handler = logging.handlers.TimedRotatingFileHandler(
    filename=LOGS_DIR / "bot_activity.jsonl", # .jsonl for JSON lines format
    when='midnight',
    interval=1,
    backupCount=30,  # Keeps the last 30 daily log files
    encoding='utf-8'
)
file_handler.setFormatter(json_formatter)
file_handler.setLevel(logging.INFO) # Ensure file handler captures all logs

# 6. Create a console handler to show logs in the terminal (like before).
console_handler = logging.StreamHandler()
# The console will only show INFO level and higher to avoid being too noisy.
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
console_handler.setFormatter(console_formatter)

# 7. Add both handlers to the root logger.
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

# 8. Keep the httpx logger quiet to avoid spam from the underlying library.
logging.getLogger("httpx").setLevel(logging.WARNING)

# 9. Get the specific logger for this module.
logger = logging.getLogger(__name__)


# Load the bot token directly from the CSV file

try:
    with TOKEN_CSV_PATH.open(mode='r', encoding='utf-8') as infile:
        reader = csv.reader(infile)
        first_row = next(reader, None)
        if not first_row or not first_row[0]:
            raise ValueError("Token file is empty or improperly formatted.")
        BOT_TOKEN = first_row[0]
        logger.info("Bot token loaded successfully.")
except FileNotFoundError:
    logger.critical(f"CRITICAL: Token file not found at '{TOKEN_CSV_PATH}'. Bot cannot start.")
    sys.exit(1) # Exit the script
except Exception as e:
    logger.critical(f"CRITICAL: Failed to read token: {e}. Bot is shutting down.")
    sys.exit(1) # Exit the script


#load groups and users from csv
def read_ids_from_csv(file_path: Path, file_description: str) -> list[str]:
    """
    Reads a list of IDs as strings from the first column of a CSV file.
    """
    ids = []
    if not file_path.exists():
        # If the file is not found, log an error and return an empty list.
        logger.error(f"Configuration Error: The file '{file_path}' was not found. Please create it and restart the bot.")
        return []

    try:
        with file_path.open(mode='r', encoding='utf-8') as infile:
            reader = csv.reader(infile)
            next(reader, None)  # Skip the header row
            for row_num, row in enumerate(reader, start=2):
                if row:  # Check if the row is not empty
                    try:
                        # Read the ID as a string and remove any leading/trailing whitespace.
                        # This avoids any issues with scientific notation from spreadsheets.
                        ids.append(row[0].strip())
                    except (ValueError, IndexError):
                        logger.warning(f"Skipping invalid ID in '{file_path}' on line {row_num}: '{row}'")
    except Exception as e:
        logger.error(f"Error reading '{file_path}': {e}")
    
    logger.info(f"Loaded {len(ids)} {file_description}(s) from '{file_path}'")
    return ids


# Load IDs from files at startup
ALLOWED_USER_IDS = read_ids_from_csv(USERS_CSV_PATH, "allowed user")
GROUP_IDS_LARGE = read_ids_from_csv(LARGE_GROUPS_CSV_PATH, "large group")
GROUP_IDS_ALL = read_ids_from_csv(ALL_GROUPS_CSV_PATH, "all group")
MONITOR_GROUP_IDS = read_ids_from_csv(MONITOR_GROUPS_CSV_PATH, "monitored group")



#start command
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    This async function is called when the /start command is issued.
    It sends a welcome message to the user.
    """

    user = update.effective_user
    chat = update.effective_chat

    # The message to be sent
    greeting_message = f"Hello, {user.username}! Welcome to SignalPlus bot. I'm ready to chat." #may need change later

    if chat.type == 'private':
        greeting_message += f"\nThis is a private chat. Your Chat ID is: {chat.id}"
        logger.info(f"User {user.username} ({user.id}) started the bot in a private chat ({chat.id}).")
    else: # Covers 'group' and 'supergroup'
        greeting_message += f"\nThis bot was started in the group: '{chat.title}'.\nThe Group Chat ID is: {chat.id}"
        logger.info(f"User {user.username} ({user.id}) started the bot in group '{chat.title}' ({chat.id}).")

    # Send the message (using 'await')
    await update.message.reply_text(greeting_message)



#send start
async def send_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    # Check if the user is in the allowed list
    if str(user.id) not in ALLOWED_USER_IDS:
        logger.warning(f"Unauthorized send attempt by user {user.username} ({user.id}).")
        await update.message.reply_text("Sorry, you are not authorized to use this command.")
        return ConversationHandler.END

    """Handles the /send command to broadcast a message."""
    chat = update.message.chat

    # Ensure the command is used in a private chat for security/privacy
    if chat.type != 'private':
        await update.message.reply_text("This command can only be used in a private chat with me.")
        return ConversationHandler.END

    message = update.message
    text_content = ""
    entities = []

    # Case 1: Command is in a photo caption
    if message.photo:
        text_content = message.caption or ""
        entities = message.caption_entities or []
        context.user_data['broadcast_type'] = 'photo'
        # Get the highest resolution photo
        context.user_data['photo_id'] = message.photo[-1].file_id
    # Case 2: Command is a standard text message
    elif message.text:
        text_content = message.text
        entities = message.entities
        context.user_data['broadcast_type'] = 'text'

    # Find the command in the entities to extract the message part
    command_entity = next((e for e in entities if e.type == MessageEntityType.BOT_COMMAND), None)

    # This function is an entry point for /send, so a command should exist.
    # We extract the text that comes after the /send command.
    message_part = ""
    if command_entity:
        message_part = text_content[command_entity.offset + command_entity.length:].strip()

    # Store the extracted content for broadcasting
    if context.user_data.get('broadcast_type') == 'photo':
        context.user_data['caption_to_broadcast'] = message_part
        logger.info(f"User {user.username} ({user.id}) initiated photo broadcast with caption: '{message_part}'")
    else:  # Text message
        if not message_part:
            await update.message.reply_text("Please provide a message to send.\nUsage: /send <your message>")
            return ConversationHandler.END
        context.user_data['message_to_broadcast'] = message_part
        logger.info(f"User {user.username} ({user.id}) initiated broadcast with message: '{message_part}'")

    # Create the selection keyboard
    keyboard = [
        [
            InlineKeyboardButton("Large Size Maker Groups", callback_data="send_large_only"),
            InlineKeyboardButton("All Size Maker Groups", callback_data="send_all"),
        ],
        [InlineKeyboardButton("Cancel", callback_data="cancel_send")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # The previous code was only trying to send a text reply, which would fail for photos.
    if context.user_data.get('broadcast_type') == 'photo':
        await update.message.reply_photo(
            photo=context.user_data['photo_id'],
            caption=(f"PREVIEW:\n{message_part}\n\n"
                     "Your photo is ready. Please choose which groups to send it to:"),
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            f"PREVIEW:\n{message_part}\n\n"
            "Your message is ready. Please choose which groups to send it to:",
            reply_markup=reply_markup
        )
    return CHOOSING_GROUP

#send select group
async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the user's choice and broadcasts the message."""
    query = update.callback_query
    await query.answer() # Acknowledge the button press

    choice = query.data
    user = query.from_user
    broadcast_type = context.user_data.get('broadcast_type')


    if str(user.id) not in ALLOWED_USER_IDS:
        logger.warning(f"Unauthorized send attempt by user {user.username} ({user.id}).")
        if query.message.photo:
            await query.edit_message_caption(caption="Sorry, you are not authorized to perform this action.")
        else:
            await query.edit_message_text("Sorry, you are not authorized to perform this action.")
        return ConversationHandler.END

    if not broadcast_type:
        if query.message.photo:
            await query.edit_message_caption(caption="Error: I've lost the message to send. Please start again with /send.")
        else:
            await query.edit_message_text("Error: I've lost the message to send. Please start again with /send.")
        return ConversationHandler.END

    if choice == 'send_large_only':
        target_groups = GROUP_IDS_LARGE
        group_name_log = "Large Groups"
    elif choice == 'send_all':
        target_groups = GROUP_IDS_ALL
        group_name_log = "All Groups"
    else:
        await query.edit_message_text("Invalid selection.")
        return ConversationHandler.END

    broadcast_status_text = f"Broadcasting to {len(target_groups)} '{group_name_log}'... Please wait."
    if query.message.photo:
        await query.edit_message_caption(caption=broadcast_status_text)
    else:
        await query.edit_message_text(text=broadcast_status_text)

    successful_sends = 0
    failed_sends = 0
    failed_group_ids = []

    for group_id in target_groups:
        try:
            if broadcast_type == 'photo':
                photo_id = context.user_data.get('photo_id')
                caption = context.user_data.get('caption_to_broadcast')
                await context.bot.send_photo(chat_id=group_id, photo=photo_id, caption=caption)
            else: # 'text'
                message_text = context.user_data.get('message_to_broadcast')
                await context.bot.send_message(chat_id=group_id, text=message_text)
            successful_sends += 1
        except Exception as e:
            failed_sends += 1
            failed_group_ids.append(group_id)
            logger.error(f"Failed to send message to group {group_id}: {e}")

    confirmation_message = (
        f"Broadcast complete!\n"
        f"Successfully sent to: {successful_sends} group(s).\n"
        f"Failed to send to: {failed_sends} group(s)."
    )
    if failed_sends > 0:
        failed_ids_str = ', '.join(failed_group_ids)
        confirmation_message += f"\nFailed IDs: {failed_ids_str}"
        confirmation_message += "\nPlease check logs for errors. I might not be a member or lack permissions in those groups."

    if query.message.photo:
            await query.edit_message_caption(caption=confirmation_message, reply_markup=None)
    else:
        await query.edit_message_text(text=confirmation_message, reply_markup=None)
    
    # Clean up user_data
    context.user_data.clear()
    return ConversationHandler.END


#send cancel
async def cancel_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the send operation and clears user data."""
    query = update.callback_query
    await query.answer()
    if query.message.photo:
        await query.edit_message_caption(caption="Broadcast canceled.", reply_markup=None)
    else:
        await query.edit_message_text(text="Broadcast canceled.", reply_markup=None)

    context.user_data.clear()
    return ConversationHandler.END



#reload lists
async def reload_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reloads the allowed user and group IDs from the CSV files."""
    global ALLOWED_USER_IDS, GROUP_IDS_LARGE, GROUP_IDS_ALL, MONITOR_GROUP_IDS


    user = update.effective_user
    if str(user.id) not in ALLOWED_USER_IDS:
        logger.warning(f"Unauthorized reload attempt by user {user.username} ({user.id}).")
        await update.message.reply_text("Sorry, you are not authorized to use this command.")
        return
        
    logger.info(f"Reload initiated by user {user.username} ({user.id})")
    
    # Re-read the CSV files
    new_users = read_ids_from_csv(USERS_CSV_PATH, "allowed user")
    new_groups_large = read_ids_from_csv(LARGE_GROUPS_CSV_PATH, "large group")
    new_groups_all = read_ids_from_csv(ALL_GROUPS_CSV_PATH, "all group")
    new_monitor_ids = read_ids_from_csv(MONITOR_GROUPS_CSV_PATH, "monitored group")

    if USERS_CSV_PATH.exists():
        ALLOWED_USER_IDS = new_users
    if LARGE_GROUPS_CSV_PATH.exists():
        GROUP_IDS_LARGE = new_groups_large
    if ALL_GROUPS_CSV_PATH.exists():
        GROUP_IDS_ALL = new_groups_all
    if MONITOR_GROUPS_CSV_PATH.exists():
        MONITOR_GROUP_IDS = new_monitor_ids

    context.bot_data["allowed_user_ids"] = set(ALLOWED_USER_IDS)
    context.bot_data["monitor_ids"] = set(MONITOR_GROUP_IDS)

    
    reply_message = (
        "Configuration reload finished!\n"
        f"Found {len(ALLOWED_USER_IDS)} allowed users.\n"
        f"Found {len(GROUP_IDS_LARGE)} large groups.\n"
        f"Found {len(GROUP_IDS_ALL)} all groups.\n"
        f"Found {len(MONITOR_GROUP_IDS)} monitored groups for unanswered alerts."
    )
    await update.message.reply_text(reply_message)


#help command
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    help_message = (
    "/start - Shows the welcome message.\n"
    "/send <message> - Broadcasts a text message or a photo.\n"
    "/reload - Reloads the user and group lists.\n"
    "/px - Calculates the net mark price for a multi-leg options strategy.\n"
    "/status - Shows the bot's current status and uptime.\n"
    "/help - Shows this help message.\n"
    "Automatic Features:\n"
    " **Admin Notifications when the bot is added or removed from a group.\n"
    " **Unanswered Message Alerts in monitored groups."
    )
    await update.message.reply_text(help_message)
    logger.info(f"User {user.username} ({user.id}) is checking help")


#status command 
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Provides an overview of the bot's status."""
    user = update.effective_user
    if str(user.id) not in ALLOWED_USER_IDS:
        await update.message.reply_text("Sorry, you are not authorized to use this command.")
        return

    # Calculate uptime
    current_time = datetime.datetime.now()
    uptime_delta = current_time - BOT_START_TIME
    
    # To avoid displaying microseconds, we format it nicely
    total_seconds = int(uptime_delta.total_seconds())
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{days}d, {hours}h, {minutes}m, {seconds}s"

    status_message = (
        f"Bot Status: Running ✅\n"
        f"Uptime: {uptime_str}\n"
        f"Allowed Users: {len(ALLOWED_USER_IDS)}\n"
        f"Large Groups: {len(GROUP_IDS_LARGE)}\n"
        f"Total Groups: {len(GROUP_IDS_ALL)}\n"
        f"Monitored Groups: {len(MONITOR_GROUP_IDS)}\n"
        f"Last Heartbeat: {context.bot_data.get('last_heartbeat', 'Never')}"
    )
    
    await update.message.reply_text(status_message)
    logger.info(f"User {user.username} ({user.id}) checked status.")



#unknown command
async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    """Handles any command that isn't recognized."""
    await update.message.reply_text("Sorry, I don't recognize that command. Please use /help to see available commands.")
    logger.info(f"User {user.username} ({user.id}) entered unknown command: {update.message.text}")


# --- Price Command Conversation ---

async def price_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    logger.info(f"User {user.username} ({user.id}) initiated price calculation with /px.")

    prompt_message = (
        "Please enter the strategy legs, one per line\. \n\n"
        "*Format:* `[+/-]quantity [BTC-]EXPIRY-STRIKE-TYPE`\n"
        "Can omit `BTC-` for Bitcoin options and can omit all `-` and last `000` in the instrument name\. \n\n"
        "**Example:**\n"
        "`+1 26DEC25 95000 P`\n"
        "`-2 26DEC25 130000 C`\n"

        "Use `/cancel` to exit\."

    )
    await update.message.reply_text(prompt_message, parse_mode=ParseMode.MARKDOWN_V2)
    return GETTING_LEGS

async def price_get_legs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives the legs, calls mark_px, and returns the result."""
    user = update.effective_user
    user_input = update.message.text
    logger.info(f"User {user.username} ({user.id}) submitted legs for /px: {user_input.replace(chr(10), '; ')}")
    # Split the input by newlines and filter out any empty lines
    strategy_legs_input = [line.strip() for line in user_input.split('\n') if line.strip()]

    if not strategy_legs_input:
        await update.message.reply_text("You didn't provide any legs. Please try again or use /cancel.")
        return GETTING_LEGS

    await update.message.reply_text("Calculating, please wait...")

    # Call the async mark_px function
    result_string = await mark_px(strategy_legs_input)

    # Send the result back to the user
    await update.message.reply_text(result_string)

    return ConversationHandler.END

async def price_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the price calculation operation."""
    user = update.effective_user
    logger.info(f"User {user.username} ({user.id}) canceled the price calculation.")
    await update.message.reply_text("Price calculation canceled. Please re-enter command.")
    return ConversationHandler.END



#heartbeat
async def heartbeat(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a heartbeat message to a specific user to show the bot is alive."""
    # The user ID to send the heartbeat to, as per the request.
    HEARTBEAT_RECIPIENT_ID = 5596846279 #send to Tony only

    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    context.bot_data['last_heartbeat'] = current_time
    message = f"Heartbeat\nBot Status: Running ✅ \nTimestamp: {current_time}"

    try:
        await context.bot.send_message(chat_id=HEARTBEAT_RECIPIENT_ID, text=message)
        logger.info(f"Sent heartbeat message to recipient ({HEARTBEAT_RECIPIENT_ID}).")
    except Exception as e:
        logger.error(f"Failed to send heartbeat message to recipient ({HEARTBEAT_RECIPIENT_ID}): {e}")


# Handle bot being added to a new group
async def on_new_group_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the event of the bot being added to a new group.
    Sends a notification to all allowed users (admins).
    """
    # The message is a status update, not a user message, so we check effective_message
    if not update.effective_message or not update.effective_message.new_chat_members:
        return

    # Check if the bot itself is one of the new members
    bot_id = context.bot.id
    if any(member.id == bot_id for member in update.effective_message.new_chat_members):
        chat = update.effective_chat
        user_who_added = update.effective_user # The user who performed the action

        logger.info(f"Bot was added to new group '{chat.title}' ({chat.id}) by {user_who_added.username} ({user_who_added.id}).")

        message_to_admins = (
            f"🔼 New Group Joined 🔼\n"
            f"I have been added to a new group.\n"
            f"Group Name: {chat.title}\n"
            f"Group ID: {chat.id}\n"
            f"Added By: @{user_who_added.username or 'N/A'}"
        )

        # Send the notification to all allowed users
        if not ALLOWED_USER_IDS:
            logger.warning("Bot added to a group, but no admin IDs are configured to receive the notification.")
            return

        for admin_id in ALLOWED_USER_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id, text=message_to_admins
                )
            except Exception as e:
                logger.error(f"Failed to send 'new group' notification to admin {admin_id}: {e}")


# Handle bot being removed from a group
async def on_group_leave(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the event of the bot being removed from a group.
    Sends a notification to all allowed users (admins).
    """
    if not update.effective_message or not update.effective_message.left_chat_member:
        return

    # Check if the bot itself is the one who left
    bot_id = context.bot.id
    if update.effective_message.left_chat_member.id == bot_id:
        chat = update.effective_chat
        user_who_removed = update.effective_user  # The user who performed the action

        logger.info(f"Bot was removed from group '{chat.title}' ({chat.id}) by {user_who_removed.username} ({user_who_removed.id}).")

        message_to_admins = (
            f"🔽 Removed From Group 🔽\n"
            f"I have been removed from a group.\n"
            f"Group Name: {chat.title}\n"
            f"Group ID: {chat.id}\n"
            f"Removed By: @{user_who_removed.username or 'N/A'}"
        )

        # Send notification to all allowed users
        if not ALLOWED_USER_IDS:
            logger.warning("Bot removed from a group, but no admin IDs are configured to receive the notification.")
            return

        for admin_id in ALLOWED_USER_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id, text=message_to_admins
                )
            except Exception as e:
                logger.error(f"Failed to send 'group leave' notification to admin {admin_id}: {e}")



#main
def main() -> None:
    """Starts the bot and listens for commands."""
    print("Bot is starting...")

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(BOT_TOKEN).build()

    # Initialize bot_data with IDs for the reminder system
    application.bot_data.update({
        "allowed_user_ids": set(ALLOWED_USER_IDS),
        "monitor_ids": set(MONITOR_GROUP_IDS)
    })

    # Create a JobQueue for heartbeat job ---
    
    job_queue = application.job_queue

    # 1. Calculate the delay until the next hour for the repeating job
    now = datetime.datetime.now()
    # Calculate the time of the next hour
    next_hour = (now + datetime.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    # Calculate the seconds until the next hour
    first_run_delay = (next_hour - now).total_seconds()

    # 2. Schedule the repeating job to run every hour, starting at the next hour
    job_queue.run_repeating(heartbeat, interval=3600, first=first_run_delay)
    # 3. Schedule a one-time job to run immediately on startup
    job_queue.run_once(heartbeat, when=1) # Run 1 second after startup
    logger.info(f"Heartbeat job scheduled. First run in {int(first_run_delay)} seconds, then hourly. An initial heartbeat will be sent now.")
    


    # This filter combination will trigger for EITHER:
    # 1. A text message that is the /send command.
    # 2. A photo message where the caption starts with /send.
    send_filter = filters.COMMAND & filters.Regex(r'^/send')
    photo_filter = filters.PHOTO & filters.CaptionRegex(r'^/send')

    send_conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(
                (send_filter | photo_filter), send_start
            )
        ],
        states={
            CHOOSING_GROUP: [
                CallbackQueryHandler(broadcast_message, pattern="^send_.*"),
                CallbackQueryHandler(cancel_send, pattern="^cancel_send$"),
            ]
        },
        fallbacks=[CommandHandler("send", send_start)],
    )

    price_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("px", price_start)],
        states={
            GETTING_LEGS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, price_get_legs)
            ]
        },
        fallbacks=[MessageHandler(filters.COMMAND, price_cancel)],
    )


    # Register the command handlers
    application.add_handler(send_conv_handler)
    application.add_handler(price_conv_handler)

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("reload", reload_command))
    application.add_handler(CommandHandler("status", status_command))

    # Add handler for monitoring unanswered messages. It should process all text messages that are not commands.
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, monitor_group_chats))

    # Add handler for monitoring unanswered messages from photos with captions.
    # This ensures that if a user asks a question by sending a picture, it's also monitored.
    application.add_handler(MessageHandler(filters.CAPTION & ~filters.COMMAND, monitor_group_chats))



    # This handler specifically listens for status updates about new chat members.
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_group_join))

    # This handler listens for when the bot is removed from a chat.
    application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, on_group_leave))

    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    # Start the Bot by continuously polling for updates
    logger.info("Bot is polling for messages...")
    application.run_polling(drop_pending_updates=True)
    logger.info("Bot has stopped.")


if __name__ == "__main__":
    main()
