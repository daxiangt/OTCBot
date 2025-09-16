
# Telegram Bot Documentation

## 1. Overview

This document provides a comprehensive guide to a multi-functional, Python-based Telegram bot. Built using the `python-telegram-bot` library, it includes features for message broadcasting, group monitoring, multi-channel alerting, and robust administration.

Key functionalities include broadcasting messages, monitoring groups for unanswered queries, and notifying administrators through Telegram, Lark, and Twilio phone calls.

---

## 2. Features

*   **Broadcast Messaging**: Send text messages or photos with captions to multiple groups at once.
*   **Group Selection**: Choose between broadcasting to a list of "Large Groups" or "All Groups".
*   **Authorization Control**: Only users listed in `Allowed_User.csv` can perform administrative actions.
*   **Dynamic Configuration**: Reload all user and group lists from CSV files on-the-fly with the `/reload` command, without needing to restart the bot.
*   **Unanswered Message Alerts**: Monitors designated groups and triggers alerts if a user's message isn't answered by an admin within 5 minutes.
*   **Multi-Channel Notifications**: Sends critical alerts via:
    *   Lark (Webhook)
    *   Twilio (Phone Call)
    *   Telegram (Direct Message to Admins)
*   **Status Monitoring**: A `/status` command provides real-time information about the bot's uptime, configuration, and last heartbeat.
*   **Health Check Heartbeat**: Periodically sends a "heartbeat" message to admins to confirm the bot is running correctly.
*   **Group Join/Leave Alerts**: Automatically sends a notification to all admins when the bot is added to or removed from a group.
*   **Structured Logging**: All bot activities are logged to daily rotating JSON files (`.jsonl`) in a `logs` directory for easy parsing and monitoring.
*   **Interactive Workflow**: The `/send` command initiates a conversation with interactive buttons for selecting the target audience or canceling the operation.

---

## 3. Setup and Installation

### Prerequisites

*   Python 3.8 or newer.
*   A Telegram Bot Token from @BotFather.
*   A Lark Webhook URL.
*   A Twilio account with a phone number, Account SID, and Auth Token.

### Installation

1.  **Clone or download the project files.**

2.  **Install required Python libraries** using pip:
    ```sh
    pip install python-telegram-bot python-json-logger requests twilio
    ```

3.  **Create the necessary configuration files and directory structure.** Your project folder should look like this:

    ```
    /your_project_folder
    |-- OTCBot.py
    |-- Monitor.py
    |-- lark_notifier.py
    |-- call_notifier.py
    |-- /Config/
    |   |-- TGToken.csv
    |   |-- Allowed_User.csv
    |   |-- Group_List_Large.csv
    |   |-- Group_List_All.csv
    |   |-- Monitor_List.csv
    |   |-- TwilioInfo.csv
    |   |-- NumbersToCall.csv
    |-- /logs/              (This will be created automatically on first run)
    ```

### Configuration Files

You must create the `Config` folder and populate it with the following CSV files.

#### `TGToken.csv`
This file contains your unique Telegram Bot Token.

* **Format**: A single line with the token. No header.
* **Example:**
    ```
    1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789
    ```

#### `Allowed_User.csv`
This file lists the Telegram User IDs of administrators who are authorized to use commands like `/send`, `/reload`, and `/status`.

* **How to get a User ID**: Message [@userinfobot](https://t.me/userinfobot) on Telegram.
* **Format**: A header followed by one User ID per line.
* **Example:**
    ```csv
    user_id
    987654321
    135792468
    ```

#### `Group_List_Large.csv` & `Group_List_All.csv`
These files define the target groups for broadcasting. `Group_List_All.csv` should contain every target group, while `Group_List_Large.csv` can contain a subset (e.g., only your most important groups).

* **How to get a Group ID**:
    1.  Add your bot to the target group.
    2.  Make sure the bot has permission to read messages.
    3.  Send the `/start` command in that group.
    4.  The bot will reply with the Group Chat ID (it will be a negative number).
* **Format**: A header followed by one Group ID per line.
* **Example (`Group_List_All.csv`):**
    ```csv
    group_id
    -1001234567890
    -1009876543210
    -1001122334455
    ```
#### `Monitor_List.csv`
This file lists the Group IDs of chats where the bot should monitor for unanswered messages.

* **Format**: A header followed by one Group ID per line.
* **Example:**
    ```csv
    group_id
    -1001111111111
    ```

#### `TwilioInfo.csv`
Contains your Twilio credentials for making phone call alerts.

* **Format**: Three lines, in this specific order: Account SID, Auth Token, and your Twilio phone number. No header.
* **Example:**
    ```
    ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    your_auth_token_here
    +15017122661
    ```

#### `NumbersToCall.csv`
A list of phone numbers to call for Twilio alerts.

* **Format**: One phone number per line in E.164 format (`+` followed by country code and number). No header.
* **Example:**
    ```
    +14155552671
    +442071838750
    ```

#### `lark_notifier.py`
You must manually edit this file and replace the placeholder `LARK_WEBHOOK_URL` with your actual Lark bot webhook URL.


---

## 4. Running the Bot

Once you have installed the dependencies and configured the CSV files, you can run the bot from your terminal:

```sh
python OTCBot.py