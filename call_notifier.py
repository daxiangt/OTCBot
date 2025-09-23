import os
import logging
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from datetime import datetime, timedelta
from pathlib import Path
import csv

logger = logging.getLogger(__name__)

# --- File Path ---
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_DIR = SCRIPT_DIR / "Config"
TWILIO_CSV_PATH = CONFIG_DIR / "TwilioInfo.csv"
NUMBERS_TO_CALL_CSV_PATH = CONFIG_DIR / "NumbersToCall.csv"
# -----------------

# --- Rate Limiting Configuration ---
# This dictionary stores the last call timestamp for each phone number to prevent spam.
LAST_CALL_TIMESTAMPS = {}
CALL_COOLDOWN = timedelta(minutes=5)
# -----------------------------------

def load_recipient_numbers_from_csv(file_path: Path) -> list[str]:
    """
    Loads recipient phone numbers from the first column of a CSV file.
    """
    numbers = []
    if not file_path.exists():
        logger.warning(f"'{file_path.name}' not found. No recipient numbers loaded for Twilio calls.")
        return []
    
    try:
        with file_path.open(mode='r', encoding='utf-8') as infile:
            reader = csv.reader(infile)
            for row_num, row in enumerate(reader, start=1):
                if row and row[0].strip():
                    numbers.append(row[0].strip())
    except Exception as e:
        logger.error(f"Error reading '{file_path.name}': {e}")

    logger.info(f"Loaded {len(numbers)} recipient phone number(s) from '{file_path.name}'.")
    return numbers

def load_twilio_credentials_from_csv(file_path: Path) -> tuple[str, str, str]:
    """
    Loads Twilio credentials from a CSV file.
    The CSV file should contain 3 rows in this order:
    1. Account SID
    2. Auth Token
    3. Twilio Phone Number
    """
    try:
        with file_path.open(mode='r', encoding='utf-8') as infile:
            reader = csv.reader(infile)
            sid = next(reader)[0].strip()
            token = next(reader)[0].strip()
            number = next(reader)[0].strip()
            if not all([sid, token, number]):
                raise ValueError(f"One or more credential fields are empty in {file_path.name}.")
            logger.info(f"Twilio credentials loaded successfully from {file_path.name}.")
            return sid, token, number
    except FileNotFoundError:
        logger.warning(f"'{file_path.name}' not found at '{file_path}'. Phone call notifications will be disabled.")
    except (StopIteration, IndexError):
        logger.warning(f"'{file_path.name}' is improperly formatted. It must contain 3 rows. Phone calls disabled.")
    except Exception as e:
        logger.error(f"Failed to read Twilio credentials from CSV: {e}")
    
    return "NOT_CONFIGURED", "NOT_CONFIGURED", "NOT_CONFIGURED"

# --- Twilio Configuration ---
TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER = load_twilio_credentials_from_csv(TWILIO_CSV_PATH)

# Load recipient phone numbers from the CSV file.
RECIPIENT_PHONE_NUMBERS = load_recipient_numbers_from_csv(NUMBERS_TO_CALL_CSV_PATH)

def send_twilio_call(message: str):
    """
    Initiates a phone call via Twilio to read out a notification message,
    respecting a 5-minute cooldown period.

    Args:
        message (str): The text content to be read out during the call.
    """
    global LAST_CALL_TIMESTAMPS

    # Check if Twilio credentials or recipient numbers are configured
    if any(val == "NOT_CONFIGURED" for val in [TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]):
        logger.warning("Twilio credentials are not fully configured. Skipping phone call notification.")
        return
    
    if not RECIPIENT_PHONE_NUMBERS:
        logger.warning("No recipient phone numbers loaded. Skipping Twilio calls.")
        return

    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        twiml_message = f'<Response><Say language="en-US">{message}</Say></Response>'

        for number in RECIPIENT_PHONE_NUMBERS:
            # --- Per-Number Rate Limiting Check ---
            last_call_time = LAST_CALL_TIMESTAMPS.get(number)
            if last_call_time and (datetime.now() - last_call_time) < CALL_COOLDOWN:
                remaining_cooldown = CALL_COOLDOWN - (datetime.now() - last_call_time)
                logger.info(
                    f"Skipping Twilio call to {number} due to 5-minute cooldown. "
                    f"Time remaining: {int(remaining_cooldown.total_seconds())} seconds."
                )
                continue # Skip to the next number

            try:
                call = client.calls.create(
                    twiml=twiml_message,
                    to=number,
                    from_=TWILIO_PHONE_NUMBER
                )
                logger.info(f"Successfully initiated Twilio call to {number}.")
                # Update the timestamp for this specific number
                LAST_CALL_TIMESTAMPS[number] = datetime.now()
            except TwilioRestException as e:
                logger.error(f"Failed to initiate Twilio call to {number}: {e}")

    except TwilioRestException as e:
        logger.error(f"Failed to initialize Twilio client or process calls: {e}")


if __name__ == "__main__":
    # Example usage
    send_twilio_call("This is a test message from the Twilio notifier.")
