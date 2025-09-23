import requests
import logging

logger = logging.getLogger(__name__)

# IMPORTANT: Please replace the URL below with your own Lark Webhook URL
LARK_WEBHOOK_URL = "https://open.larksuite.com/open-apis/bot/v2/hook/1db81890-17f5-4278-9f96-82b442a4850f"

def send_lark_notification(message: str, mention_all: bool = True):
    """
    Sends a notification message to a Lark group via Webhook.

    Args:
        message (str): The text content to send.
        mention_all (bool): If True, @everyone will be mentioned.
        mention_user_ids (list[str]): A list of Open IDs of users to @.
    """
    if not LARK_WEBHOOK_URL or "YOUR_LARK_WEBHOOK_URL" in LARK_WEBHOOK_URL:
        logger.warning("Lark Webhook URL is not configured. Skipping notification.")
        return

    text_content = message
    if mention_all:
        # Prepend the mention tag to the message for it to work correctly
        text_content = f'<at user_id="all">All</at> {message}'

    # For normal messages, use the simple "text" type
    # The payload structure requires the text to be within a "content" dictionary.
    payload = {
        "msg_type": "text",
        "content": {
            "text": text_content
        }
    }

    try:
        response = requests.post(LARK_WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()  # This will raise an exception for 4xx or 5xx status codes
        logger.info("Successfully sent notification to Lark.")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send notification to Lark: {e}")

if __name__ == "__main__":
    # Example usage
    send_lark_notification("This is a test message from the Lark notifier.", mention_all=True)