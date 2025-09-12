import logging
import asyncio
import datetime
from functools import partial
from telegram import Update
from telegram.ext import ContextTypes

from lark_notifier import send_lark_notification
from call_notifier import send_twilio_call

logger = logging.getLogger(__name__)

# --- Unanswered Message Monitoring ---

async def unanswered_message_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    The callback function that is executed by the JobQueue if a message is not answered in time.
    It sends a notification to Lark and to Telegram admins.
    """
    job = context.job
    chat_title = job.data['chat_title']
    user_name = job.data['user_name']

    notification_message = (
        f"🚨 Unanswered Message Alert 🚨\n"
        f"A message from user '{user_name}' in group '{chat_title}' has not been answered for 5 minutes."
    )
    
    logger.warning(f"Unanswered message in '{chat_title}'. Triggering notifications.")

    # --- Run synchronous notification functions ---
    # Lark and Twilio functions are synchronous, so we run them in a separate thread pool
    # to avoid blocking the bot's async event loop.
    loop = asyncio.get_running_loop()

    # --- Send to Lark ---
    await loop.run_in_executor(
        None, partial(send_lark_notification, message=notification_message, mention_all=True)
    )
    # --- Initiate Twilio Phone Call ---
    await loop.run_in_executor(
        None, partial(send_twilio_call, message=notification_message)
    )

    # --- Send to Telegram Admins ---
    admin_ids = context.bot_data.get("allowed_user_ids", set())
    if not admin_ids:
        logger.warning("No admin IDs found in bot_data to send Telegram alert.")
        return

    for admin_id in admin_ids:
        try:
            await context.bot.send_message(chat_id=admin_id, text=notification_message)
            logger.info(f"Sent unanswered message alert to Telegram admin {admin_id}.")
        except Exception as e:
            logger.error(f"Failed to send Telegram alert to admin {admin_id}: {e}")

    # --- Clean up the job from chat_data ---
    # This is crucial to prevent JobLookupError if another message arrives later.
    if 'unanswered_job' in context.chat_data and context.chat_data['unanswered_job'].name == job.name:
        del context.chat_data['unanswered_job']
        logger.info(f"Cleaned up completed job '{job.name}' from chat_data for chat '{chat_title}'.")



async def monitor_group_chats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Monitors messages in specified groups.
    - If an allowed user sends a message, it cancels any pending alert and records their activity time.
    - If a non-allowed user sends a message, it only schedules an alert if no allowed user has been active in the last 5 minutes.
    """
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    allowed_user_ids = context.bot_data.get("allowed_user_ids", set())
    monitor_ids = context.bot_data.get("monitor_ids", set())

    # Only monitor messages in specified groups and ignore messages from the bot itself.
    if chat.id not in monitor_ids or user.id == context.bot.id:
        return

    unanswered_job = context.chat_data.get('unanswered_job')

    if user.id in allowed_user_ids:
        # An allowed user (admin) sent a message.
        # 1. Record their message time as the last known admin activity.
        context.chat_data['last_admin_message_time'] = message.date
        # 2. If a "no-reply" job is pending, cancel it because an admin has now responded.
        if unanswered_job:
            # Check if the job still exists in the queue before trying to remove it.
            # This prevents a JobLookupError if the job has already run.
            if context.job_queue.get_jobs_by_name(unanswered_job.name):
                unanswered_job.schedule_removal()
                logger.info(f"Admin '{user.username}' responded in '{chat.title}'. Canceled pending unanswered message job.")
            # Always remove the reference from chat_data.
            if 'unanswered_job' in context.chat_data:
                del context.chat_data['unanswered_job']
    else:
        # A non-allowed user sent a message.
        # Check when the last admin message was sent.
        last_admin_time = context.chat_data.get('last_admin_message_time')
        
        # If an admin has been active in the last 5 minutes, do nothing.
        if last_admin_time and (message.date - last_admin_time) < datetime.timedelta(minutes=5):
            logger.info(f"Ignoring user message in '{chat.title}' as an admin was recently active.")
            return
            
        # If we reach here, it's a new query. Cancel any old job and set a new one.
        if unanswered_job:
            # Same check as above to prevent race conditions.
            if context.job_queue.get_jobs_by_name(unanswered_job.name):
                unanswered_job.schedule_removal()
                logger.info(f"New user message arrived. Removing previously scheduled job '{unanswered_job.name}'.")


        job = context.job_queue.run_once(
            unanswered_message_callback,
            5, # 5 minutes
            name=f"unanswered_{chat.id}_{message.message_id}",
            chat_id=chat.id,
            data={'chat_title': chat.title, 'user_name': user.full_name}
        )
        context.chat_data['unanswered_job'] = job
        logger.info(f"Non-admin '{user.username}' sent a message in '{chat.title}'. Scheduled a 5-min check.")
