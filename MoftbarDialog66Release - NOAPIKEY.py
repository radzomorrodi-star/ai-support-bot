# This code requires the `telethon` module to be installed to run correctly.pending_tickets
# Since the environment cannot install external modules, please run this code in a local environment.
import sqlite3
import asyncio
import openai
from openai import OpenAI
import re
import json
import time
import datetime
import unicodedata
import os  # For file operations
from telethon.tl.types import InputMessagesFilterPinned
from telethon import TelegramClient, events, Button
from telethon.tl.functions.messages import GetHistoryRequest, ForwardMessagesRequest
from telethon.tl.functions.contacts import GetContactsRequest
from telethon.errors import FloodWaitError, MessageNotModifiedError
from rapidfuzz import process, fuzz

import random
import aiohttp

user_tickets_lock = asyncio.Lock()




# The username to use for authentication
username = 'mftadmin'



# API Credentials
api_id = 22644005
api_hash = "325e1e9c59d3180d0188568126d905b8"
openai.api_key = "....."
# Initialize Telegram Client
client = TelegramClient(username, api_id, api_hash)

# Variables to store the bot's actual information after connection
bot_username = None
bot_id = None

# Admin management functions
def load_admin_chat_ids():
    """Load admin chat IDs from file"""
    global admin_chat_ids
    try:
        if os.path.exists(ADMIN_FILE):
            with open(ADMIN_FILE, 'r') as f:
                admin_chat_ids = set(int(line.strip()) for line in f if line.strip())
            print(f"✅ Loaded {len(admin_chat_ids)} admin chat IDs from file")
        else:
            print("ℹ️ No admin file found, starting with empty admin list")
    except Exception as e:
        print(f"❌ Error loading admin chat IDs: {e}")
        admin_chat_ids = set()

def save_admin_chat_ids():
    """Save admin chat IDs to file"""
    try:
        with open(ADMIN_FILE, 'w') as f:
            for chat_id in admin_chat_ids:
                f.write(f"{chat_id}\n")
        print(f"✅ Saved {len(admin_chat_ids)} admin chat IDs to file")
    except Exception as e:
        print(f"❌ Error saving admin chat IDs: {e}")

def add_admin_chat_id(chat_id):
    """Add a chat ID to admin list"""
    global admin_chat_ids
    admin_chat_ids.add(chat_id)
    save_admin_chat_ids()
    print(f"✅ Added chat ID {chat_id} to admin list")

def remove_admin_chat_id(chat_id):
    """Remove a chat ID from admin list"""
    global admin_chat_ids
    if chat_id in admin_chat_ids:
        admin_chat_ids.remove(chat_id)
        save_admin_chat_ids()
        print(f"✅ Removed chat ID {chat_id} from admin list")
        return True
    return False

def is_admin_chat_id(chat_id):
    """Check if a chat ID is in admin list"""
    return chat_id in admin_chat_ids

def is_bot_sender(sender_id):
    """Check if the sender is the bot itself"""
    return sender_id == bot_id

# Database Setup
DB_FILE = "moftbar_custom_gpt.db"
mode = "on"
fingilish_translation_enabled = True
default_token_text = (
                "🔍 در صورتی که تراکنش شما در وضعیت **در حال بررسی** قرار گیرد:\n"
                "⏳ سیستم ما به‌صورت خودکار **۴ بار** هر **۱۵ دقیقه** آن را بررسی می‌کند.\n"
                "✅ در صورت موفقیت‌آمیز بودن تراکنش، مبلغ به حساب کاربری شما اضافه خواهد شد.\n"
                "📌 توجه: تراکنش یا به حساب کاربری شما در سایت واریز می‌شود، یا از طرف درگاه به حساب بانکی شما بازمی‌گردد.\n"
                "⚠️ حالت بینابینی وجود ندارد و نیازی به پیگیری نیست.\n"
            )

adminConfirm = True  # By default admin mode (60 min wait time) 
channel_name = "@MFTQandA"
qa_channel_id = -1002492715418
# Variable for tracking user selection stage
#await user_states.clear()
approved_messages = set()  # Prevents duplicate AI approvals
tournament_channel = "@moftbarnews"
ticket_channel = "https://t.me/+URXQIdGCTWExNWYy"
ticket_channel_chat_ID =  -1002411014842
Support_channelchat_ID =  -4601865977
# Add near the top of your code, after other global variables
pinned_status_message_id = None  # Stores the message ID of the pinned status update message

# Admin management - using chat IDs instead of usernames
admin_chat_ids = set()  # Set to store admin chat IDs
ADMIN_FILE = "admin_chat_ids.txt"  # File to persist admin chat IDs
WAIT_TIME_FOR_ADMIN_LONG = 3600  # 60 minutes in seconds
WAIT_TIME_FOR_ADMIN = WAIT_TIME_FOR_ADMIN_LONG  # Wait for 60 minutes for admin response
WAIT_TIME_FOR_ADMIN_SHORT = 60

# New min/max wait time variables (in seconds)
WAIT_TIME_MIN = 300  # 5 minutes default minimum
WAIT_TIME_MAX = 3600  # 60 minutes default maximum
# At the beginning of the code, after existing global variables
auto_response_count = 0  # Counts the number of automatic responses since the last manual response
last_manual_response_time = 0  # Timestamp of the last manual response

# Fingilish translation state - default is ON
fingilish_translation_enabled = True




SENSITIVE_WORDS = ["کلاهبرداری", "دزدی", "حرومزاده", "تقلب","کس کشا", "تپان", "کیرم", "بی ناموس", "دزدها"]  # Add actual words


Q_KEYWORDS      = ["/Support", "/support", "ye Soal", "سوال", "یک سوال", "1", "/1",   "۱" , "1️⃣" ,  "سوال فنی" , "javab bede","ye soal dashtam",  "فنی" , "یک سوال دارم", "پیشنهاد"]
FINANCE_KEYWORDS = ["cashout", "", "تراکنش", "پیگیری", "خرید", "۲", "/2",   "2" , "2️⃣" ,  "deposite",  "deposit",  "کش اوت" , "استعلام","kharid",  "peygiri" , "کشوت",  "دیپوزیت",  "ریالی", "پیگیری تراکنش"]
TICKET_KEYWORDS = ["/Ticket", "/ticket", "Ticket", "ticket", "tiket", "3", "/3",   "۳" , "3️⃣" ,  "تیکت" , "poshtibani","poshtiban",  "پشتیبانی" , "پشتیبان"]


START_KEYWORDS = {"/start", "start","start/", "menu", "/menu", "استارت"}
BONOUS_WORDS = ["۴", "4","جایزه", "جوایز", "بونوس", "رایگان","چیپ رایگان", "چیپ رایکان", "دست برگردون", "gift" , "گیفت" ,"عیدی","کادو", "خوش آمدگویی", "هدیه", "bonous", "bonus"    ]  # Add actual words
# Define bonus and rewards information text

# Always Respond Keywords
ALWAYS_RESPOND_KEYWORDS = {
 
    "adress": "آدرس : moftbar.online",
    "آدرس": "آدرس: moftbar.online",
    "آدرس بدون فیلتر": "آدرس: https://mft-pk-gg.cc",

    "لینک": "آدرس: moftbar.online",
    "link": "آدرس: moftbar.online",
    "adres": "آدرس: moftbar.online",
    "آدرس میدی؟": "آدرس: moftbar.online",
    "لینک سایت": "آدرس: moftbar.online",

     "کانال": ": @moftbarnews",
     " کانال تلگرام": ": @moftbarnews",
     "kanal": ": @moftbarnews",
     "channel": ": @moftbarnews",
     "telegram": ": @moftbarnews",
     "kanal telegram": ": @moftbarnews",


    "slam": "سلام و عرض ادب \n",
    "Hi": "سلام و عرض ادب \n",
    "hi": "سلام و عرض ادب \n",

    "alo": "سلام و عرض ادب \n",
    "الو": "سلام و عرض ادب \n",
    "جناب": "سلام و عرض ادب \n",
    "هستید؟": "سلام و عرض ادب \n",


    "hello": "سلام و عرض ادب \n",
    "helo": "سلام و عرض ادب \n",

    "doroud": "درود بر شما \n",
    "درود":"درود بر شما \n",
    "وقت بخیر": "سلام و عرض ادب \n",
    "صبح بخیر": "سلام و عرض ادب \n",
    "روز بخیر": "سلام و عرض ادب \n",

    "slm": "سلام و عرض ادب \n",
    "salam": "سلام و عرض ادب \n", 
    "salam o khste nabashid": "سلام و عرض ادب \n", 

    "salm": "سلام و عرض ادب \n",
    "سلم": "سلام و عرض ادب \n",
    "سلام": "سلام و عرض ادب \n",
    "سلام مجدد": "سلام و عرض ادب \n",
    "سلام و درود": "سلام و عرض ادب \n",


    "خسته نباشید": "سلامت باشید\n",
    "سلام ادمین": "سلام و عرض ادب \n",
    "ادمین": "جان ادمین؟\n",

    "عزیز": "جان امرتون رو بفرمایید؟\n",
    "aziz": "جان امرتون رو بفرمایید؟\n",

    "آقای محترم": "جان امرتون رو بفرمایید؟\n",
    "khasteh nabashid": "سلامت باشید\n",
    "❤️": "❤️",
    "❤️❤️": "❤️❤️",
    "❤️❤️❤️": "❤️❤️❤️",
    "🙏": "🙏",
    "👍": "👍",
    "🌹": "🌹"




}


# Dictionary for storing original user IDs
pending_questions = {}  # Format: {message_id: user_id}
# Dictionary to store user tickets (as it already exists)
user_tickets = {}  # Format: {chat_id: {"ticket_id": ..., "ticket_status": ..., ...}}
# Dictionary to store conversation history
conversation_history = {}  # Format: {chat_id: [{"role": "user"|"bot", "content": str, "timestamp": float}, ...]}

# Lock for thread-safe access
conversation_history_lock = asyncio.Lock()



# New separate dictionary for pending screenshots (not nested in user_tickets)
pending_screenshots = {}  # Format: {screenshot_id: {"chat_id": ..., "message_id": ..., "photo_message_id": ..., ...}}
last_separator_message_id = None  # Stores the message ID of the last separator

last_gpt_call_time = 0  # Global variable to track the last GPT call time
DEFAULT_QA_ACCURACY = 65  # Default accuracy percentage for fuzzy Q&A search (range: 52-80)
class UserState:
    """
    Manages user conversation states and interaction tracking.
    Thread-safe implementation for handling multiple concurrent users.
    """
    def __init__(self):
        self.states = {}  # {chat_id: {"state": state, "last_interaction": timestamp}}
        self.lock = asyncio.Lock()  # Thread safety for concurrent access

    async def get(self, chat_id, default="technical_menu"):
        async with self.lock:
            entry = self.states.setdefault(chat_id, {"state": default, "last_interaction": time.time()})
            entry["last_interaction"] = time.time()
            return entry["state"]

    async def set(self, chat_id, state):
        async with self.lock:
            self.states[chat_id] = {"state": state, "last_interaction": time.time()}

    async def has(self, chat_id):
        async with self.lock:
            return chat_id in self.states

    async def clear(self):
        async with self.lock:
            self.states.clear()

    async def cleanup_stale_entries(self, timeout=24*60*60):  # 24 hours in seconds
        """
        Removes stale user state entries that haven't been accessed within the timeout period.
        This prevents memory leaks from inactive users.
        
        Args:
            timeout (int): Timeout in seconds (default: 24 hours)
        """
        async with self.lock:
            current_time = time.time()
            stale_chat_ids = [
                chat_id for chat_id, entry in self.states.items()
                if current_time - entry["last_interaction"] > timeout
            ]
            for chat_id in stale_chat_ids:
                del self.states[chat_id]
            print(f"🧹 DEBUG: Cleaned up {len(stale_chat_ids)} stale entries from user_states")

user_states = UserState()


async def cleanup_resolved_tickets():
    """
    Removes resolved tickets from memory to prevent accumulation.
    This function is called periodically to maintain clean memory usage.
    """
    resolved = [ticket_id for ticket_id, data in user_tickets.items() if data.get("ticket_status") == "resolved"]
    for ticket_id in resolved:
        del user_tickets[ticket_id]
        print(f"✅ DEBUG: Removed resolved ticket: {ticket_id}")
    if resolved:
        print(f"🧹 DEBUG: Cleanup completed - removed {len(resolved)} resolved tickets")



async def get_valid_peer(client, peer_id):
    """
    Safely resolves a peer ID to a valid Telegram peer object with retry logic.
    
    Args:
        client: TelegramClient instance
        peer_id: The peer ID to resolve (can be user ID, chat ID, or channel ID)
    
    Returns:
        Valid peer object or None if resolution fails
    """
    try:
        # Validate input parameters
        if not peer_id or (isinstance(peer_id, dict) and not peer_id):
            print(f"❌ DEBUG: Invalid peer ID detected: {peer_id}")
            return None
        
        # Check client connection status
        if not client.is_connected():
            print(f"❌ ERROR: TelegramClient is not connected. Cannot resolve peer ID {peer_id}.")
            return None
        
        # Retry logic for peer resolution
        for attempt in range(3):  # Retry up to 3 times
            try:
                peer = await client.get_input_entity(peer_id)
                print(f"✅ DEBUG: Successfully resolved peer for ID {peer_id} on attempt {attempt + 1}")
                return peer
            except Exception as e:
                print(f"⚠️ DEBUG: Attempt {attempt + 1} failed to get peer for ID {peer_id} - {e}")
                if attempt < 2:
                    await asyncio.sleep(2)  # Wait before retrying
                else:
                    raise
                    
    except ValueError as e:
        print(f"❌ DEBUG: Failed to get peer for ID {peer_id} - ValueError: {e}")
        return None
    except AttributeError as e:
        print(f"❌ DEBUG: Attribute error in get_input_entity for ID {peer_id} - {e}")
        return None
    except Exception as e:
        print(f"❌ ERROR: Unexpected error in get_valid_peer for ID {peer_id} - {e}")
        return None


def load_bonus_text_from_file(file_path="bonus_text.txt"):
    """
    Loads the BONUS_TEXT from a text file. If the file doesn't exist,
    returns the default BONUS_TEXT.
    
    Args:
        file_path (str): Path to the file from which the text is read.
    
    Returns:
        str: The loaded text or default BONUS_TEXT on error.
    """
    default_bonus_text = (
        "🎁 اطلاعات جوایز و آفرها:\n\n"
        "📅 جوایز 🃏 تاپ‌هند:\n"
        "   هر چهارشنبه، ساعت ۱۲:۰۰ ظهر پرداخت می‌شوند.\n\n"
        "🏅 جوایز لیگ تاپ ریک:\n"
        "     ساعت ۱۲:۰۰ ظهر تقدیم می‌گردند. به صورت ماهیانه و آخرین‌ شنبه هرماه، \n\n"
        "🎯 تورنمنت‌های روزانه:\n"
        "   به‌صورت خودکار با جوایز نفیس برگزار می‌شوند.\n\n"
        "⚠️ توجه:\n"
        "   رویال فلاش جایزه ندارد.\n"
        "   در حال حاضر هیچ جایزه دیگری فعال نیست. لطفاً در این مورد سوال نفرمایید.\n\n"
        "📌 نکته:\n"
        "   جوایز تنها از طریق سیستم لیگ و تورنمنت پرداخت می‌شوند، نه پشتیبانی فنی.\n\n"
        "📢 اخبار و جوایز:\n"
        "   برای اطلاعات بیشتر، به کانال تلگرام ما مراجعه کنید: @moftbarnews"
    )
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            loaded_text = f.read().strip()
            print(f"✅ DEBUG: BONUS_TEXT successfully loaded from {file_path}")
            return loaded_text if loaded_text else default_bonus_text
    except FileNotFoundError:
        print(f"⚠️ DEBUG: File {file_path} not found. Using default BONUS_TEXT.")
        return default_bonus_text
    except Exception as e:
        print(f"❌ ERROR: Could not load BONUS_TEXT from {file_path} - {e}")
        return default_bonus_text


def save_bonus_text_to_file(bonus_text, file_path="bonus_text.txt"):
    """
    Saves the BONUS_TEXT to a text file.
    
    Args:
        bonus_text (str): The text to be saved.
        file_path (str): Path to the file where the text will be saved.
        
    Returns:
        bool: True if successful, False otherwise.
    """
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(bonus_text)
        print(f"✅ DEBUG: BONUS_TEXT successfully saved to {file_path}")
        return True
    except Exception as e:
        print(f"❌ ERROR: Could not save BONUS_TEXT to {file_path} - {e}")
        return False



import re

def reverse_text(text: str) -> str:
    """
    Reverses the given text only if it is predominantly in Persian (Farsi) script.
    Leaves non-Persian text (e.g., Finglish, English, numbers) unchanged.

    :param text: The input string to check and possibly reverse.
    :return: The reversed string if predominantly Persian, otherwise the original string.
    """
    if not text or text.isspace():  # Handle empty or whitespace-only strings
        #print(f"DEBUG: Empty or whitespace-only text, returning as-is: '{text}'")
        return text

    # Define Persian Unicode range (U+0600 to U+06FF)
    persian_pattern = r'[\u0600-\u06FF]'
    
    # Count Persian characters in the text
    persian_chars = len(re.findall(persian_pattern, text))
    
    # Count total alphanumeric characters (exclude spaces and punctuation)
    # We only count letters and numbers for a more accurate ratio
    alphanumeric_chars = len(re.findall(r'[a-zA-Z0-9\u0600-\u06FF]', text))
    
    # Debug information
    #print(f"DEBUG: Text: '{text}'")
    #print(f"DEBUG: Persian chars: {persian_chars}")
    #print(f"DEBUG: Alphanumeric chars: {alphanumeric_chars}")
    
    # If there are no alphanumeric characters, return the text as-is
    if alphanumeric_chars == 0:
        #print(f"DEBUG: No alphanumeric chars, returning as-is: '{text}'")
        return text

    # Calculate the ratio of Persian characters to total alphanumeric characters
    persian_ratio = persian_chars / alphanumeric_chars if alphanumeric_chars > 0 else 0
    #print(f"DEBUG: Persian ratio: {persian_ratio}")

    # Only reverse if Persian characters make up at least 50% of the alphanumeric characters
    if persian_chars > 0 and persian_ratio >= 0.5:
        #print(f"DEBUG: Predominantly Persian text, reversing: '{text}'")
        return text[::-1]
    else:
        #print(f"DEBUG: Not predominantly Persian, returning as-is: '{text}'")
        return text






def generate_ticket_id():
    return f"#T{random.randint(1000, 9999)}"














        

def count_pending_items() -> tuple[int, int, int, int]:

    """
    Counts all pending tickets, screenshots, and tokens separately.
    Returns:
        tuple: (total_pending, pending_tickets, pending_tokens, pending_screenshots)
    """
    global pending_screenshots
    #print(f"DEBUG: Initial pending_screenshots dict: {pending_screenshots}")
    # Count regular tickets (non-token) - include both pending and auto_responded
    pending_tickets = sum(
        1 for chat_id, data in user_tickets.items()
        if (data.get("ticket_status") == "pending" or data.get("ticket_status") == "auto_responded") and not is_valid_token(data.get("ticket_text", ""))
    )
    
    # Count token-based tickets - include both pending and auto_responded
    pending_tokens = sum(
        1 for chat_id, data in user_tickets.items()
        if (data.get("ticket_status") == "pending" or data.get("ticket_status") == "auto_responded") and is_valid_token(data.get("ticket_text", ""))
    )
    
    # Count screenshots (length of the global pending_screenshots dictionary)
    pending_screenshots_count = len(pending_screenshots)
    
    # Total pending items
    total_pending = pending_tickets + pending_tokens + pending_screenshots_count
    
    #print(f"DEBUG: count_pending_items returning: {total_pending, pending_tickets, pending_tokens, pending_screenshots_count}")
    return total_pending, pending_tickets, pending_tokens, pending_screenshots_count



def generate_screenshot_id():
    return f"#S{random.randint(1000, 9999)}"

# In message_handler beim Verarbeiten eines Fotos:
screenshot_id = generate_screenshot_id()




def get_separator(status):
    global user_tickets,auto_response_count
    """
    Returns a separator string with color-coded status, separate counts for pending items,
    the ID of the oldest pending ticket or screenshot (e.g., #T1234 or #S5678), and timestamp.

    Args:
        status (str): The status of the message ('pending', 'resolved', 'canceled').

    Returns:
        str: A separator string with color indicator, pending counts, oldest ID, and timestamp.
    """
    # Get counts of pending items
    total_pending, pending_tickets, pending_tokens, pending_screenshots_count = count_pending_items()

    # Timestamp
    timestamp = datetime.datetime.now().strftime('%H:%M:%S')  # Format: HH:MM:SS

    # Determine the color based on pending items
    if total_pending == 0:
        color_emoji = "🟢"  # Green: No pending items
    elif pending_tickets == 0 and pending_tokens == 0 and pending_screenshots_count > 0:
        color_emoji = "🟣"  # Purple: Only screenshots pending
    else:
        color_emoji = "🔴"  # Red: At least one ticket or token pending

    # Build the counts display with emojis
    counts_display = (
        f"🎫{pending_tickets} "  # Tickets
        f"🔍{pending_tokens} "   # Tokens
        f"📷{pending_screenshots_count}"  # Screenshots
    )

    # Find the oldest pending ticket or screenshot
    oldest_id = None
    oldest_message_id = float('inf')  # Initialize with infinity to find the smallest ID

    # Check tickets
    for chat_id, data in user_tickets.items():
        if data.get("ticket_status") == "pending" or data.get("ticket_status") == "auto_responded":
            current_message_id = data.get("ticket_message_id", float('inf'))
            if current_message_id < oldest_message_id:
                oldest_message_id = current_message_id
                oldest_id = data.get("ticket_id")

    # Check screenshots with type checking
    if isinstance(pending_screenshots, dict):  # Ensure it's a dictionary
        for s_id, data in pending_screenshots.items():
            current_message_id = data.get("message_id", float('inf'))
            if current_message_id < oldest_message_id:
                oldest_message_id = current_message_id
                oldest_id = s_id
    else:
        print(f"ERROR: pending_screenshots is not a dictionary, it's {type(pending_screenshots)}: {pending_screenshots}")

    # Include the oldest ID if it exists, otherwise show "N/A"
    id_display = f"🚨: {oldest_id}" if oldest_id else "✅"

    # Combine everything into one line
    #return f"{color_emoji} [{counts_display}] - {id_display} - {timestamp} {color_emoji}"

    auto_responses_display = f"🤖{auto_response_count}" if auto_response_count > 0 else "🤖0"
    return f"{color_emoji} [{counts_display}]-{auto_responses_display}-{id_display} -{timestamp}"


from telethon.tl.functions.channels import EditTitleRequest

async def change_channel_title(client, channel_id, new_title):
    """
    Changes the title of a Telegram channel.
    
    Args:
        client: TelegramClient instance
        channel_id: The ID of the channel (int or string)
        new_title: The new title for the channel (string)
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Ensure the channel_id is valid and resolve it to a peer
        peer = await get_valid_peer(client, channel_id)
        if not peer:
            print(f"❌ ERROR: Invalid channel ID {channel_id}")
            return False

        # Use EditTitleRequest to change the channel title
        await client(EditTitleRequest(
            channel=peer,
            title=new_title
        ))
        print(f"✅ DEBUG: Channel title changed to '{new_title}' for channel ID {channel_id}")
        return True
    except Exception as e:
        print(f"❌ ERROR: Failed to change channel title - {e}")
        return False
    


# Add the lock object outside the function (at the beginning of the code, e.g. after user_tickets_lock)
separator_lock = asyncio.Lock()

async def send_admin_response_with_cleanup(client, chat_id, message, delete_command=True, command_message_id=None):
    """
    Send admin response and handle cleanup:
    1. Delete the command message if requested
    2. Send the response
    3. Delete the response after 30 seconds
    4. Refresh status bar
    """
    try:
        # Delete command message if requested
        if delete_command and command_message_id:
            try:
                await client.delete_messages(chat_id, command_message_id)
                print(f"✅ DEBUG: Deleted admin command message {command_message_id}")
            except Exception as e:
                print(f"⚠️ WARNING: Could not delete command message - {e}")
        
        # Send the response
        response_message = await safe_send_message(client, chat_id, message)
        
        # Schedule deletion of response after 30 seconds
        if response_message:
            asyncio.create_task(delete_message_after_delay(client, chat_id, response_message.id, 30))
        
        # Refresh status bar
        await manage_separator("pending")
        
        return response_message
        
    except Exception as e:
        print(f"❌ ERROR: Failed to send admin response with cleanup - {e}")
        return None

async def delete_message_after_delay(client, chat_id, message_id, delay_seconds):
    """Delete a message after a specified delay"""
    try:
        await asyncio.sleep(delay_seconds)
        await client.delete_messages(chat_id, message_id)
        print(f"✅ DEBUG: Auto-deleted response message {message_id} after {delay_seconds} seconds")
    except Exception as e:
        print(f"⚠️ WARNING: Could not auto-delete message {message_id} - {e}")

async def manage_separator(status):
    global last_separator_message_id
    async with separator_lock:  # Synchronisiere den Zugriff
        # Step 1: Edit the previous separator to gray dashes, if it exists
        if last_separator_message_id is not None:
            try:
                # Fetch the previous separator message
                previous_message = await client.get_messages(ticket_channel_chat_ID, ids=last_separator_message_id)
                if previous_message:
                    # Edit it to gray dashes
                    gray_separator = "➖➖➖➖➖➖➖➖➖➖➖➖"
                    if  gray_separator != previous_message.text:
                        await client.edit_message(ticket_channel_chat_ID, last_separator_message_id, gray_separator)
                else:
                    print(f"⚠️ DEBUG: Previous separator message (ID: {last_separator_message_id}) not found.")
                    last_separator_message_id = None  # Reset if not found
            except Exception as e:
                print(f"❌ ERROR: Failed to edit previous separator (ID: {last_separator_message_id}) - {e}")
                last_separator_message_id = None  # Reset on error

        # Step 2: Find the latest pending ticket or token based on the highest ticket_message_id
        latest_ticket_message_id = None
        max_message_id = -1

        new_title = "✅ Tickets✅ "     



        for chat_id, data in user_tickets.items():
            if data.get("ticket_status") == "pending":
                new_title = "🚨Pending Tickets🚨"



                current_message_id = data.get("ticket_message_id", -1)
                if current_message_id > max_message_id:
                    max_message_id = current_message_id
                    latest_ticket_message_id = current_message_id        
        
        #await change_channel_title(client, ticket_channel_chat_ID, new_title)

        # Step 3: Check if the last message is a status separator
        separator_text = get_separator(status)
        try:
            last_message = await client.get_messages(ticket_channel_chat_ID, limit=1)
            if last_message and isinstance(last_message, list) and len(last_message) > 0:
                last_msg = last_message[0]  # Get the first message
                if hasattr(last_msg, 'text') and last_msg.text and last_msg.text.strip().startswith(('🟢', '🟣', '🔴')):
                    print(f"DEBUG: Last message is a status separator, editing instead of sending new one: {last_msg.text}")
                    await client.edit_message(ticket_channel_chat_ID, last_msg.id, separator_text)
                    last_separator_message_id = last_msg.id
                    return
                else:
                    print(f"DEBUG: Last message is not a status separator or has no text")
            else:
                print(f"DEBUG: No messages found in ticket channel.")
        except Exception as e:
            print(f"❌ ERROR: Failed to fetch or edit last message in ticket channel - {e}")
            return  # Abort if an error occurs


        if latest_ticket_message_id:
            new_separator_message = await safe_send_message(client, ticket_channel_chat_ID, separator_text)
        else:
            new_separator_message = await safe_send_message(client, ticket_channel_chat_ID, separator_text)

        # Step 4: Update the last_separator_message_id (with desired error handling)
        if new_separator_message:
            last_separator_message_id = new_separator_message.id
        else:
            print("❌ ERROR: Failed to send new separator message!")
            last_separator_message_id = None  # Reset on failure



def ensure_ticket_exists(ticket_id, chat_id, user_message, ticket_message_id):
    if ticket_id not in user_tickets:
        user_tickets[ticket_id] = {
            "ticket_id": ticket_id,
            "chat_id": chat_id,
            "ticket_status": "pending",
            "ticket_text": user_message.raw_text,
            "ticket_message_id": ticket_message_id,
            "created_at": time.time(),
            "admin_response": None,
            "last_warning_time": 0,
            "pinned_warning_id": None,
        }
        print(f"🆕 Ticket {ticket_id} created.")




import os

async def safe_send_file(client, chat_id, file_path_or_id, **kwargs):
    if os.path.isfile(file_path_or_id) or file_path_or_id.startswith("CAAC"):
        try:
            await client.send_file(chat_id, file_path_or_id, **kwargs)
        except Exception as e:
            print(f"❌ ERROR: Failed to send file '{file_path_or_id}' - {e}")
    else:
        print(f"❌ ERROR: Invalid file or sticker ID: {file_path_or_id}")


async def has_pending_ticket(chat_id: int) -> bool:
    for ticket_id, ticket in user_tickets.items():
        print(f"[DEBUG] Checking ticket {ticket_id}: chat_id={ticket.get('chat_id')}, status={ticket.get('ticket_status')}")
        if ticket.get("chat_id") == chat_id and ticket.get("ticket_status") == "pending":
            print(f"✅ Found existing pending ticket: {ticket_id}")
            return True
    return False

async def safe_ticket(client, chat_id, message, event):
    """
    Safely creates a new ticket only if the user does not already have a pending one.
    Prevents duplicate ticket creation using a lock.

    Args:
        client: Telethon client instance.
        chat_id (int): User's chat ID.
        message: The user message (raw or event.message).
        event: The full event object (needed for message.id).
    """
    async with user_tickets_lock:
        if await has_pending_ticket(chat_id):
            await safe_send_message(client, chat_id,
                "⚠️ شما فقط می‌توانید یک تیکت فعال داشته باشید. لطفاً منتظر پاسخ ادمین باشید.")
        else:
            await send_ticket(event, chat_id, message, event.message.id)

    print(f"\nREAL TICKET DEBUG await user_states.get(chat_id) == {await user_states.get(chat_id)}")


import re

def extract_text_without_token(user_message):
    """
    Extrahiert die Token-Nummer (20-stellige Zahl, ggf. mit Leerzeichen) aus einer Nachricht
    und gibt den verbleibenden Text ohne die Token-Nummer zurück.

    Args:
        user_message (str): Der Text der Benutzernachricht

    Returns:
        str: Der Text ohne die Token-Nummer; wenn kein Token vorhanden ist, der Originaltext;
             wenn nur ein Token vorhanden ist, "بدون متن اضافی"
    """
    # Check if the message contains a token
    token_number = is_valid_token(user_message)
    if token_number:
        # Remove the token number from the message to get the remaining text
        non_token_text = re.sub(r'\b(?:\d\s*){20}\b', '', user_message).strip()
        if not non_token_text:
            non_token_text = "🔍 **استعلام توکن**\n\n"  # Fallback if no text remains
        print(f"✅ DEBUG: Extracted token: {token_number}, Remaining text: {non_token_text}")
        return non_token_text
    else:
        print(f"✅ DEBUG: No token found, returning original text: {user_message}")
        return user_message


async def send_ticket_test(chat_id, user_message, user_message_id):
    global default_token_text

    # Retrieve Moftbar username
    moftbar_username = get_user_by_chat_id(chat_id) or f"User{chat_id}"

    # Generate a unique ticket ID
    ticket_id = generate_ticket_id()
    print(f"✅ DEBUG: Created new ticket - Ticket ID: {ticket_id}, Chat ID: {chat_id}")

    # Check if the message contains a token
    token_number = is_valid_token(user_message)
    ticket_text = user_message
    non_token_text = user_message

    if token_number:
        # Remove the token number from the message to get the remaining text
        non_token_text = re.sub(r'\b(?:\d\s*){20}\b', '', user_message).strip()
        if not non_token_text:
            non_token_text = "درخواست استعلام  "  # Fallback if no text remains
        print(f"✅ DEBUG: Extracted token: {token_number}, Remaining text: {non_token_text}")

    # Format the ticket message
    if token_number:
        ai_response = default_token_text
        ticket_text = (
            f"🔍 **شماره توکن:** `{token_number}`\n"
            f"**☝️ TOKEN NUMBER ☝️**\n\n"

            f"📝 **متن :** `{non_token_text}`\n\n"
            f"👤 **نام کاربری:** `{moftbar_username}`\n\n"
            f"🎫 **شناسه تیکت:** `{ticket_id}`\n\n"
            f"🧠 **پاسخ آماده AI:**\n\n"
            f"```{ai_response}```\n\n"
            f"🔹 **Reply with 'ok' to confirm and send this response**\n\n"
            f"🕒 **زمان:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"🚨 **وضعیت:** در انتظار استعلام توکن"
        )
    else:
        ai_response = get_gpt_response(user_message, chat_id) or "در حال بررسی!"
        # Save conversation history for AI responses
        if ai_response and ai_response != "در حال بررسی!":
            save_conversation_to_db(chat_id, "user", user_message, datetime.datetime.now())
            save_conversation_to_db(chat_id, "bot", ai_response, datetime.datetime.now())
            print(f"✅ DEBUG: Saved conversation history for chat_id {chat_id}")
        ticket_text = (
            f"📝 **متن درخواست:**\n\n"
            f"```{user_message}```\n\n"
            f"👤 **نام کاربری:** `{moftbar_username}`\n\n"
            f"🎫 **شناسه تیکت:** `{ticket_id}`\n\n"
            f"🧠 **پاسخ پیشنهادی AI:**\n\n"
            f"```{ai_response}```\n\n"
            f"🔹 **Reply with 'ok' to confirm and send this response or send no to ignore**\n\n"
            f"🕒 **زمان:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"🚨 **وضعیت:** در انتظار بررسی ادمین"
        )

    # Send ticket to the ticket channel
    ticket_message = await safe_send_message(client, ticket_channel_chat_ID, ticket_text)
    if not ticket_message:
        print(f"❌ ERROR: Failed to send ticket message! ticket_text: {ticket_text}")
        return

    ticket_message_id = ticket_message.id

    # Store ticket details
    user_tickets[ticket_id] = {
        "chat_id": chat_id,
        "moftbar_username": moftbar_username,
        "ticket_id": ticket_id,
        "ticket_text": f"`{token_number}`\n {non_token_text}\n" if token_number else user_message,
        "ticket_status": "pending",
        "message_id": ticket_message_id,
        "user_message_id": user_message_id,
        "ticket_message_id": ticket_message_id,
        "ai_response": ai_response,
        "admin_response": None,
        "timers": None,
        "always_on": False,
        "never_on": False,
        "token_number": token_number  # Store token number separately if present
    }
    print(f"DEBUG: Added ticket for chat_id {chat_id}, new count: {count_pending_items()[0]}")

    # Inform the user about their Ticket ID
    await safe_send_message(client, chat_id,
                            f"مورد شما به پشتیبانی سایت جهت بررسی منتقل شد و ظرف {WAIT_TIME_FOR_ADMIN//60} دقیقه آینده به آن پاسخ داده خواهد شد.\n\n"
                            f"🆔 **Ticket-ID:** \n{ticket_id}\n")

    # Add separator after ticket
    await manage_separator("pending")

    # Start a timer for AI auto-response
    if ticket_id in user_tickets and user_tickets[ticket_id].get("ticket_message_id") == ticket_message_id:
        user_tickets[ticket_id]["timers"] = asyncio.create_task(


            await wait_for_admin_response(event, ticket_data, is_screenshot=False)
            #wait_for_admin_response(
            #    question_id=user_message_id,
            #    ai_response=ai_response,
            #    user_chat_id=chat_id,
            #    ticket_message_id=ticket_message_id,
            #    ticket_id=ticket_id
            #)
        )
        print(f"✅ DEBUG: Stored and verified valid ticket_message_id {ticket_message_id} for Ticket {ticket_id}")
    else:
        print(f"❌ ERROR: ticket_message_id was not correctly stored! Expected {ticket_message_id}, found {user_tickets.get(chat_id, {}).get('ticket_message_id')}")



async def send_ticket(event, chat_id, message, message_id):
    """
    Sends a ticket to the ticket channel using templates and waits for admin response.
    
    Args:
        event: The Telethon event object.
        chat_id: The ID of the chat where the message originated.
        message: The message object.
        message_id: The ID of the original message.
    """
    # Generate a unique ticket ID
    ticket_id = generate_ticket_id()

    # Get the username
    try:
        user = await client.get_entity(chat_id)
        moftbar_username = get_user_by_chat_id(chat_id) or f"User{chat_id}"
        telegram_username = f"@{user.username}" if getattr(user, "username", None) else f"User_{chat_id}"
    except Exception as e:
        print(f"DEBUG: Could not fetch username for chat_id {chat_id}: {e}")
        moftbar_username = "UnknownUser"
        telegram_username = f"User_{chat_id}"

    # Extract ticket text
    user_message = message or ""

    # Determine ticket type
    is_token = is_valid_token(user_message)
    token_text = extract_text_without_token(user_message)
    card_number = is_valid_cardnumber(user_message)
    trx_wallet = is_valid_trx_wallet(user_message)
    
    # Select template key based on ticket type
    if is_token:
        template_key = "ticket_token"
    elif card_number:
        template_key = "ticket_card"
    elif trx_wallet:
        template_key = "ticket_trx_wallet"
    else:
        template_key = "ticket_text"

    # Set AI response based on ticket type
    if is_token:
        default_token_text = (
            "🔍 در صورتی که تراکنش شما در وضعیت **در حال بررسی** قرار گیرد:\n"
            "⏳ سیستم ما به‌صورت خودکار **۴ بار** هر **۱۵ دقیقه** آن را بررسی می‌کند.\n"
            "✅ در صورت موفقیت‌آمیز بودن تراکنش، مبلغ به حساب کاربری شما اضافه خواهد شد.\n"
            "📌 توجه: تراکنش یا به حساب کاربری شما در سایت واریز می‌شود، یا از طرف درگاه به حساب بانکی شما بازمی‌گردد.\n"
            "⚠️ حالت بینابینی وجود ندارد و نیازی به پیگیری نیست.\n"
        )
        ai_response = default_token_text
    elif card_number:
        default_token_text = ("📌 شماره کارت دریافت شد و به ادمین منتقل گردید\n"
            "⏳ منتظر پاسخ استعلام بمانید و لطفاً از **پیگیری مجدد** خودداری کنید!")
        ai_response = default_token_text
    elif trx_wallet:
        default_token_text = ("✅ آدرس کیف پول TRX دریافت شد و به ادمین منتقل گردید\n"
            "⏳ منتظر پاسخ استعلام بمانید و لطفاً از **پیگیری مجدد** خودداری کنید!")
        ai_response = default_token_text
    else:
        ai_response = get_gpt_response(user_message, chat_id) or "در حال بررسی!"
        # Save conversation history for AI responses
        if ai_response and ai_response != "در حال بررسی!":
            save_conversation_to_db(chat_id, "user", user_message, datetime.datetime.now())
            save_conversation_to_db(chat_id, "bot", ai_response, datetime.datetime.now())
            print(f"✅ DEBUG: Saved conversation history for chat_id {chat_id}")

    # Get real conversation history from database (user-admin conversations)
    conversation_history_list = load_conversation_from_db(chat_id)
    separate_history = format_chat_history_separate_post(conversation_history_list, telegram_username)
    
    # Create ticket_data dictionary
    ticket_data = {
        "ticket_id": ticket_id,
        "chat_id": chat_id,
        "moftbar_username": moftbar_username,
        "telegram_username": telegram_username,
        "user_message_id": message_id,
        "message_id": None,  # Will be set after sending to ticket channel
        "ticket_message_id": None,  # Will be set after sending to ticket channel
        "ticket_text": user_message,
        "ai_response": ai_response,  # Set if AI response is generated
        "ai_response_message_id": None,  # Set if AI response is sent
        "ticket_status": "pending",  # Initial status
        "token_number": is_token if is_token else None,
        "card_number": card_number if card_number else None,
        "trx_wallet": trx_wallet if trx_wallet else None,
        "chat_history": None,  # No longer needed in ticket since posted separately
        "admin_response": None,
        "timers": None,
        "always_on": False,
        "never_on": False
    }

    # First, send chat history as separate post if available
    history_message = None
    if separate_history:
        try:
            # Check length to ensure it's not too long
            if len(separate_history) <= 4000:  # Telegram limit is 4096, leave some buffer
                history_message = await client.send_message(ticket_channel_chat_ID, separate_history)
                print(f"✅ DEBUG: Chat history posted before ticket {ticket_id}")
            else:
                # If too long, truncate it
                truncated_history = separate_history[:3900] + "\n... (truncated due to length)"
                history_message = await client.send_message(ticket_channel_chat_ID, truncated_history)
                print(f"⚠️ DEBUG: Chat history truncated for ticket {ticket_id}")
        except Exception as e:
            print(f"❌ ERROR: Failed to send chat history: {e}")

    # Generate initial ticket message using template
    try:
        update_text = await generate_update_text(
            template_key,
            ticket_id=ticket_id,
            moftbar_username=moftbar_username,
            telegram_username=telegram_username,
            ticket_text=user_message if not is_token else "",
            token_number=is_token if is_token else None,
            non_token_text=token_text if is_token else None,
            card_number=card_number if card_number else None,
            trx_wallet=trx_wallet if trx_wallet else None,
            chat_history=None,  # No longer needed since posted separately
            response_text=default_token_text if is_token else ai_response,
            status_text="⏳ **وضعیت:** در انتظار پاسخ ادمین"
        )
        
        # Check ticket length and truncate if necessary
        if len(update_text) > 4000:
            print(f"⚠️ DEBUG: Ticket {ticket_id} is too long ({len(update_text)} chars), truncating...")
            # Truncate the ticket text but keep essential info
            update_text = update_text[:3900] + "\n\n... (ticket truncated due to length limit)"
            
    except Exception as e:
        print(f"❌ ERROR: Failed to generate ticket text: {e}")
        update_text = (
            f"Ticket ID: {ticket_id}\n"
            f"Username: {moftbar_username}\n"
            f"Text: {user_message[:200]}...\n"  # Truncate user message
            f"Status: ⏳ Waiting for admin response"
        )

    # Send ticket to ticket channel
    try:
        ticket_message = await client.send_message(ticket_channel_chat_ID, update_text)
        ticket_data["message_id"] = ticket_message.id
        ticket_data["ticket_message_id"] = ticket_message.id
        print(f"✅ DEBUG: Ticket {ticket_id} posted successfully (length: {len(update_text)} chars)")
    except Exception as e:
        print(f"❌ ERROR: Failed to send ticket to channel: {e}")
        return

    # Store ticket data in user_tickets
    user_tickets[ticket_id] = ticket_data
    print(f"DEBUG: Created ticket {ticket_id} for user {moftbar_username}")

    # ✅ Inform the user about their Ticket ID with beautiful formatting
    user_notification = (
        f"🎫 **تیکت شما ایجاد شد!** ✅\n\n"
        f"📋 **جزئیات تیکت:**\n"
        f"🆔 **شناسه:** `{ticket_id}`\n"
        f"⏱️ **زمان پاسخ:** حداکثر {WAIT_TIME_FOR_ADMIN//60} دقیقه\n"
        f"📝 **وضعیت:** در حال بررسی توسط تیم پشتیبانی\n\n"
        f"💡 **نکته:** لطفاً این شناسه را برای پیگیری نگه دارید.\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    await safe_send_message(client, chat_id, user_notification)
    
    # ✅ Add separator after ticket
    await manage_separator("pending")
    
    # ✅ Start a timer for AI auto-response
    if ticket_id in user_tickets and user_tickets[ticket_id].get("message_id") == ticket_data["message_id"]:
        # Start the timer task for this ticket
        asyncio.create_task(start_ticket_timer(ticket_data))
        print(f"✅ DEBUG: Timer started for ticket_message_id {ticket_data['message_id']} for Ticket {ticket_id}")
    else:
        print(f"❌ ERROR: ticket_message_id was not correctly stored! Expected {ticket_data['message_id']}, found {user_tickets.get(ticket_id, {}).get('message_id')}")









def is_only_numbers(message):
    return message.replace(" ", "").isdigit()


def is_valid_token(text):
    """
    Searches for a sequence of exactly 20 digits (ignoring spaces between them) within the text.
    Returns the raw 20-digit string without spaces if found, otherwise None.
    
    Args:
        text (str): The input text to search for a token.
    
    Returns:
        str | None: A string of exactly 20 digits if found, otherwise None.
    """
    # Find all sequences of digits separated by spaces
    # Use regex to match sequences of digits with optional spaces
    pattern = r'\b(?:\d\s*){20}\b'
    matches = re.finditer(pattern, text)

    for match in matches:
        # Extract the matched sequence
        matched_text = match.group(0)
        # Remove all non-digits (like spaces) to get the pure digit sequence
        cleaned_digits = re.sub(r'\D', '', matched_text)
        
        # Check if we have exactly 20 digits
        if len(cleaned_digits) == 20 and cleaned_digits.isdigit():
            return cleaned_digits  # Return the raw 20 digits without spaces
    
    return None


# Modified is_valid_cardnumber to avoid matching 20-digit tokens
def is_valid_cardnumber(text):
    """
    Searches for a sequence of exactly 16 digits (ignoring spaces) within the text.
    Ensures it does not match 20-digit tokens.
    
    Args:
        text (str): The input text to search for a card number.
    
    Returns:
        str | None: A string of exactly 16 digits if found, otherwise None.
    """
    pattern = r'\b(?:\d\s*){16}\b(?!\s*\d)'  # Match exactly 16 digits, not followed by more digits
    matches = re.finditer(pattern, text)
    for match in matches:
        matched_text = match.group(0)
        cleaned_digits = re.sub(r'\D', '', matched_text)
        if len(cleaned_digits) == 16 and cleaned_digits.isdigit():
            # Ensure it's not a 20-digit token
            if not is_valid_token(text):
                return cleaned_digits
    return None


def is_valid_trx_wallet(text):
    """
    Validates TRX (Tron) wallet addresses.
    TRX addresses start with 'T' and are 34 characters long.
    
    Args:
        text (str): The input text to search for a TRX wallet address.
    
    Returns:
        str | None: A valid TRX wallet address if found, otherwise None.
    """
    # TRX wallet pattern: starts with 'T', followed by 33 alphanumeric characters
    pattern = r'\bT[A-Za-z0-9]{33}\b'
    matches = re.finditer(pattern, text)
    
    for match in matches:
        wallet_address = match.group(0)
        # Additional validation: check if it's a valid TRX address format
        if wallet_address.startswith('T') and len(wallet_address) == 34:
            return wallet_address
    
    return None


async def get_recent_chat_history(chat_id, limit=5):
    """
    Retrieves recent chat history for a user, excluding stickers and media.
    
    Args:
        chat_id (int): The chat ID to get history for
        limit (int): Number of recent messages to retrieve
    
    Returns:
        list: List of recent text messages
    """
    try:
        # Get recent messages from the chat
        messages = await client.get_messages(chat_id, limit=limit * 2)  # Get more to filter out non-text
        
        recent_messages = []
        if messages and isinstance(messages, (list, tuple)):  # Check if messages is not None and is iterable
            for message in messages:
                # Only include text messages, exclude stickers, photos, etc.
                if message and hasattr(message, 'text') and message.text and not message.sticker and not message.photo:
                    # Clean the message text
                    clean_text = message.text.strip()
                    if clean_text and len(clean_text) > 0:
                        recent_messages.append({
                            "text": clean_text,
                            "timestamp": message.date,
                            "message_id": message.id
                        })
                    
                    # Stop when we have enough text messages
                    if len(recent_messages) >= limit:
                        break
        
        return recent_messages
        
    except Exception as e:
        print(f"❌ ERROR: Failed to get chat history for {chat_id}: {e}")
        return []


def format_chat_history_for_ticket(chat_history):
    """
    Formats chat history for display in ticket with compact format.
    
    Args:
        chat_history (list): List of recent messages
    
    Returns:
        str: Formatted chat history text (compact)
    """
    if not chat_history:
        return None  # Return None if no history
    
    # Compact format to save space
    formatted_history = "📝 **آخرین ۵ پیام:**\n"
    
    for i, msg in enumerate(chat_history, 1):
        timestamp = msg["timestamp"].strftime("%H:%M") if msg["timestamp"] else "??:??"
        # Very short truncation to keep it compact
        text = msg["text"][:60] + "..." if len(msg["text"]) > 60 else msg["text"]
        formatted_history += f"{i}. {timestamp}: {text}\n"
    
    return formatted_history


def format_chat_history_separate_post(conversation_history, telegram_username=""):
    """
    Formats conversation history for a separate post before the ticket.
    Shows 5 real user-admin conversations from manual ticket responses.
    Filters out automated responses, stickers, and AI answers.
    
    Args:
        conversation_history (list): List of conversation history from database
        telegram_username (str): Telegram username to display for user messages
    
    Returns:
        str: Formatted conversation history for separate post
    """
    if not conversation_history:
        return "💬 **تاریخچه چت** 📱\n━━━━━━━━━━━━━━━━━━━━\n\n📝 **هیچ گفتگوی واقعی یافت نشد**"
    
    # Filter out automated responses, stickers, and AI answers
    def is_real_conversation(msg):
        content = msg.get("content", "").lower()
        role = msg.get("role", "").lower()
        
        # Skip automated system messages
        automated_keywords = [
            "در حال بررسی", "پاسخ خودکار", "auto-response", "ai response",
            "سیستم", "system", "bot", "ربات", "خودکار", "automated",
            "تیکت", "ticket", "شناسه", "id", "وضعیت", "status",
            "برای منوی اصلی start", "start/", "منوی اصلی"
        ]
        
        # Skip sticker messages
        if "[sticker sent:" in content or "sticker" in content:
            return False
            
        # Skip photo messages
        if "[photo sent:" in content or "photo" in content:
            return False
            
        # Skip automated responses
        for keyword in automated_keywords:
            if keyword in content:
                return False
                
        # Skip very short messages (likely system messages)
        if len(content.strip()) < 5:
            return False
            
        # Skip messages that are just emojis or symbols
        if content.strip() in ["⏳", "✅", "❌", "⚠️", "📝", "🔵", "🟢", "📱", "💬"]:
            return False
            
        # Only include user and bot (admin) messages
        if role not in ["user", "bot"]:
            return False
            
        return True
    
    # Filter conversation history to only include real conversations
    real_messages = [msg for msg in conversation_history if is_real_conversation(msg)]
    
    if not real_messages:
        return "💬 **تاریخچه چت** 📱\n━━━━━━━━━━━━━━━━━━━━\n\n📝 **هیچ گفتگوی واقعی یافت نشد**"
    
    # Compact chat-like format
    formatted_history = "💬 **تاریخچه چت** 📱\n"
    formatted_history += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    # Take the last 10 messages (more compact)
    recent_messages = real_messages[-10:] if len(real_messages) >= 10 else real_messages
    
    for msg in recent_messages:
        # Convert timestamp to readable format
        timestamp_obj = msg.get("timestamp")
        if isinstance(timestamp_obj, str):
            try:
                import datetime
                timestamp_obj = datetime.datetime.fromisoformat(timestamp_obj.replace('Z', '+00:00'))
            except:
                timestamp_obj = None
        
        timestamp = timestamp_obj.strftime("%H:%M") if timestamp_obj else "??:??"
        content = msg.get("content", "")
        text = content[:150] + "..." if len(content) > 150 else content
        
        # Compact chat format: username/message on same line
        if msg.get("role") == "user":
            # User message - show actual Telegram username
            user_display = f"@{telegram_username}" if telegram_username else "User"
            formatted_history += f"**{user_display}** ({timestamp}): {text}\n\n"
        else:
            # Admin message
            formatted_history += f"**Admin** ({timestamp}): {text}\n\n"
    
    formatted_history += "━━━━━━━━━━━━━━━━━━━━\n📝 **پایان تاریخچه چت**"
    return formatted_history


import asyncio


async def start_ticket_timer(ticket_data):
    """
    Starts a timer for a ticket and handles auto-response after timeout.
    This function runs independently and doesn't wait for admin replies.
    """
    global auto_response_count, WAIT_TIME_FOR_ADMIN, WAIT_TIME_MIN, WAIT_TIME_MAX
    ticket_id = ticket_data.get("ticket_id")
    original_chat_id = ticket_data.get("chat_id")
    moftbar_username = ticket_data.get("moftbar_username", "UnknownUser")
    telegram_username = ticket_data.get("telegram_username", "")
    original_message_id = ticket_data.get("user_message_id")
    ticket_message_id = ticket_data.get("message_id")
    original_ticket_text = ticket_data.get("ticket_text", "")
    
    # Timer setup for auto-response - use current WAIT_TIME_FOR_ADMIN value
    current_wait_time = WAIT_TIME_FOR_ADMIN
    REMINDER_TIME = current_wait_time - (current_wait_time/20)   # 95% of wait time
    DEBUG_INTERVAL = 5    # Debug print every 5 seconds
    print(f"⏳ DEBUG: Timer started for Ticket {ticket_id}")
    print(f"⏳ DEBUG: REMINDER_TIME= {REMINDER_TIME}s -- WAIT_TIME_FOR_ADMIN = {current_wait_time}s -- DEBUG_INTERVAL = {DEBUG_INTERVAL}s")

    elapsed_time = 0
    print(f"⏳ DEBUG: Waiting {current_wait_time//60} minutes for admin response for Ticket {ticket_id}...")
    
    # Send initial waiting message to user
    await asyncio.sleep(1)
    await safe_send_message(client, original_chat_id, f"⏳...")

    # First phase: Wait until reminder time
    while elapsed_time < REMINDER_TIME:
        print(f"⏳ DEBUG: Phase 1 - elapsed_time: {elapsed_time}s / {REMINDER_TIME}s ({(elapsed_time/REMINDER_TIME)*100:.1f}%) - Ticket {ticket_id}")

        # Check if ticket was handled by an admin before the reminder
        if ticket_id in user_tickets and user_tickets[ticket_id].get("ticket_status") != "pending":
            print(f"✅ DEBUG: Ticket {ticket_id} was handled by an admin before reminder. Exiting timer.")
            await manage_separator("resolved")
            return
            
        await asyncio.sleep(DEBUG_INTERVAL)
        elapsed_time += DEBUG_INTERVAL

    # Send reminder to admin channel
    if ticket_id in user_tickets and user_tickets[ticket_id].get("ticket_status") == "pending":
        reminder_message = await safe_send_message(client, ticket_channel_chat_ID,
            f"⏰ **یادآوری به ادمین‌ها**: تیکت با شناسه {ticket_id} هنوز پاسخ داده نشده است. {(current_wait_time-REMINDER_TIME)//60} دقیقه تا پاسخ خودکار AI باقی مانده است.")
        await asyncio.sleep(5)
        if reminder_message:
            await reminder_message.delete()

    print(f"⏳ DEBUG: Phase 2 starting - elapsed_time: {elapsed_time}s / {current_wait_time}s ({(elapsed_time/current_wait_time)*100:.1f}%)")

    # Second phase: Wait until final timeout
    while elapsed_time < current_wait_time:
        print(f"⏳ DEBUG: Phase 2 - elapsed_time: {elapsed_time}s / {current_wait_time}s ({(elapsed_time/current_wait_time)*100:.1f}%) - Time left: {current_wait_time - elapsed_time}s - Ticket {ticket_id}")

        # Check if ticket was handled by an admin before the final timeout
        if ticket_id in user_tickets and user_tickets[ticket_id].get("ticket_status") != "pending":
            print(f"✅ DEBUG: Ticket {ticket_id} was handled by an admin before auto-reply. Exiting timer.")
            await manage_separator("resolved")
            return

        client.action(original_chat_id, "typing")
        await asyncio.sleep(DEBUG_INTERVAL)
        elapsed_time += DEBUG_INTERVAL

    # Auto-response after timeout
    if ticket_id in user_tickets and user_tickets[ticket_id].get("ticket_status") == "pending":
        print(f"⏰ DEBUG: Timeout reached ({current_wait_time}s) - sending auto-response for Ticket {ticket_id}")
        
        # Handle ticket auto-response
        ai_response = ticket_data.get("ai_response", "در حال بررسی!")
        await asyncio.sleep(2)
        ai_response_message = await safe_send_message(client, original_chat_id, ai_response, reply_to=original_message_id)
        
        if ai_response_message:
            user_tickets[ticket_id]["ai_response_message_id"] = ai_response_message.id
            user_tickets[ticket_id]["ticket_status"] = "auto_responded"
            user_tickets[ticket_id]["admin_response"] = ai_response
            auto_response_count += 1
            # WAIT_TIME_FOR_ADMIN bleibt unverändert - AI Antwort ändert nicht die Wartezeit
            print(f"✅ DEBUG: auto_response_count = {auto_response_count}")

            # Update ticket message
            updated_ticket_text = (
                f"```{user_tickets[ticket_id]['ticket_text']}```\n"
                f"☝️☝️☝️☝️☝️☝️\n\n"
                f"👤 **Username:** : ```{moftbar_username}``` \n\n telegram: {telegram_username}\n\n"
                f"🎫 **شناسه تیکت:**\n{ticket_id}\n\n"
                f"📝 **ارسال شده: پاسخ خودکار:**\n\n```{ai_response}```\n"
                f"\n✅ **تیکت پس از اتمام زمان بطور خودکار پاسخ داده شد✅**\n"
            )
            await client.edit_message(ticket_channel_chat_ID, ticket_message_id, updated_ticket_text)

        await manage_separator("resolved")


async def start_screenshot_timer(screenshot_data):
    """
    Starts a timer for a screenshot and handles auto-ignore after timeout.
    This function runs independently and doesn't wait for admin replies.
    """
    global WAIT_TIME_FOR_ADMIN, WAIT_TIME_MIN, WAIT_TIME_MAX
    screenshot_id = screenshot_data.get("screenshot_id")
    chat_id = screenshot_data.get("chat_id")
    message_id = screenshot_data.get("message_id")
    moftbar_username = screenshot_data.get("moftbar_username", "UnknownUser")
    original_message_id = screenshot_data.get("original_message_id")
    
    # Timer setup for auto-ignore - use current WAIT_TIME_FOR_ADMIN value
    current_wait_time = WAIT_TIME_FOR_ADMIN
    REMINDER_TIME = current_wait_time - (current_wait_time/20)   # 95% of wait time
    DEBUG_INTERVAL = 5    # Debug print every 5 seconds
    print(f"⏳ DEBUG: Timer started for Screenshot {screenshot_id}")
    print(f"⏳ DEBUG: REMINDER_TIME= {REMINDER_TIME}s -- WAIT_TIME_FOR_ADMIN = {current_wait_time}s -- DEBUG_INTERVAL = {DEBUG_INTERVAL}s")

    elapsed_time = 0
    print(f"⏳ DEBUG: Waiting {current_wait_time//60} minutes for admin response for Screenshot {screenshot_id}...")
    
    # Send initial waiting message to user
    await asyncio.sleep(1)
    await safe_send_message(client, chat_id, f"⏳...")

    # First phase: Wait until reminder time
    while elapsed_time < REMINDER_TIME:
        print(f"⏳ DEBUG: Phase 1 - elapsed_time: {elapsed_time}s / {REMINDER_TIME}s ({(elapsed_time/REMINDER_TIME)*100:.1f}%) - Screenshot {screenshot_id}")

        # Check if screenshot was handled by an admin before the reminder
        if screenshot_id not in pending_screenshots:
            print(f"✅ DEBUG: Screenshot {screenshot_id} was handled by an admin before reminder. Exiting timer.")
            await manage_separator("resolved")
            return
            
        await asyncio.sleep(DEBUG_INTERVAL)
        elapsed_time += DEBUG_INTERVAL

    # Send reminder to admin channel
    if screenshot_id in pending_screenshots:
        reminder_message = await safe_send_message(client, ticket_channel_chat_ID,
            f"⏰ **یادآوری به ادمین‌ها**: اسکرین‌شات با شناسه {screenshot_id} هنوز پاسخ داده نشده است. {(current_wait_time-REMINDER_TIME)//60} دقیقه تا نادیده گرفتن خودکار باقی مانده است.")
        await asyncio.sleep(5)
        if reminder_message:
            await reminder_message.delete()

    print(f"⏳ DEBUG: Phase 2 starting - elapsed_time: {elapsed_time}s / {current_wait_time}s ({(elapsed_time/current_wait_time)*100:.1f}%)")

    # Second phase: Wait until final timeout
    while elapsed_time < current_wait_time:
        print(f"⏳ DEBUG: Phase 2 - elapsed_time: {elapsed_time}s / {current_wait_time}s ({(elapsed_time/current_wait_time)*100:.1f}%) - Time left: {current_wait_time - elapsed_time}s - Screenshot {screenshot_id}")

        # Check if screenshot was handled by an admin before the final timeout
        if screenshot_id not in pending_screenshots:
            print(f"✅ DEBUG: Screenshot {screenshot_id} was handled by an admin before auto-ignore. Exiting timer.")
            await manage_separator("resolved")
            return

        client.action(chat_id, "typing")
        await asyncio.sleep(DEBUG_INTERVAL)
        elapsed_time += DEBUG_INTERVAL

    # Auto-ignore after timeout
    if screenshot_id in pending_screenshots:
        print(f"⏰ DEBUG: Timeout reached ({current_wait_time}s) - auto-ignoring Screenshot {screenshot_id}")
        
        # Handle screenshot auto-ignore
        await auto_ignore_screenshot(screenshot_id, chat_id, message_id, moftbar_username, original_message_id)
        await manage_separator("resolved")


async def wait_for_admin_response(event, ticket_data, is_screenshot=False):
    """
    Waits for an admin response and updates the ticket or screenshot using templates.
    """
    global auto_response_count, last_manual_response_time, WAIT_TIME_FOR_ADMIN, WAIT_TIME_MIN, WAIT_TIME_MAX
    ticket_id = ticket_data.get("ticket_id")
    original_chat_id = ticket_data.get("chat_id")
    moftbar_username = ticket_data.get("moftbar_username", "UnknownUser")
    original_message_id = ticket_data.get("user_message_id")
    ticket_message_id = ticket_data.get("message_id")
    original_ticket_text = ticket_data.get("ticket_text", "")
    is_token = bool(is_valid_token(original_ticket_text))
    is_card = bool(is_valid_cardnumber(original_ticket_text)) if not is_token else False
    trx_wallet = bool(is_valid_trx_wallet(original_ticket_text)) if not is_token and not is_card else False

    # Timer setup for auto-response - use current WAIT_TIME_FOR_ADMIN value
    current_wait_time = WAIT_TIME_FOR_ADMIN
    REMINDER_TIME = current_wait_time - (current_wait_time/20)   # 95% of wait time
    DEBUG_INTERVAL = 5    # Debug print every 5 seconds
    print(f"⏳ DEBUG: Timer started for {'Screenshot' if is_screenshot else 'Ticket'} {ticket_id}")
    print(f"⏳ DEBUG: REMINDER_TIME= {REMINDER_TIME}s -- WAIT_TIME_FOR_ADMIN = {current_wait_time}s -- DEBUG_INTERVAL = {DEBUG_INTERVAL}s")

    elapsed_time = 0
    print(f"⏳ DEBUG: Waiting {current_wait_time//60} minutes for admin response for {'Screenshot' if is_screenshot else 'Ticket'} {ticket_id}...")
    
    # Send initial waiting message to user
    await asyncio.sleep(1)
    await safe_send_message(client, original_chat_id, f"⏳...")

    # First phase: Wait until reminder time
    while elapsed_time < REMINDER_TIME:
        print(f"⏳ DEBUG: Phase 1 - elapsed_time: {elapsed_time}s / {REMINDER_TIME}s ({(elapsed_time/REMINDER_TIME)*100:.1f}%) - {'Screenshot' if is_screenshot else 'Ticket'} {ticket_id}")

        # Check if ticket/screenshot was handled by an admin before the reminder
        if not is_screenshot and ticket_id in user_tickets and user_tickets[ticket_id].get("ticket_status") != "pending":
            print(f"✅ DEBUG: Ticket {ticket_id} was handled by an admin before reminder. Exiting wait task.")
            await manage_separator("resolved")
            return
        elif is_screenshot and ticket_id not in pending_screenshots:
            print(f"✅ DEBUG: Screenshot {ticket_id} was handled by an admin before reminder. Exiting wait task.")
            await manage_separator("resolved")
            return
            
        await asyncio.sleep(DEBUG_INTERVAL)
        elapsed_time += DEBUG_INTERVAL

    # Send reminder to admin channel
    if (not is_screenshot and ticket_id in user_tickets and user_tickets[ticket_id].get("ticket_status") == "pending") or \
       (is_screenshot and ticket_id in pending_screenshots):
        reminder_message = await safe_send_message(client, ticket_channel_chat_ID,
            f"⏰ **یادآوری به ادمین‌ها**: {'اسکرین‌شات' if is_screenshot else 'تیکت'} با شناسه {ticket_id} هنوز پاسخ داده نشده است. {(current_wait_time-REMINDER_TIME)//60} دقیقه تا پاسخ خودکار AI باقی مانده است.")
        await asyncio.sleep(5)
        if reminder_message:
            await reminder_message.delete()

    print(f"⏳ DEBUG: Phase 2 starting - elapsed_time: {elapsed_time}s / {current_wait_time}s ({(elapsed_time/current_wait_time)*100:.1f}%)")

    # Second phase: Wait until final timeout
    while elapsed_time < current_wait_time:
        print(f"⏳ DEBUG: Phase 2 - elapsed_time: {elapsed_time}s / {current_wait_time}s ({(elapsed_time/current_wait_time)*100:.1f}%) - Time left: {current_wait_time - elapsed_time}s - {'Screenshot' if is_screenshot else 'Ticket'} {ticket_id}")

        # Check if ticket/screenshot was handled by an admin before the final timeout
        if not is_screenshot and ticket_id in user_tickets and user_tickets[ticket_id].get("ticket_status") != "pending":
            print(f"✅ DEBUG: Ticket {ticket_id} was handled by an admin before auto-reply. Exiting wait task.")
            await manage_separator("resolved")
            return
        elif is_screenshot and ticket_id not in pending_screenshots:
            print(f"✅ DEBUG: Screenshot {ticket_id} was handled by an admin before auto-reply. Exiting wait task.")
            await manage_separator("resolved")
            return

        client.action(original_chat_id, "typing")
        await asyncio.sleep(DEBUG_INTERVAL)
        elapsed_time += DEBUG_INTERVAL

    # Auto-response after timeout
    if (not is_screenshot and ticket_id in user_tickets and user_tickets[ticket_id].get("ticket_status") == "pending") or \
       (is_screenshot and ticket_id in pending_screenshots):
        
        print(f"⏰ DEBUG: Timeout reached ({current_wait_time}s) - sending auto-response for {'Screenshot' if is_screenshot else 'Ticket'} {ticket_id}")
        
        if is_screenshot:
            # Handle screenshot auto-ignore
            await auto_ignore_screenshot(ticket_id, original_chat_id, ticket_message_id, moftbar_username, original_message_id)
        else:
            # Handle ticket auto-response
            ai_response = ticket_data.get("ai_response", "در حال بررسی!")
            await asyncio.sleep(2)
            ai_response_message = await safe_send_message(client, original_chat_id, ai_response, reply_to=original_message_id)
            
            if ticket_id in user_tickets and ai_response_message:
                user_tickets[ticket_id]["ai_response_message_id"] = ai_response_message.id
                user_tickets[ticket_id]["ticket_status"] = "auto_responded"
                user_tickets[ticket_id]["admin_response"] = ai_response
                auto_response_count += 1
                # WAIT_TIME_FOR_ADMIN bleibt unverändert - AI Antwort ändert nicht die Wartezeit
                print(f"✅ DEBUG: auto_response_count = {auto_response_count}")
                # Send notification about count increase
                count_notify = await safe_send_message(client, ticket_channel_chat_ID, f"🤖 Auto response count increased to {auto_response_count}")
                await asyncio.sleep(3)
                await count_notify.delete()

                # Update ticket message with colorful AI indicator
                telegram_username = user_tickets[ticket_id].get("telegram_username", "")
                if is_token:
                    template_key = "ticket_token_ai"
                    status_text = STATUS_TEXTS["auto_responded_token"]
                elif is_card:
                    template_key = "ticket_card_ai"
                    status_text = STATUS_TEXTS["auto_responded_card"]
                elif trx_wallet:
                    template_key = "ticket_trx_wallet_ai"
                    status_text = STATUS_TEXTS["auto_responded_wallet"]
                else:
                    template_key = "ticket_text_ai"
                    status_text = STATUS_TEXTS["auto_responded"]
                
                updated_ticket_text = await generate_update_text(
                    template_key,
                    ticket_id=ticket_id,
                    moftbar_username=moftbar_username,
                    telegram_username=telegram_username,
                    ticket_text=user_tickets[ticket_id]['ticket_text'] if not is_token else "",
                    token_number=is_token if is_token else None,
                    non_token_text=extract_text_without_token(user_tickets[ticket_id]['ticket_text']) if is_token else None,
                    card_number=card_number if card_number else None,
                    trx_wallet=trx_wallet if trx_wallet else None,
                    response_text=ai_response,
                    status_text=status_text
                )
                await client.edit_message(ticket_channel_chat_ID, ticket_message_id, updated_ticket_text)

        await manage_separator("resolved")

    # Wait for the admin's reply (this part is now handled by the timer above)
    # The function will return before reaching this point if auto-response is sent
    replied_message = await event.get_reply_message()
    if not replied_message:
        print(f"DEBUG: No reply from admin for {ticket_id or 'screenshot'}")
        return

    response_text = replied_message.raw_text.strip().lower()

    # Check for links (exclude emails)
    if has_link(response_text) and not replied_message.sticker and not replied_message.photo and response_text not in SPECIAL_COMMANDS["confirm"]:
        notify_message = await safe_send_message(client, event.chat_id, "❌ **خطا:** پاسخ حاوی لینک است. لطفاً لینک‌ها را حذف کنید.")
        print(f"❌ DEBUG: Admin reply contains a link: {response_text}")
        await asyncio.sleep(3)
        await notify_message.delete()
        return

    # Handle special commands
    is_ticket_reply = not is_screenshot
    if response_text in SPECIAL_COMMANDS["cancel"]:
        template_key = "canceled_token" if is_ticket_reply and is_token else "canceled" if not is_screenshot else "canceled_screenshot"
        status = "canceled"
        if not is_screenshot:
            user_tickets[ticket_id]["ticket_status"] = status
            await cancel_timer(user_tickets, ticket_id, "Ticket")
        else:
            await cancel_timer(pending_screenshots, ticket_id, "Screenshot")
            del pending_screenshots[ticket_id]
        update_text = await generate_update_text(
            template_key,
            ticket_id=ticket_id,
            screenshot_id=ticket_id if is_screenshot else None,
            moftbar_username=moftbar_username,
            telegram_username=user_tickets[ticket_id].get("telegram_username", ""),
            ticket_text=original_ticket_text if not is_token else "",
            token_number=is_valid_token(original_ticket_text) if is_token else None,
            non_token_text=extract_text_without_token(original_ticket_text) if is_token else None
        )
        await client.edit_message(ticket_channel_chat_ID, ticket_message_id, update_text)
        print(f"⛔ DEBUG: Admin canceled {'Token Ticket' if is_token else 'Ticket' if not is_screenshot else 'Screenshot'} {ticket_id}")
        await manage_separator("canceled")
        return

    if response_text in SPECIAL_COMMANDS["block"]:
        if not is_screenshot:
            await block_user(original_chat_id)
            update_text = await generate_update_text(
                "blocked",
                ticket_id=ticket_id,
                moftbar_username=moftbar_username,
                telegram_username=user_tickets[ticket_id].get("telegram_username", ""),
                ticket_text=original_ticket_text
            )
            await client.edit_message(ticket_channel_chat_ID, ticket_message_id, update_text)
            await reset_tickets(original_chat_id)
            notify_message = await safe_send_message(client, event.chat_id, f"❌**کاربر بلاک شد.**❌")
            await asyncio.sleep(3)
            await notify_message.delete()
            await manage_separator("resolved")
        return

    if response_text in SPECIAL_COMMANDS["reset"]:
        await reset_tickets(original_chat_id)
        notify_message = await safe_send_message(client, event.chat_id, f"❌**کلیه پیامهای باز `{moftbar_username}` نادیده گرفته شد**❌")
        await asyncio.sleep(3)
        await notify_message.delete()
        await manage_separator("resolved")
        return

    # Handle response types
    is_sticker = replied_message.sticker is not None
    is_photo = replied_message.photo is not None
    final_message = response_text
    is_ai_response = False

    if response_text in SPECIAL_COMMANDS["confirm"]:
        final_message = ai_response or "🤖 AI پاسخ خودکار موجود نیست."
        is_ai_response = True
        last_manual_response_time = time.time()
        auto_response_count = 0
        await replied_message.delete()

    # Determine template key
    template_key = "screenshot" if is_screenshot else "ticket_token" if is_token else "ticket_card" if is_card else "ticket_text"

    # Generate update text
    if is_sticker:
        sticker_id = replied_message.file.id
        await client.send_file(original_chat_id, sticker_id, reply_to=original_message_id)
        if not is_screenshot:
            add_qa_with_sticker(original_ticket_text, None, sticker_id)
        update_text = await generate_update_text(
            template_key,
            ticket_id=ticket_id,
            screenshot_id=ticket_id if is_screenshot else None,
            moftbar_username=moftbar_username,
            telegram_username=user_tickets[ticket_id].get("telegram_username", ""),
            ticket_text=original_ticket_text if not is_token else "",
            token_number=is_valid_token(original_ticket_text) if is_token else None,
            non_token_text=extract_text_without_token(original_ticket_text) if is_token else None,
            card_number=is_valid_cardnumber(original_ticket_text) if is_card else None,
            response_text="Sticker sent.",
            status_text=STATUS_TEXTS["resolved_sticker"]
        )
        notify_message = await safe_send_message(client, event.chat_id, "✅ Sticker sent to user!")
    elif is_photo:
        file_path = await replied_message.download_media()
        await client.send_file(original_chat_id, file_path, reply_to=original_message_id)
        if not is_screenshot:
            add_qa_with_image(original_ticket_text, image_path=file_path)
        update_text = await generate_update_text(
            template_key,
            ticket_id=ticket_id,
            screenshot_id=ticket_id if is_screenshot else None,
            moftbar_username=moftbar_username,
            telegram_username=user_tickets[ticket_id].get("telegram_username", ""),
            ticket_text=original_ticket_text if not is_token else "",
            token_number=is_valid_token(original_ticket_text) if is_token else None,
            non_token_text=extract_text_without_token(original_ticket_text) if is_token else None,
            card_number=is_valid_cardnumber(original_ticket_text) if is_card else None,
            response_text="Photo sent.",
            status_text=STATUS_TEXTS["resolved_photo"]
        )
        notify_message = await safe_send_message(client, event.chat_id, "✅ Photo sent to user!")
    else:
        if not is_screenshot:
            add_qa(original_ticket_text, final_message)
        update_text = await generate_update_text(
            template_key,
            ticket_id=ticket_id,
            screenshot_id=ticket_id if is_screenshot else None,
            moftbar_username=moftbar_username,
            telegram_username=user_tickets[ticket_id].get("telegram_username", ""),
            ticket_text=original_ticket_text if not is_token else "",
            token_number=is_valid_token(original_ticket_text) if is_token else None,
            non_token_text=extract_text_without_token(original_ticket_text) if is_token else None,
            card_number=is_valid_cardnumber(original_ticket_text) if is_card else None,
            response_text=final_message,
            status_text=STATUS_TEXTS["resolved_ai" if is_ai_response else "resolved_text"]
        )
        if is_ai_response and ticket_data.get("ai_response_message_id"):
            try:
                await client.edit_message(original_chat_id, ticket_data["ai_response_message_id"], final_message)
                auto_response_count = max(0, auto_response_count - 1)
            except Exception as e:
                print(f"❌ ERROR: Failed to edit AI response - {e}")
                await safe_send_message(client, original_chat_id, final_message, reply_to=original_message_id)
        else:
            await safe_send_message(client, original_chat_id, final_message, reply_to=original_message_id)
        await append_to_conversation_history(original_chat_id, "bot", final_message)
        notify_message = await safe_send_message(client, event.chat_id, 
            f"✅ پاسخ به {'تیکت' if not is_screenshot else 'اسکرین‌شات'} `{ticket_id}` ارسال شد.")

    # Update ticket or screenshot status
    if not is_screenshot:
        await cancel_timer(user_tickets, ticket_id, "Ticket")
        if user_tickets[ticket_id].get("pinned_warning_id"):
            try:
                await client.unpin_message(original_chat_id, user_tickets[ticket_id]["pinned_warning_id"])
                await client.delete_messages(original_chat_id, user_tickets[ticket_id]["pinned_warning_id"])
                del user_tickets[ticket_id]["pinned_warning_id"]
            except Exception as e:
                print(f"ERROR: Konnte gepinnte Warnnachricht nicht löschen - {e}")
        user_tickets[ticket_id]["ticket_status"] = "resolved" if not response_text in SPECIAL_COMMANDS["cancel"] else "canceled"
        user_tickets[ticket_id]["admin_response"] = final_message
    else:
        await cancel_timer(pending_screenshots, ticket_id, "Screenshot")
        del pending_screenshots[ticket_id]

    # Edit ticket/screenshot message
    try:
        current_message = await client.get_messages(ticket_channel_chat_ID, ids=ticket_message_id)
        # Handle both single message and list cases
        if isinstance(current_message, list) and len(current_message) > 0:
            current_message = current_message[0]
        current_text = current_message.text if current_message and hasattr(current_message, 'text') else ""
        if update_text != current_text:
            await client.edit_message(ticket_channel_chat_ID, ticket_message_id, update_text)
        else:
            update_text += f"\n🕒 Edited: {datetime.datetime.now().strftime('%H:%M:%S')}"
            await client.edit_message(ticket_channel_chat_ID, ticket_message_id, update_text)
            print(f"⚠️ DEBUG: Forced edit with timestamp for {'Ticket' if not is_screenshot else 'Screenshot'} {ticket_id}")
    except MessageNotModifiedError:
        print(f"⚠️ DEBUG: Message not modified for {'Ticket' if not is_screenshot else 'Screenshot'} {ticket_id}")
    except Exception as e:
        print(f"❌ ERROR: Failed to edit message - {e}")

    # Clean up notify message
    if 'notify_message' in locals():
        await asyncio.sleep(3)
        await notify_message.delete()

    await manage_separator("resolved" if not response_text in SPECIAL_COMMANDS["cancel"] else "canceled")














async def forward_message_without_reading(client, chat_id, message_id, target_chat):
    try:
        # Retrieve original message
        message = await client.get_messages(chat_id, ids=message_id)
        if message and message.sender_id:
            pending_questions[message.id] = message.sender_id
            #print(f"✅ Benutzer-ID gespeichert: Nachricht {message.id} von Benutzer {message.sender_id}")
        
        # Nachricht weiterleiten und das Ergebnis speichern
        forwarded = await client(ForwardMessagesRequest(
            from_peer=chat_id,
            id=[message_id],
            to_peer=target_chat,
            silent=True
        ))
        
        # Extrahiere die Nachricht-ID aus dem Update
        if forwarded.updates and len(forwarded.updates) > 0:
            update = forwarded.updates[-1]  # Letztes Update nehmen
            if hasattr(update, 'message') and hasattr(update.message, 'id'):
                forwarded_message_id = update.message.id
            else:
                print(f"❌ ERROR: Keine gültige Nachricht-ID im Update gefunden: {update}")
                return None
        else:
            print(f"❌ ERROR: Keine Updates nach dem Weiterleiten erhalten.")
            return None
        
        # Hole die weitergeleitete Nachricht aus dem Zielkanal
        forwarded_message = await client.get_messages(target_chat, ids=forwarded_message_id)
        if not forwarded_message:
            print(f"❌ ERROR: Konnte die weitergeleitete Nachricht mit ID {forwarded_message_id} nicht abrufen.")
            return None
        
        # Check for active tickets
        #has_pending, ticket_info = await user_has_active_timer(chat_id)
        #if has_pending:
        #    print(f"⛔ DEBUG: User {chat_id} tried to create a new ticket while an active one exists.")
        #    await safe_send_message(client, chat_id, 
        #        "⚠️ شما قبلاً یک مورد برای بررسی ارسال کرده‌اید. لطفاً منتظر بررسی ادمین بمانید و سپس مورد بعدی را استعلام کنید.")
        #    return None  # Return None on abort
        
        #print(f"✅ Nachricht {message_id} weitergeleitet. Ticket-ID: {forwarded_message.id}")
        return forwarded_message  # Return the forwarded message

    except Exception as e:
        print(f"❌ Fehler beim Weiterleiten der Nachricht: {e}")
        return None





async def is_known_contact(client, chat_id):
    try:
        # Kontakte aus Telegram abrufen (hash=0 bedeutet alle abrufen)
        result = await client(GetContactsRequest(hash=0))

        # Go through contacts and check if the chat_id exists
        for user in result.users:
            if user.id == chat_id:
                return True  # Der Nutzer ist in den Kontakten
        
        return False  # Nutzer ist nicht in den Kontakten
    except Exception as e:
        print(f"❌ Fehler beim Abrufen der Kontakte: {e}")
        return False



async def find_original_user_id(client, event, ticket_chat_id, search_limit=50):
    """
    Finds the original user ID from a forwarded message or stored message.

    Args:
        client: TelegramClient - Dein Telethon Client.
        event: telethon.events.NewMessage - Das Event-Objekt mit der Nachricht.
        ticket_chat_id: int - Die ID des Ticket-Chats oder Kanals.
        search_limit: int - Anzahl der letzten Nachrichten, die für die Benutzer-ID durchsucht werden.

    Returns:
        int | None: Die gefundene Benutzer-ID oder None, falls nicht gefunden.
    """
    history = await event.get_reply_message()

    if not history:
        print("❌ Fehler: Es gibt keine Antwort-Nachricht (Reply).")
        return None

    # 1️⃣ Check if the message ID is stored in pending_questions
    if history.id in pending_questions:
        original_user_id = pending_questions[history.id]
        print(f"✅ User ID found from stored history: {original_user_id}")
        return original_user_id

            # 2️⃣ Check if Telegram provides a forwarding ID
    if hasattr(history, "forward") and hasattr(history.forward, "sender_id"):
        if history.forward.sender_id and history.forward.sender_id != ticket_chat_id:
            print(f"✅ Benutzer-ID gefunden (weitergeleitet von): {history.forward.sender_id}")
            return history.forward.sender_id

        print("⚠ Warnung: Weitergeleitete Nachricht, aber die Sender-ID ist verborgen.")

    # 3️⃣ Falls kein direkter Treffer, suche in der letzten Chat-Historie
    try:
        original_history = await client(GetHistoryRequest(
            peer=ticket_chat_id,
            limit=search_limit,
            offset_date=None,
            offset_id=0,
            max_id=0,
            min_id=0,
            add_offset=0,
            hash=0
        ))

        # 4️⃣ Suche nach der Originalfrage
        for msg in original_history.messages:
            if msg.message and history.message in msg.message and msg.sender_id != ticket_chat_id:
                #print(f"✅ Benutzer-ID durch Chat-Historie gefunden: {msg.sender_id}")
                return msg.sender_id

    except Exception as e:
        print(f"❌ Fehler beim Abrufen der Chat-Historie: {e}")

    print("❌ Fehler: Keine gültige Benutzer-ID gefunden, nur Kanal-ID verfügbar.")
    return None









last_send_time = 0  # Global variable to track last send time

last_bot_message_ids = {}  # Global dictionary to store the last message ID per chat_id

async def safe_send_message(client, chat, message, **kwargs):
    global last_send_time, last_bot_message_ids
    current_time = time.time()
    elapsed = current_time - last_send_time
    if elapsed < 0.1:  # Enforce 100ms delay (10 messages/sec)
        await asyncio.sleep(0.1 - elapsed)
    
    try:
        sent_message = await client.send_message(chat, message, **kwargs)
        last_send_time = time.time()
        last_bot_message_ids[chat] = sent_message.id  # Store the last message ID
        return sent_message
    except FloodWaitError as e:
        await asyncio.sleep(e.seconds + 1)  # Reduced safety buffer
        sent_message = await client.send_message(chat, message, **kwargs)
        last_send_time = time.time()
        last_bot_message_ids[chat] = sent_message.id  # Store the last message ID
        return sent_message
    except Exception as e:
        print(f"❌ ERROR: Failed to send message - {e}")
        return None



last_ticket_message_cache = None  # Cache for the last message
last_ticket_message_time = 0      # Time when last message was fetched


BLACKLIST_FILE = "blacklist.txt"

# Function to add a user to the blacklist
def add_to_blacklist(user_id):
    with open(BLACKLIST_FILE, "a") as f:
        f.write(f"{user_id}\n")

def delfrom_blacklist(user_id):
    """
    Removes a user from the blacklist file.
    
    Args:
        user_id: The user ID to remove from the blacklist
    """
    # Read file and save all lines
    with open(BLACKLIST_FILE, "r") as f:
        lines = f.readlines()

    # Filter lines to remove the user_id
    with open(BLACKLIST_FILE, "w") as f:
        for line in lines:
            if line.strip() != str(user_id):  # Remove exact match
                f.write(line)


def load_blacklist():
    """
    Loads the blacklist from file.
    
    Returns:
        set: Set of blacklisted user IDs
    """
    try:
        with open(BLACKLIST_FILE, "r") as f:
            return set(line.strip() for line in f)
    except FileNotFoundError:
        return set()

def remove_from_blacklist(user_id):
    """
    Removes a user from the blacklist.
    
    Args:
        user_id: The user ID to remove from the blacklist
    """
    blacklist = load_blacklist()
    if str(user_id) in blacklist:
        blacklist.remove(str(user_id))
        with open(BLACKLIST_FILE, "w") as f:
            f.write("\n".join(blacklist))




def set_always_on(chat_id):
    """
    Activates the Always-On mode for a user and stores the chat ID in the database.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR IGNORE INTO always_on_users (chat_id) VALUES (?)", (chat_id,))
        conn.commit()
        print(f"✅ DEBUG: Always-On mode activated for Chat ID {chat_id}")
    except Exception as e:
        print(f"❌ ERROR: Error activating Always-On mode: {e}")
    finally:
        conn.close()

def remove_always_on(chat_id):
    """
    Deactivates the Always-On mode for a user and removes the chat ID from the database.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM always_on_users WHERE chat_id = ?", (chat_id,))
        conn.commit()
        print(f"✅ DEBUG: Always-On mode deactivated for Chat ID {chat_id}")
    except Exception as e:
        print(f"❌ ERROR: Error deactivating Always-On mode: {e}")
    finally:
        conn.close()

def is_always_on(chat_id):
    """
    Checks if the Always-On mode is activated for a chat ID.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM always_on_users WHERE chat_id = ?", (chat_id,))
        result = cursor.fetchone()
        return result is not None
    except Exception as e:
        print(f"❌ ERROR: Error checking Always-On mode: {e}")
        return False
    finally:
        conn.close()


def is_valid_username(username):
    """
    Checks if the username meets the following conditions:
    - Maximum 12 characters
    - Only letters, numbers, hyphens and underscores
    """
    pattern = r"^[a-zA-Z0-9_-]{3,12}$"
    return re.match(pattern, username)


async def register_new_user(chat_id, event):
    print(f"DEBUG: Requesting Moftbar username - Chat ID: {chat_id}")
    try:
        if await user_states.has(chat_id) and await user_states.get(chat_id) == "awaiting_username":
            print(f"DEBUG: Already awaiting username for Chat ID: {chat_id}, skipping.")
            return None
        await user_states.set(chat_id, "awaiting_username")
        async with client.conversation(chat_id) as conv:
            await conv.send_message(
                "لطفا نام کاربری خود را وارد کنید (حداقل ۳ و حداکثر ۱۲ کاراکتر، فقط حروف، اعداد، خط تیره و آندرلاین مجاز هستند):"
            )
            try:
                response_event = await conv.get_response(timeout=120)
                moftbar_username = response_event.text.strip()
                if is_valid_username(moftbar_username):
                    notify_message = await safe_send_message(client, chat_id, f"✅ **نام کاربری با موفقیت ذخیره شد!** 🎉")
                    await asyncio.sleep(2)
                    await notify_message.delete()
                    add_user(moftbar_username, chat_id)
                    update_last_check_date(chat_id)
                    await pin_user(client, event, moftbar_username)
                    await show_main_menu(event.chat_id)
                    return moftbar_username
                else:
                    notify_message = await safe_send_message(client, chat_id, "❌ **نام کاربری نامعتبر است!** ⚠️\n\nلطفاً نام کاربری معتبر وارد کنید.")
                    await asyncio.sleep(2)
                    await notify_message.delete()
                    moftbar_username = f"User{chat_id}"
                    add_user(moftbar_username, chat_id)
                    update_last_check_date(chat_id)
                    await show_main_menu(event.chat_id)
                    return moftbar_username
            except asyncio.TimeoutError:
                notify_message = await safe_send_message(client, chat_id, "⏰ **زمان به پایان رسید!** ⏳\n\nنام کاربری پیش‌فرض تنظیم شد.")
                await asyncio.sleep(2)
                await notify_message.delete()
                moftbar_username = f"User{chat_id}"
                add_user(moftbar_username, chat_id)
                update_last_check_date(chat_id)
                await show_main_menu(event.chat_id)
                return moftbar_username
    except Exception as e:
        print(f"ERROR: Error during user registration - Chat ID: {chat_id}, Error: {e}")
        moftbar_username = f"User{chat_id}"
        add_user(moftbar_username, chat_id)
        update_last_check_date(chat_id)
        await pin_user(client, event, moftbar_username)
        #await safe_send_message(client, chat_id, f"✅خوش آمدید")
        #await show_main_menu(event.chat_id)
        return moftbar_username
    finally:
        

        if await user_states.has(chat_id) and await user_states.get(chat_id) == "awaiting_username":
            await user_states.set(chat_id, "main_menu")  # Reset to a safe state


            

async def show_main_menu(chat_id):
    if chat_id is None:
        return
    async with conversation_history_lock:
        conversation_history[chat_id] = []  # Clear history on menu reset

    await user_states.set(chat_id, "main_menu")

    # Define the menu text (from MoftbarDialog59)
    menu_text = ("درخدمتم\n لطفاً یکی از گزینه‌های زیر را انتخاب کنید:\n\n"
                 "1️⃣ حالت متنی پرسش و پاسخ.\n"
                 "2️⃣ پیگیری تراکنش.\n"
                 "3️⃣ ارسال تیکت مستقیم به پشتیبانی فنی\n"
                 "4️⃣ جوایز🎁 (لیگ،آفرها، بونوس)\n\n")

 


    # Send the menu if it's not the last message
    await safe_send_message(client, chat_id, menu_text)











async def get_chat_id_by_username(telegram_username, client):
    """
    Finds the chat ID based on the Telegram username.
    """
    try:
        #print(f"DEBUG: Fetching Chat ID for Telegram Username: {telegram_username}")
        # Get user information
        user = await client.get_entity(telegram_username)
        return user.id  # User's chat ID
    except Exception as e:
        print(f"ERROR: Failed to fetch Chat ID for Telegram Username '{telegram_username}': {e}")
        return None
    


    
def get_limited_qa_data(prompt, limit=10):
    """
    Limits the number of QA data that are included in the prompt.
    """
    try:
        all_qa_data = read_full_qa_db()
        relevant_qa = get_relevant_qa_entries(prompt, all_qa_data, limit=limit)

        if not relevant_qa:
            # Return a fallback QA pair instead of a string
            return [("سوال عمومی", "سلام! من آماده کمک به شما هستم. لطفاً سوال خود را بپرسید.")]

        return relevant_qa
    except Exception as e:
        print(f"[QA Data Error]: {e}")
        return [("سوال عمومی", "سلام! من آماده کمک به شما هستم. لطفاً سوال خود را بپرسید.")]



def clean_invalid_entries():
    """
    Entfernt ungültige Einträge aus der QA-Datenbank, wenn eines der Felder (question, answer, image_path, sticker_id)
    NULL oder leer ist.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        # Delete entries where `question`, `answer`, `image_path` or `sticker_id` is NULL or empty
        cursor.execute("""
            DELETE FROM qa
            WHERE 
                question IS NULL OR question = '' OR
                answer IS NULL OR answer = '' OR
                (image_path IS NOT NULL AND image_path = '') OR
                (sticker_id IS NOT NULL AND sticker_id = '')
        """)
        conn.commit()
        print("DEBUG: Ungültige Einträge aus der QA-Datenbank entfernt.")
    except Exception as e:
        print(f"ERROR: Fehler beim Bereinigen der QA-Datenbank: {e}")
    finally:
        conn.close()



def read_full_qa_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT question, answer FROM qa")
    data = cursor.fetchall()
    conn.close()

    # Debugging: Check the structure of the data
    for idx, entry in enumerate(data):
        if len(entry) < 2:
            print(f"DEBUG: Ungültiger Eintrag in der Datenbank an Position {idx}: {entry}")

    # Fallback for empty data
    if not data:
        print("DEBUG: QA-Datenbank ist leer.")
        return [("هیچ اطلاعاتی در پایگاه داده موجود نیست.", "لطفاً سوال خود را دقیق‌تر بیان کنید.")]

    return data


# File path for the prompts
PROMPTS_FILE = "prompts.json"

def load_prompts():
    """
    Lädt die Prompts aus der JSON-Datei.

    Returns:
        list: Liste von Prompts.
    """
    try:
        with open(PROMPTS_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        print(f"⚠️ DEBUG: File {PROMPTS_FILE} not found. Creating a new one.")
        return []
    except json.JSONDecodeError:
        print(f"❌ ERROR: Invalid JSON format in {PROMPTS_FILE}.")
        return []

def save_prompts(prompts):
    """
    Saves the prompts to the JSON file.

    Args:
        prompts (list): List of prompts to be saved.
    """
    try:
        with open(PROMPTS_FILE, "w", encoding="utf-8") as file:
            json.dump(prompts, file, ensure_ascii=False, indent=4)
        print(f"✅ DEBUG: Prompts successfully saved to {PROMPTS_FILE}")
    except Exception as e:
        print(f"❌ ERROR: Error saving prompts: {e}")

def add_prompt(role, content):
    """
    Adds a new prompt to the prompts and saves the file.

    Args:
        role (str): The role (e.g., 'system', 'user').
        content (str): The content of the prompt.
    """
    prompts = load_prompts()
    new_prompt = {"role": role, "content": content}
    prompts.append(new_prompt)
    save_prompts(prompts)
    print(f"✅ DEBUG: New prompt added - Role: {role}, Content: {content}")

def build_messages(relevant_qa=""):
    """
    Builds the `messages` list dynamically from prompts and combines content with the same role.
    
    Args:
        relevant_qa (str): Dynamically inserted data (e.g., QA content).

    Returns:
        list: List of messages (`messages`) with combined roles.
    """
    prompts = load_prompts()

    # Initialisiere die Rollenstruktur
    combined_roles = {
        "system": "",
        "user": "",
        "assistant": ""
    }

    # Go through all prompts and add content based on the role
    for prompt in prompts:
        role = prompt.get("role")
        content = prompt.get("content", "")

        # Add `relevant_qa` if present
        if role == "system" and "{relevant_qa}" in content:
            content = content.replace("{relevant_qa}", relevant_qa)

        # Combine the content for each role
        if role in combined_roles:
            combined_roles[role] += f"{content}\n\n"

    # Remove unnecessary whitespace and create the messages list
    messages = []
    for role, content in combined_roles.items():
        if content.strip():  # Only add if there is content
            messages.append({"role": role, "content": content.strip()})

    return messages


def enrich_prompt_with_qa_limited(prompt):
    """
    Enhances the GPT prompt with the most relevant QA entries from the database.

    Args:
        prompt (str): The user's question.

    Returns:
        list: Adapted messages list for the GPT API.
    """
    # Normalize the input prompt to handle Persian text properly
    prompt = unicodedata.normalize('NFC', prompt)

    # Read QA database
    try:
        all_qa_data = read_full_qa_db()
    except Exception as e:
        print(f"❌ ERROR: Failed to read QA database - {e}")
        all_qa_data = []

    # Check if the database is empty
    if not all_qa_data:
        print("⚠️ DEBUG: QA database is empty, using fallback.")
        qa_context = "هیچ اطلاعاتی در پایگاه داده موجود نیست."
    else:
        # Select the most relevant QA entries
        try:
            relevant_qa = get_relevant_qa_entries(prompt, all_qa_data, limit=5)
        except Exception as e:
            print(f"❌ ERROR: Failed to get relevant QA entries - {e}")
            relevant_qa = []

        # Validate and format the relevant QA entries into a string for context
        if not relevant_qa:
            qa_context = "هیچ نتیجه مرتبطی در پایگاه داده پیدا نشد."
        else:
            qa_context = "\n\n**اطلاعات مرتبط از پایگاه داده سوالات متداول:**\n"
            for i, entry in enumerate(relevant_qa, 1):
                # Ensure the entry is a tuple with exactly two elements
                if not isinstance(entry, (tuple, list)) or len(entry) != 2:
                    print(f"⚠️ DEBUG: Invalid QA entry format at index {i-1}: {entry}")
                    continue
                question, answer = entry
                qa_context += f"{i}. پرسش: {question}\n   پاسخ: {answer}\n"

    # Read the saved prompts (assuming build_messages returns a list of prompts)
    try:
        saved_prompts = build_messages()
    except Exception as e:
        print(f"❌ ERROR: Failed to build messages - {e}")
        saved_prompts = []

    # Ensure saved_prompts is a list of dictionaries
    if not isinstance(saved_prompts, list):
        print(f"WARNING: saved_prompts is not a list, reinitializing: {type(saved_prompts)}")
        saved_prompts = []

    # Filter out the system prompt from saved_prompts to avoid duplication
    saved_prompts = [p for p in saved_prompts if p.get("role") != "system"]

    # Create the base system prompt
    system_prompt = {
        "role": "system",
        "content": unicodedata.normalize('NFC', (
            "شما یک بات حرفه‌ای پشتیبانی برای سایت پوکر مفتبر Moftbar.online هستید و فقط به زبان فارسی پاسخ می‌دهید.\n"
            "پاسخ‌های شما بر اساس پایگاه داده سوالات متداول است و فقط به موضوعات مربوط به سایت Moftbar.online پاسخ می‌دهید.\n"
            "شما نباید هیچ لینک یا اطلاعات خارجی بدهید و فقط کانال تلگرام @moftbarnews را معرفی کنید.\n"
            "اگر سوالی خارج از سایت یا اطلاعات شخصی بود، politely رد کنید.\n"
            "تمام پاسخ‌ها باید حداکثر در ۸ خط بیان شوند و دقیق، شفاف، و بدون اضافه‌گویی باشند.\n"
            "در صورتی که پاسخ آماده کافی نبود، کاربر را به منوی اصلی با start/ و گزینه ۳ ارجاع دهید.\n"
            "در پاسخ خود، حتما از اطلاعات به‌روز در پرسش‌های پرتکرار و پایگاه داده استفاده کنید.\n"
            "پاسخ‌های شما باید دوستانه، دقیق و سریع باشد."
        ))
    }

    # Combine the user prompt with QA context
    user_prompt = unicodedata.normalize('NFC', (
        f"پاسخ را در حداکثر ۸ خط بنویس. فقط از اطلاعات تاییدشده استفاده کن. به سوال زیر پاسخ بده:\n\n"
        f"{prompt}\n"
        f"{qa_context}"
    ))

    # Construct the final messages list
    messages = [system_prompt] + saved_prompts + [{"role": "user", "content": user_prompt}]

    print(f"DEBUG: Final messages for GPT:\n\n\n\n {reverse_text(messages)}\n\n\n\n")
    return messages


def get_relevant_qa_entries(prompt, qa_data, limit=5):
    """
    Find the most relevant QA entries based on fuzzy matching.

    Args:
        prompt (str): The user prompt to match against.
        qa_data (list): List of (question, answer) tuples from the QA database.
        limit (int): Maximum number of entries to return.

    Returns:
        list: List of (question, answer) tuples.
    """
    # Ensure qa_data contains valid entries
    valid_qa_data = [entry for entry in qa_data if isinstance(entry, (tuple, list)) and len(entry) == 2]
    if not valid_qa_data:
        return []

    # Extract questions for fuzzy matching
    questions = [entry[0] for entry in valid_qa_data]
    matches = process.extract(prompt, questions, scorer=fuzz.ratio, limit=limit)

    # Return the corresponding QA entries for the best matches
    relevant_entries = []
    for match in matches:
        question = match[0]
        # Find the original entry with this question
        for qa_entry in valid_qa_data:
            if qa_entry[0] == question:
                relevant_entries.append(qa_entry)
                break

    return relevant_entries

import openai

# Create a dedicated OpenAI client (to avoid conflict with Telethon client)


# Global variables (existing)
last_gpt_call_time = 0  # Global variable to track the last GPT call time

def get_gpt_response(user_message, chat_id):
    """
    Generates a GPT response for the user message, using comprehensive Q&A database as knowledge and style context.
    Now includes conversation history for better context awareness.
    """
    try:
        # Get conversation history for this user (last 10 conversations)
        conversation_history_list = load_conversation_from_db(chat_id)
        recent_conversations = conversation_history_list[-20:]  # Last 20 messages (10 conversations = 20 messages)
        
        # Get more Q&A examples for comprehensive style and knowledge context
        qa_examples = get_limited_qa_data(prompt=user_message, limit=15)  # More examples for better context
        print(f"[DEBUG] Found {len(qa_examples)} QA examples")
        print(f"[DEBUG] Found {len(recent_conversations)} recent conversation messages")
        
        style_examples = ""
        for qa in qa_examples:
            if isinstance(qa, (tuple, list)) and len(qa) >= 2:
                style_examples += f"پرسش: {qa[0]}\nپاسخ: {qa[1]}\n\n"
            else:
                print(f"[DEBUG] Invalid QA format: {qa}")
        
        # Build conversation context
        conversation_context = ""
        if recent_conversations:
            conversation_context = "\n\n📝 **تاریخچه گفتگوهای اخیر:**\n"
            for i, conv in enumerate(recent_conversations[-10:], 1):  # Last 10 conversations
                role_emoji = "👤" if conv["role"] == "user" else "🤖"
                conversation_context += f"{i}. {role_emoji} {conv['role'].title()}: {conv['content'][:100]}...\n"
        
        # Build comprehensive system context
        system_context = (
            "تو یک دستیار فارسی‌زبان متخصص هستی که از دیتابیس Q&A ما برای پاسخ‌دهی استفاده می‌کنی. "
            "سبک و لحن و واژگان پاسخ‌های زیر را کاملاً یاد بگیر و از آنها استفاده کن:\n\n"
            f"{style_examples}"
            f"{conversation_context}"
            "قوانین مهم:\n"
            "1. فقط از دانش موجود در نمونه‌های بالا استفاده کن\n"
            "2. از همان سبک، لحن و واژگان نمونه‌ها استفاده کن\n"
            "3. اصطلاحات و کلمات فنی و کامپیوتری را به همان صورت لاتین (انگلیسی) حفظ کن\n"
            "4. از ایموجی‌ها و استایل‌دهی (بولد، ایتالیک) زیاد استفاده کن\n"
            "5. پاسخ‌ها باید دوستانه، مفید و دقیق باشند\n"
            "6. اگر سوال خارج از حوزه دانش نمونه‌ها باشد، صادقانه بگو که نمی‌دانی\n"
            "7. پاسخ‌ها باید کوتاه و مختصر باشند (حداکثر 10 خط) اما جملات را کامل کن حتی اگر از 10 خط بیشتر شد\n"
            "8. به تاریخچه گفتگوهای اخیر توجه کن و پاسخ‌های قبلی را در نظر بگیر\n"
            "9. اگر کاربر سوال مشابهی پرسیده، به پاسخ قبلی ارجاع بده"
        )
        
        # Prepare messages for OpenAI API
        messages = [{"role": "system", "content": system_context}]
        
        # Add conversation history as context
        if recent_conversations:
            for conv in recent_conversations[-10:]:  # Last 10 conversations
                # Map database roles to OpenAI roles
                openai_role = "assistant" if conv["role"] == "bot" else conv["role"]
                messages.append({
                    "role": openai_role,
                    "content": conv["content"]
                })
        
        # Add current user message
        messages.append({"role": "user", "content": user_message})
        
        # Use the OpenAI client that's already imported at the top
        openai_client = OpenAI(api_key=openai.api_key)
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=300,  # Increased for more detailed responses
            temperature=0.7,
        )
        result = response.choices[0].message.content.strip()
        print(f"[DEBUG] GPT Response generated successfully with conversation history: {result[:100]}...")
        return result
    except Exception as e:
        print(f"[GPT Response Error]: {e}")
        print(f"[DEBUG] User message: {user_message}")
        return "متأسفانه در حال حاضر نمی‌توانم پاسخ دهم. لطفاً بعداً تلاش کنید."


async def pin_user(client, event, new_moftbar_username):
    #await safe_send_message(client, event.chat_id, f" برای منوی اصلی start/ را بزنید.")

    pinned_messages = await client.get_messages(event.chat_id, filter=InputMessagesFilterPinned)
    if pinned_messages and new_moftbar_username and new_moftbar_username.strip() in pinned_messages[0].message.strip():
        #print(f"DEBUG: Username '{new_moftbar_username}' is already as pinned_messages[0] {pinned_messages[0].message} pinned.")
        return
    pin_message = await safe_send_message(client, event.chat_id, f"{new_moftbar_username}")
    if pinned_messages:
        await client.unpin_message(event.chat_id)
    

    await client.pin_message(event.chat_id, pin_message.id, notify=False)
    print(f"DEBUG: Pinned username: {new_moftbar_username}")






def get_keywords_frequency(data):
    """
    Extrahiert Schlüsselwörter aus Fragen und zählt deren Häufigkeit.
    """
    all_words = []
    for question, _, _ in data:
        words = question.split()
        all_words.extend(words)
    return Counter(all_words)

def add_qa_with_sticker(question, answer=None, sticker_id=None):
    """
    Fügt eine Frage-Antwort-Paarung mit einem Sticker hinzu oder aktualisiert sie bei Duplikaten.
    """
    if not question:
        print("❌ ERROR: Cannot add Q&A with an empty question.")
        return False  # ✅ Exit function safely
    if  question:
        question  = clean_text(question)
    
    if is_mostly_numbers(question):
        print(f"\n✅ Nothing to learn from digits: {reverse_text(question)}") 
        return False
    
    if "✅" in question:
        #print(f"\n✅ in question wrong question to learn: {reverse_text(question)}") 
        return False
    
    if contains_email(question):
        print("✅ The question contains an email.")
        return False
   

    #print(f"\n\n\n\n\n\nadd_qa_with stickjer ques{question}") 


    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO qa (question, answer, sticker_id)
            VALUES (?, ?, ?)
            ON CONFLICT(question) DO UPDATE SET
                answer = excluded.answer,
                sticker_id = excluded.sticker_id
        """, (question, answer, sticker_id))
        conn.commit()
        print(f"DEBUG: QA with sticker added/updated - Question: {reverse_text(question)}, Sticker ID: {sticker_id}")
        return True
    except Exception as e:
        print(f"ERROR: Fehler beim Hinzufügen/Aktualisieren des Stickers: {e}")
        return False
    finally:
        conn.close()

def search_qa(message, threshold, chat_id=None):
    # Optionally combine with conversation history
    if chat_id in conversation_history:
        recent_messages = [entry["content"] for entry in conversation_history[chat_id][-3:] if entry["role"] == "user"]
        combined_input = " ".join(recent_messages + [message])
    else:
        combined_input = message

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT question, answer, image_path, sticker_id FROM qa")
    qa_data = cursor.fetchall()
    conn.close()

    best_match = process.extractOne(combined_input, [row[0] for row in qa_data], scorer=fuzz.token_sort_ratio)
    if best_match and best_match[1] >= threshold:
        matched_question = best_match[0]
        for row in qa_data:
            if row[0] == matched_question:
                return row[1], row[2], row[3]
    return None, None, None




def save_conversation_to_db(chat_id, role, content, timestamp):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO conversation_history (chat_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                      (chat_id, role, content, timestamp))
        # Keep only the last 20 messages per user
        cursor.execute("DELETE FROM conversation_history WHERE chat_id = ? AND timestamp NOT IN (SELECT timestamp FROM conversation_history WHERE chat_id = ? ORDER BY timestamp DESC LIMIT 20)",
                      (chat_id, chat_id))
        conn.commit()
        conn.close()
        print(f"✅ DEBUG: Saved conversation to DB - Chat ID: {chat_id}, Role: {role}, Content: {content[:30]}...")
    except Exception as e:
        print(f"❌ ERROR: Failed to save conversation to DB - {e}")

def load_conversation_from_db(chat_id):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT role, content, timestamp FROM conversation_history WHERE chat_id = ? ORDER BY timestamp ASC",
                      (chat_id,))
        history = [{"role": row[0], "content": row[1], "timestamp": row[2]} for row in cursor.fetchall()]
        conn.close()
        print(f"✅ DEBUG: Loaded {len(history)} conversation entries from DB for Chat ID: {chat_id}")
        return history
    except Exception as e:
        print(f"❌ ERROR: Failed to load conversation from DB - {e}")
        return []

# Initialize conversation_history at startup
async def initialize_conversation_history():
    async with conversation_history_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT chat_id FROM conversation_history")
        chat_ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        for chat_id in chat_ids:
            conversation_history[chat_id] = load_conversation_from_db(chat_id)


def is_only_emojis(text):
    """
    Prüft, ob ein Text nur aus Emojis und Leerzeichen besteht.

    Args:
        text (str): Eingabetext.

    Returns:
        bool: True, wenn der Text nur aus Emojis und Leerzeichen besteht, sonst False.
    """
    emoji_pattern = re.compile(
        r'^[\u2000-\u3300\u1F000-\u1F6FF\u1F900-\u1FAFF\u2600-\u26FF\u2700-\u27BF\s]+$',
        flags=re.UNICODE
    )
    return bool(emoji_pattern.fullmatch(text.strip()))

def is_fingilish(text):
    """
    Überprüft, ob der Text ausschließlich lateinische Buchstaben (Fingilish) enthält.
    
    Args:
        text (str): Eingabetext.
    
    Returns:
        bool: True, wenn der Text nur aus lateinischen Buchstaben und häufigen Sonderzeichen besteht, andernfalls False.
    """
    # Erlaubte Zeichen: lateinische Buchstaben, Leerzeichen, Ziffern und einige Satzzeichen
    return bool(re.match(r'^[a-zA-Z0-9\s.,?!\'"-]*$', text))

def fingilish_to_farsi(fingilish_text):
    """
    Hybrid Fingilish-to-Farsi: strict letter-to-letter transliteration, then AI polish using Q&A database for style and vocabulary.
    """
    if not is_fingilish(fingilish_text):
        return fingilish_text
    transliteration_map = {
        'a': 'ا', 'b': 'ب', 'c': 'ک', 'd': 'د', 'e': 'ه', 'f': 'ف', 'g': 'گ',
        'h': 'ح', 'i': 'ی', 'j': 'ج', 'k': 'ک', 'l': 'ل', 'm': 'م', 'n': 'ن',
        'o': 'و', 'p': 'پ', 'q': 'ق', 'r': 'ر', 's': 'س', 't': 'ت', 'u': 'و',
        'v': 'و', 'w': 'و', 'x': 'خ', 'y': 'ی', 'z': 'ز',
        'A': 'ا', 'B': 'ب', 'C': 'ک', 'D': 'د', 'E': 'ه', 'F': 'ف', 'G': 'گ',
        'H': 'ح', 'I': 'ی', 'J': 'ج', 'K': 'ک', 'L': 'ل', 'M': 'م', 'N': 'ن',
        'O': 'و', 'P': 'پ', 'Q': 'ق', 'R': 'ر', 'S': 'س', 'T': 'ت', 'U': 'و',
        'V': 'و', 'W': 'و', 'X': 'خ', 'Y': 'ی', 'Z': 'ز',
    }
    # Step 1: Letter-to-letter transliteration
    words = fingilish_text.split()
    transliterated_words = []
    for word in words:
        farsi_word = ''.join([transliteration_map.get(ch, ch) for ch in word])
        transliterated_words.append(farsi_word)
    transliterated_text = ' '.join(transliterated_words)

    # Step 2: AI polish with Q&A database context
    try:
        import openai
        # Get Q&A examples for style context
        qa_examples = get_limited_qa_data(prompt="", limit=5)
        style_examples = ""
        for qa in qa_examples:
            style_examples += f"پرسش: {qa[0]}\nپاسخ: {qa[1]}\n\n"
        
        prompt = (
            f"در زیر چند نمونه پرسش و پاسخ از دیتابیس ما آمده است. سبک و لحن و واژگان پاسخ‌ها را یاد بگیر:\n\n{style_examples}"
            "حالا این متن فینگلیش را به فارسی تبدیل کن. از همان سبک و واژگان نمونه‌های بالا استفاده کن:\n\n"
            f"متن فینگلیش: {fingilish_text}\n"
            f"ترجمه مستقیم: {transliterated_text}\n\n"
            "لطفاً این متن را به فارسی صحیح و روان تبدیل کن و از سبک و واژگان نمونه‌های بالا استفاده کن. "
            "اصطلاحات و کلمات فنی و کامپیوتری را به همان صورت لاتین (انگلیسی) حفظ کن. "
            "در پاسخ از ایموجی‌ها و استایل‌دهی استفاده کن. "
            "تعداد کلمات ترجمه باید تقریباً با متن اصلی برابر باشد و هیچ جمله یا توضیح اضافه ننویس. "
            "فقط متن ترجمه شده را برگردان:"
        )
        # Use the OpenAI client that's already imported at the top
        openai_client = OpenAI(api_key=openai.api_key)
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "تو یک دستیار فارسی‌زبان هستی که از سبک و واژگان دیتابیس Q&A استفاده می‌کنی."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=256,
            temperature=0.7,
        )
        farsi_text = response.choices[0].message.content.strip()
        # Remove any label/prefix
        import re
        farsi_text = re.sub(r"^[\s\n]*(متن ترجمه شده:|ترجمه:|ترجمه شده:|پاسخ:)[\s\n]*", "", farsi_text)
        return farsi_text
    except Exception as e:
        print(f"[Fingilish2Farsi AI Error]: {e}")
        return transliterated_text


def enhanced_fingilish_to_farsi(fingilish_text):
    """
    Enhanced Fingilish to Farsi translation that preserves technical terms in Latin letters.
    
    Args:
        fingilish_text (str): The input text in Fingilish.
        
    Returns:
        str: The translated text in Farsi with technical terms preserved in Latin.
    """
    if not is_fingilish(fingilish_text):
        return fingilish_text
    
    # Technical terms that should remain in Latin letters (only complete words)
    technical_terms = [
        'api', 'url', 'http', 'https', 'www', 'com', 'org', 'net', 'io', 'co',
        'html', 'css', 'js', 'json', 'xml', 'sql', 'php', 'python', 'java',
        'javascript', 'react', 'vue', 'angular', 'node', 'npm', 'git', 'ssh',
        'ftp', 'smtp', 'pop3', 'imap', 'dns', 'ip', 'tcp', 'udp', 'ssl', 'tls',
        'vpn', 'cdn', 'aws', 'azure', 'gcp', 'docker', 'kubernetes', 'nginx',
        'apache', 'mysql', 'postgresql', 'mongodb', 'redis', 'elasticsearch',
        'kafka', 'rabbitmq', 'memcached', 'jwt', 'oauth', 'oauth2',
        'rest', 'graphql', 'soap', 'rpc', 'grpc', 'protobuf', 'yaml', 'toml',
        'ini', 'env', 'log', 'tmp', 'var', 'etc', 'usr', 'bin', 'lib', 'src',
        'dist', 'build', 'test', 'dev', 'prod', 'staging', 'beta', 'alpha',
        'release', 'version', 'patch', 'minor', 'major', 'semver', 'changelog',
        'readme', 'license', 'contributing', 'docs', 'wiki', 'issue', 'pr',
        'merge', 'branch', 'commit', 'push', 'pull', 'clone', 'fork', 'star',
        'watch', 'follow', 'like', 'share', 'comment', 'post', 'tweet', 'retweet',
        'dm', 'pm', 'msg', 'email', 'sms', 'mms', 'call', 'video', 'audio',
        'image', 'photo', 'file', 'folder', 'directory', 'path',
        'filename', 'extension', 'format', 'size', 'type', 'mime', 'content',
        'header', 'footer', 'body', 'title', 'meta', 'tag', 'class', 'id',
        'style', 'script', 'link', 'img', 'div', 'span', 'p', 'h1', 'h2', 'h3',
        'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'table', 'tr', 'td', 'th', 'form',
        'input', 'button', 'select', 'option', 'textarea', 'label', 'fieldset',
        'legend', 'iframe', 'canvas', 'svg', 'source', 'track',
        'embed', 'object', 'param', 'area', 'map', 'base', 'head', 'html', 'body',
        'doctype', 'html5', 'css3', 'es6', 'es7', 'es8', 'es9', 'es10', 'es11',
        'ts', 'typescript', 'jsx', 'tsx', 'svelte', 'solid', 'lit',
        'webpack', 'vite', 'rollup', 'parcel', 'babel', 'eslint', 'prettier',
        'jest', 'mocha', 'chai', 'cypress', 'selenium', 'puppeteer', 'playwright',
        'postman', 'insomnia', 'curl', 'wget', 'scp', 'rsync', 'tar', 'zip',
        'gzip', 'bzip2', 'xz', 'rar', '7z', 'iso', 'img', 'vhd', 'vmdk',
        'ova', 'ovf', 'qcow2', 'raw', 'vdi', 'vbox', 'vmware', 'virtualbox',
        'hyperv', 'kvm', 'xen', 'lxc', 'lxd', 'containerd', 'cri', 'cni',
        'helm', 'kubectl', 'minikube', 'kind', 'k3s', 'rancher', 'openshift',
        'istio', 'linkerd', 'consul', 'etcd', 'zookeeper', 'hadoop', 'spark',
        'flink', 'storm', 'hive', 'pig', 'hbase', 'cassandra', 'couchdb',
        'neo4j', 'arangodb', 'orientdb', 'influxdb', 'prometheus', 'grafana',
        'kibana', 'logstash', 'beats', 'filebeat', 'metricbeat',
        'packetbeat', 'heartbeat', 'auditbeat', 'functionbeat', 'journalbeat',
        'winlogbeat', 'apm', 'apm-server'
    ]
    
    # Split text into words to preserve only complete technical terms
    words = fingilish_text.split()
    translated_words = []
    
    for word in words:
        # Check if the word (case-insensitive) is a technical term
        word_lower = word.lower()
        if word_lower in technical_terms:
            # Preserve the original case of the technical term
            translated_words.append(word)
        else:
            # This word should be translated using the original function
            translated_word = fingilish_to_farsi(word)
            translated_words.append(translated_word)
    
    # Join the words back together
    translated_text = ' '.join(translated_words)
    
    return translated_text


def extract_index_from_message(message_text):
    """
    Extrahiert die ID (Index) aus dem Nachrichtentext, basierend auf einem bekannten Format.
    Beispiel: "🔐 **ID:** <ID>\n..."
    """
    try:
        lines = message_text.split("\n")
        for line in lines:
            if line.startswith("🔐 **ID:**"):
                return int(line.replace("🔐 **ID:**", "").strip())
    except Exception as e:
        print(f"ERROR: Failed to extract index from message - {e}")
    return None



def delete_user_by_chat_id(chat_id):
    """
    Löscht einen Benutzer basierend auf der chat_id aus der Datenbank.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        print(f"DEBUG: Attempting to delete user with Chat ID: {chat_id}")
        cursor.execute("DELETE FROM users WHERE chat_id = ?", (chat_id,))
        conn.commit()
        rows_deleted = cursor.rowcount
        if rows_deleted > 0:
            print(f"DEBUG: Successfully deleted user with Chat ID: {chat_id}")
        else:
            print(f"DEBUG: No user found with Chat ID: {chat_id}")
        return rows_deleted > 0
    except Exception as e:
        print(f"ERROR: Failed to delete user by Chat ID: {e}")
        return False
    finally:
        conn.close()







def add_user(moftbar_username, chat_id):
    """
    Deletes any existing entry with the same `chat_id` and inserts the new user.
    """
    if chat_id is None:
        print(f"⚠️ WARNING: No `chat_id` provided for user {moftbar_username}, skipping storage.")
        return  # Skip if `chat_id` is None
    if moftbar_username == "!None!" or not moftbar_username:
        moftbar_username = f"User{chat_id}"  # Use fallback username

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        # Delete any existing entry with the same chat_id
        cursor.execute("DELETE FROM users WHERE chat_id = ?", (chat_id,))
        
        # Insert the new user with the provided chat_id and moftbar_username
        cursor.execute("INSERT INTO users (moftbar_username, chat_id) VALUES (?, ?)", (moftbar_username, chat_id))
        
        conn.commit()
        print(f"✅ DEBUG: User saved (replaced old entry) - Moftbar Username: {moftbar_username}, Chat ID: {chat_id}")
    except Exception as e:
        print(f"❌ ERROR: Error saving/updating user: {e}")
    finally:
        conn.close()



        

def get_user_by_chat_id(chat_id):
    """
    Ruft den Benutzer basierend auf der chat_id aus der Datenbank ab.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        #print(f"DEBUG: Fetching user for Chat ID: {chat_id}")
        cursor.execute("SELECT moftbar_username FROM users WHERE chat_id = ?", (chat_id,))
        result = cursor.fetchone()
        if result:
            return result[0]
        else:
            return None
    except Exception as e:
        print(f"ERROR: Failed to fetch user by chat_id: {e}")
        return None
    finally:
        conn.close()

def get_chat_id_by_moftbar_username(moftbar_username):
    """
    Gibt die Chat-ID zurück, wenn der Moftbar-Benutzername bekannt ist.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT chat_id FROM users WHERE moftbar_username = ?", (moftbar_username,))
        result = cursor.fetchone()
        print(f"DEBUG: Abruf für {moftbar_username} ergab: {result}")  # <--- Debugging
      
        if result:
            return result[0]
        else:
            return None  # Kein Eintrag gefunden
    except Exception as e:
        print(f"ERROR: Fehler beim Abrufen der Chat-ID für Moftbar-Username {moftbar_username}: {e}")
        return None
    finally:
        conn.close()


def update_moftbar_username(new_moftbar_username, chat_id):
    """
    Aktualisiert den MOFTBAR-Benutzernamen basierend auf chat_id.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        print(f"DEBUG: Updating Moftbar Username for Chat ID: {chat_id} to {new_moftbar_username}")
        cursor.execute(
            "UPDATE users SET moftbar_username = ? WHERE chat_id = ?",
            (new_moftbar_username, chat_id),
        )
        conn.commit()
        print(f"DEBUG: Updated Moftbar username to {new_moftbar_username}. Chat ID: {chat_id}")
        return ("saved")
    except Exception as e:
        print(f"ERROR: Failed to update Moftbar username - {e}")
    finally:
        conn.close()




def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Create ticket_history table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ticket_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id TEXT UNIQUE,
            chat_id INTEGER,
            moftbar_username TEXT,
            ticket_text TEXT,
            ai_response TEXT,
            admin_response TEXT,
            status TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create conversation_history table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            role TEXT,
            content TEXT,
            timestamp REAL
        )
    ''')
    
    # Create qa table if it doesn't exist
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS qa (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT,
            answer TEXT,
            message_id INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create users table if it doesn't exist
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            moftbar_username TEXT UNIQUE,
            chat_id INTEGER UNIQUE,
            telegram_username TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ Database initialized with all required tables")






# List QA Entries
def list_qa():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, question, answer FROM qa")
    data = cursor.fetchall()
    conn.close()
    return data
# Write Q&A entries to a file
def save_qa_to_file(entries, filename="qa_entries.txt"):
    with open(filename, "w", encoding="utf-8") as file:
        for id, question, answer in entries:
            file.write(f"ID: {id}\nQuestion: {question}\nAnswer: {answer}\n\n")
    print(f"Q&A Entries saved to {filename}")

async def delete_qa_from_channel(entry_id):
    """
    Deletes a QA entry from both the Telegram channel and the database.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        # Step 1: Fetch question and message_id from DB
        cursor.execute("SELECT question, message_id FROM qa WHERE id = ?", (entry_id,))
        entry = cursor.fetchone()

        if not entry:
            print(f"❌ ERROR: No QA entry found with ID {entry_id} in the database.")
            return False  # Stop execution if entry is not found

        question, message_id = entry  # Unpack DB result

        # Step 2: Delete the message from Telegram Channel (if message_id exists)
        if message_id:
            try:
                await client.delete_messages(channel_name, message_id)
                print(f"✅ DEBUG: Deleted message with ID {message_id} from Telegram channel.")
            except Exception as e:
                print(f"⚠️ WARNING: Could not delete message ID {message_id} from channel - {e}")

        # Step 3: Remove entry from the database
        cursor.execute("DELETE FROM qa WHERE id = ?", (entry_id,))
        conn.commit()
        print(f"✅ DEBUG: Deleted QA entry from database - ID: {entry_id}")

        return True

    except Exception as e:
        print(f"❌ ERROR: Failed to delete QA entry - {e}")
        return False
    finally:
        conn.close()

def add_qa_with_image(question, answer=None, image_path=None):
    """
    Fügt eine neue Frage-Antwort-Paarung mit Bild hinzu oder aktualisiert sie bei Duplikaten.
    """
    if not question:
        print("❌ ERROR: Cannot add Q&A with an empty question.")
        return False  # ✅ Exit function safely
    if  question:
        question  = clean_text(question)
    

    if is_mostly_numbers(question):
        print(f"\n✅ Nothing to learn from digits: {reverse_text(question)}") 
        return False
   
    if "✅" in question:
        print(f"\n✅ in question wrong question to learn: {reverse_text(question)}") 
        return False
    
    if contains_email(question):
        print("✅ The question contains an email.")
        return False
   

    print(f"\n\n\nadd_qa_with picture ques{reverse_text(question)}") 


    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        # Entferne den alten Eintrag, falls vorhanden
        cursor.execute("DELETE FROM qa WHERE question = ?", (question,))
        
        # Add the new entry
        cursor.execute("INSERT INTO qa (question, answer, image_path) VALUES (?, ?, ?)", (question, answer, image_path))
        conn.commit()
        print(f"DEBUG: QA with image added/updated - Question: {reverse_text(question)}, Answer: Image Path: {image_path}")
        entry_id = cursor.lastrowid  # Get the ID of the inserted or updated entry

        asyncio.create_task(post_qa_with_image_to_channel(entry_id, question, image_path))

        return True
    except Exception as e:
        print(f"ERROR: Error adding/updating QA: {e}")
        return False
    finally:
        conn.close()



# Delete QA Entry by ID
def delete_qa(entry_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM qa WHERE id = ?", (entry_id,))
    conn.commit()
    print(f"DEBUG: Deleted QA entry with ID: {entry_id}")
    conn.close()
# Add QA Pair

def contains_email(text):
    email_pattern = re.compile(r'[\w\.-]+@[\w\.-]+\.\w+')
    return bool(email_pattern.search(text))

# Define unwanted words (case-insensitive) and phrases
UNWANTED_WORDS = {
    "slam", "hi", "hello", "helo", "doroud", "درود", "وقت بخیر", "صبح بخیر", "روز بخیر",
    "slm", "salam", "salam o khste nabashid", "salm", "سلم", "سلام", "سلام مجدد", 
    "سلام و درود", "خسته نباشید", "سلام ادمین", "ادمین", "admin", "khasteh nabashid",
    "❤️", "❤️❤️", "❤️❤️❤️", "🙏", "👍", "🌹"
}

# Define unwanted words (case-insensitive) and phrases
UNWANTED_WORDS = {
    "slam", "hi", "hello", "helo", "doroud", "درود", "وقت بخیر", "صبح بخیر", "روز بخیر",
    "slm", "salam", "salam o khste nabashid", "salm", "سلم", "سلام", "سلام مجدد",
    "سلام و درود", "خسته نباشید", "سلام ادمین", "ادمین", "admin", "khasteh nabashid",
    "❤️", "❤️❤️", "❤️❤️❤️", "🙏", "👍", "🌹"
}

def remove_emojis(text):
    # Example: Remove only emoji characters, preserving text
    emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F"  # emoticons
        u"\U0001F300-\U0001F5FF"  # symbols & pictographs
        u"\U0001F680-\U0001F6FF"  # transport & map symbols
        u"\U0001F700-\U0001F77F"  # alchemical symbols
        u"\U0001F780-\U0001F7FF"  # Geometric Shapes Extended
        u"\U0001F800-\U0001F8FF"  # Supplemental Symbols and Pictographs
        u"\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
        u"\U0001FA00-\U0001FA6F"  # Chess Symbols
        u"\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
        u"\U00002702-\U000027B0"  # Dingbats
        u"\U000024C2-\U0001F251" 
        "]+", flags=re.UNICODE)
    return emoji_pattern.sub(r'', text)

def clean_text(text):
    """
    Cleans the text by removing:
    - AI-generated text ("🤖Q&A:", "پاسخگوی خودکار:", "✅")
    - Question marks (English `?` and Farsi `؟`) if uncommented
    - All words in `UNWANTED_WORDS`
    - Optional emoji removal
    - Extra spaces (replaces multiple spaces with a single space)
    - Preserves `\n`
    """
    if not text or not isinstance(text, str):
        print(f"⚠️ DEBUG: Invalid input to clean_text: {text}")
        return text  # Return original to avoid None

    #print(f"DEBUG: Input text: {text}")

    # Remove AI-generated text and system messages
    original_text = text
    text = re.sub(r"✅\s*", "", text)
    #print(f"DEBUG: After removing '✅': {text}")
    text = re.sub(r"🤖\s*Q&A[:：]?\s*", "", text, flags=re.IGNORECASE)
    #print(f"DEBUG: After removing '🤖Q&A:': {text}")
    text = re.sub(r"پاسخگوی خودکار[:：]?\s*", "", text)
    #print(f"DEBUG: After removing 'پاسخگوی خودکار:': {text}")

    # Remove question marks (English & Farsi) - Uncomment only if needed
    # text = re.sub(r"[؟?]", "", text)
    # print(f"DEBUG: After removing question marks: {text}")

    # Remove all words from UNWANTED_WORDS while keeping new lines
    words = text.split()
    cleaned_words = [word for word in words if word.lower() not in UNWANTED_WORDS]
    text = " ".join(cleaned_words) if cleaned_words else original_text  # Fallback to original if all words removed
    #print(f"DEBUG: After removing UNWANTED_WORDS: {text}")

    # Remove all emojis (optional, comment out if not desired)
    text = remove_emojis(text)
    #print(f"DEBUG: After removing emojis: {text}")

    # Normalize spaces while preserving `\n`
    text = re.sub(r"[ \t]+", " ", text)
    #print(f"DEBUG: After normalizing spaces: {text}")
    text = re.sub(r"\n\s+", "\n", text)
    #print(f"DEBUG: After cleaning new line spaces: {text}")
    text = text.strip()
    #print(f"DEBUG: After strip: {text}")

    if not text:
        print(f"⚠️ DEBUG: clean_text resulted in empty string, returning original: {original_text}")
        return original_text
    return text


def add_qa(question, answer):
    if not question:
        print("❌ ERROR: Cannot add Q&A with an empty question.")
        return False  # ✅ Exit function safely

    if  question:

        question  = clean_text(question)



    if is_mostly_numbers(question) or is_mostly_numbers(answer):
        print(f"\n✅ Nothing to learn from digits: {question}") 
        return
    if not isinstance(question, str) or not isinstance(answer, str):
        print(f"❌ ERROR: Invalid question or answer type. Question: {type(question)}, Answer: {type(answer)}")
        return  # Stop execution if question or answer is not a string

    if "✅" in question :
        print("⚠️ WARNING: Question contains an ✅ character.")
        return
    
    if len(question) < 3 :
        print(f"⚠️ WARNING: Question:----{reverse_text(question)}----  too short <3.")
        return
    if len(answer) < 3:
        print("⚠️ WARNING:  answer:----{reverse_text(answer)}---- is too short <3.")
        return

    

    if contains_email(answer):
        print("⚠️ The answer contains an email.")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()


      
            # Check if the question already exists
    cursor.execute("SELECT id FROM qa WHERE question = ?", (question,))
    existing_entry = cursor.fetchone()

    if existing_entry:
        print(f"DEBUG: Frage existiert bereits in der Datenbank, wir überschrieben {existing_entry[0]}")


    try:
        # INSERT OR REPLACE wird verwendet, um bei Duplikaten den bestehenden Eintrag zu ersetzen
        cursor.execute("""
            INSERT OR REPLACE INTO qa (id, question, answer)
            VALUES (
                (SELECT id FROM qa WHERE question = ?),
                ?, ?
            )
        """, (question, question, answer))
        
        conn.commit()
        entry_id = cursor.lastrowid  # Get the ID of the inserted or updated entry
        print(f"DEBUG: New/Updated QA ID: {entry_id}, Question: {reverse_text(question)}, Answer: {reverse_text(answer)}")
        
        # Starte eine asynchrone Aufgabe
        asyncio.create_task(post_to_channel(entry_id, question, answer))
    except sqlite3.IntegrityError as e:
        print(f"DEBUG: Database error - {e}")
    finally:
        conn.close()
    


async def post_qa_with_image_to_channel(entry_id, question, image_path):
    """
    Postet ein bestehendes Bild mit ID und Frage als Caption in den Telegram-Kanal und speichert die message_id.
    
    Args:
        entry_id (int): Die ID des Eintrags.
        question (str): Die Frage, die als Teil der Caption gepostet wird.
        image_path (str): Der Pfad zum Bild, das gepostet werden soll.
    """
    try:
        # Caption mit ID und Frage vorbereiten
        caption = f"🔐 **ID:** {entry_id}\n**پرسش:** {question}"

        # Bild in den Kanal posten
        sent_message = await client.send_file(channel_name, image_path, caption=caption)


        # Message ID speichern
        save_message_id_to_db(entry_id, sent_message.id, question)
        print(f"DEBUG: Posted existing image to channel - ID: {entry_id}, Message ID: {sent_message.id}")
    except Exception as e:
        print(f"ERROR: Failed to post image to channel - {e}")






async def post_to_channel(entry_id, question=None, answer=""):
    """
    Posts a Q&A message to the Telegram channel and saves the message_id.
    Ensures `question` is always defined to prevent errors.
    """

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Check if the question was already posted
    cursor.execute("SELECT message_id FROM qa WHERE id = ?", (entry_id,))
    existing_entry = cursor.fetchone()

    if existing_entry and existing_entry[0]:
        print(f"DEBUG: Question already posted to the channel, overwriting... ID: {entry_id}")

    # Fetch question only if not provided
    if question is None:
        cursor.execute("SELECT question FROM qa WHERE id = ?", (entry_id,))
        entry = cursor.fetchone()

        if not entry:
            conn.close()
            print(f"❌ ERROR: No question found for entry ID {entry_id}. Using a placeholder.")
            question = "[UNKNOWN QUESTION]"  # ✅ Assign a default value to prevent errors
        else:
            question = entry[0]  # ✅ Assign fetched question

    conn.close()  # ✅ Ensure connection is properly closed
    reversed_question = reverse_text(question)
    reversed_answer = reverse_text(answer)

    print (f"\n\n🔐 **ID:** {entry_id}\n**پرسش:** {reversed_question}\n**پاسخ:** {reversed_answer}")



    try:
        message = f"🔐 **ID:** {entry_id}\n**پرسش:** {question}\n**پاسخ:** {answer}"
        sent_message = await safe_send_message(client, channel_name, message)
        save_message_id_to_db(entry_id, sent_message.id, question)  # ✅ Save message_id to the database
    except Exception as e:
        print(f"❌ ERROR: Failed to post Q&A to channel - {e}")


def save_message_id_to_db(entry_id, message_id, question=None):
    """
    Saves the message_id of a Telegram message in the database.
    Also attempts to find a similar question in the database using fuzzy matching.
    """
    
    if not entry_id or not message_id:
        print(f"❌ ERROR: Invalid entry_id ({entry_id}) or message_id ({message_id}).")
        return False  # ✅ Prevents database errors if values are missing

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        # ✅ Save message_id in the database
        cursor.execute("UPDATE qa SET message_id = ? WHERE id = ?", (message_id, entry_id))
        conn.commit()
        print(f"✅ DEBUG: Saved message_id {message_id} for entry ID {entry_id}.")
    except Exception as e:
        print(f"❌ ERROR: Failed to save message_id {message_id} - {e}")
    finally:
        conn.close()  # ✅ Ensure connection is properly closed

    # ✅ If no question provided, skip matching
    if question is None:
        return None

    # ✅ Fetch all Q&A pairs for fuzzy matching
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT question, answer FROM qa")
        data = cursor.fetchall()
        conn.close()

        if not data:
            return None  # ✅ Prevents processing if no data is available

        questions = {q: a for q, a in data}
        result = process.extractOne(question, questions.keys(), scorer=fuzz.token_sort_ratio)

        if result:
            if result[1] >= 80:  # ✅ Adjusted threshold for better matching
                print(f"✅ DEBUG: Found matching QA in database - Question: \n{reverse_text(result[0])}, Score: {result[1]}")
                return questions[result[0]]
            else:
                print(f"⚠️ DEBUG: No sufficient match in database - \nInput: {question}, Best Match: {result[0]}, Score: {result[1]}")
    except Exception as e:
        print(f"❌ ERROR: Failed during fuzzy matching - {e}")
    finally:
        conn.close()  # ✅ Ensure the connection is always closed

    return None

# Search in Channel
async def search_in_channel(question):
    try:
        history = await client(GetHistoryRequest(
            peer=channel_name,
            limit=50,
            offset_date=None,
            offset_id=0,
            max_id=0,
            min_id=0,
            add_offset=0,
            hash=0
        ))
        messages = history.messages
        for message in messages:
            if message.message and question in message.message.lower():
                print(f"DEBUG: Found matching message in channel - Message: {reverse_text(message.message)}")
                return message.message
        print("DEBUG: No match found in channel")
        return None
    except Exception as e:
        print(f"DEBUG: Error while searching in channel - {e}")
        return None

# Notify Admins About Mode Change
async def notify_admins(event):
    global adminConfirm, WAIT_TIME_FOR_ADMIN, WAIT_TIME_MIN, WAIT_TIME_MAX, DEFAULT_QA_ACCURACY, auto_response_count, last_manual_response_time, fingilish_translation_enabled  # ✅ Ensure global usage
    await client.delete_messages(event.chat_id, event.message.id)
    if adminConfirm:
        adminConfirm_txt = "ON"
        WAIT_TIME_FOR_ADMIN = WAIT_TIME_MAX
    else :
        adminConfirm_txt = "OFF"
        WAIT_TIME_FOR_ADMIN = WAIT_TIME_MIN
    
    # Check if this is a status request (/? command)
    is_status_request = event.raw_text in ["/status", "/stats", "/?", "/stat"]
    
    if is_status_request:
        # Detailed status information
        current_min_minutes = WAIT_TIME_MIN // 60
        current_max_minutes = WAIT_TIME_MAX // 60
        current_wait_minutes = WAIT_TIME_FOR_ADMIN // 60
        
        # Get pending item counts
        total_pending, pending_tickets, pending_tokens, pending_screenshots_count = count_pending_items()
        
        status_message = f"""📊 **Bot Status Report**

🤖 **Mode:** {mode.upper()}
👨‍💼 **Admin Confirm:** {adminConfirm_txt}
⏱️ **Current Wait Time:** {current_wait_minutes} minutes

⏰ **Wait Time Settings:**
• Minimum: {current_min_minutes} minutes
• Maximum: {current_max_minutes} minutes
• Dynamic: {'✅' if adminConfirm else '❌'} (Admin active → Max, AI responds → Min)

📋 **Pending Items:**
• 🎫 Tickets: {pending_tickets}
• 🔍 Tokens: {pending_tokens}
• 📷 Screenshots: {pending_screenshots_count}
• 📊 Total: {total_pending}

🎯 **QA Accuracy:** {DEFAULT_QA_ACCURACY}% (Range: 52-80%)

🌐 **Fingilish Translation:** {'✅ ON' if fingilish_translation_enabled else '❌ OFF'}

📈 **Auto Response Count:** {auto_response_count}
🕒 **Last Manual Response:** {time.strftime('%H:%M:%S', time.localtime(last_manual_response_time)) if last_manual_response_time > 0 else 'Never'}

💡 **Quick Commands:**
• `/min [minutes]` - Set minimum wait time
• `/max [minutes]` - Set maximum wait time  
• `/% [percentage]` - Set QA accuracy
• `/fin` or `/finoff` - Toggle Fingilish translation
• `/clean` - Clear all pending timers
• `/reset` - Reset all tickets"""
        
        notify_message = await safe_send_message(client, event.chat_id, status_message)
    else:
        # Simple mode change notification
        notify_message = await safe_send_message(client, event.chat_id, f"mode: {mode} \n admin-confirm: {adminConfirm_txt}")





    
    if event.is_group or event.is_channel  :
        if  event.chat_id != ticket_channel_chat_ID:  # this is where tickets get a respunse we reply 

       
            #print("DEBUG: Ignored message from a group or channel.")
            return 
        
    if notify_message:

        await asyncio.sleep(30)  # Wait for 10 seconds
        await notify_message.delete()  # Delete the message



    blacklist = load_blacklist()
    chat_id = event.chat_id

    is_never = str(chat_id) in blacklist
    notify_message = await safe_send_message(client, event.chat_id, f"Always(AI) {is_always_on(chat_id)}\n /never(for this chat):{is_never} \n ")
    await asyncio.sleep(10)  # Wait for 10 seconds
    await notify_message.delete()  # Delete the message



                    

   
    print(f"DEBUG: Admins notified about mode change to {mode}")

@client.on(events.NewMessage(pattern="/.*"))
async def handle_mode_change(event):
    global mode
    global user_states
    global adminConfirm
    global WAIT_TIME_FOR_ADMIN
    global WAIT_TIME_MIN
    global WAIT_TIME_MAX
    global fingilish_translation_enabled

    sender = await event.get_sender()
    chat_id = event.chat_id
    if not chat_id or isinstance(chat_id, dict) and not chat_id: #chat id check
        print(f"❌ DEBUG: Invalid chat_id detected: {chat_id}")
        return

    # Debug sender information
    sender_username = getattr(sender, 'username', None)
    sender_id = getattr(sender, 'id', None)
    print(f"DEBUG: Sender details - ID: {sender_id}, Username: {sender_username}, Type: {type(sender)}")
    
    # Check if the sender is an admin using chat ID or if it's the bot itself
    is_admin = is_admin_chat_id(chat_id) or is_bot_sender(sender_id)
    print(f"DEBUG: Command '{event.raw_text}' from user '{sender_username}' (chat_id: {chat_id}, sender_id: {sender_id}, bot_id: {bot_id}, is_admin: {is_admin}) in chat {event.chat_id}")
    
    # Handle commands based on chat type and user permissions
    if event.chat_id == ticket_channel_chat_ID:
        # In ticket channel: process all commands (no admin check needed since only admins have access)
        print(f"Command in Ticket Channel: {event.raw_text} from {sender_username} (Chat ID: {chat_id})")
        
        # Handle general admin commands
        await handle_general_admin_commands(event)
        
        # Handle percentage command specifically for ticket channel
        if event.raw_text.startswith("/%"):
            await handle_percentage_command(event)
        
        # Handle chat-specific commands (only when replying to tickets)
        await handle_chat_specific_commands(event)
        
    else:
        # In user chats: handle chat-specific commands
        if is_admin:
            # Admins can use all commands in user chats
            print(f"Admin Command in User Chat: {event.raw_text}")
            await handle_general_admin_commands(event)
            await handle_chat_specific_commands(event)
        else:
            # Users can only use /start command
            if event.raw_text.lower() in ["/start", "start", "start/"]:
                print(f"User Command: {event.raw_text}")
                # Handle start command in main message handler
                return
            else:
                print(f"DEBUG: User command '{event.raw_text}' ignored. Only /start allowed for users.")
                return

async def handle_general_admin_commands(event):
    """Handle general admin commands that work in both ticket channel and user chats"""
    global mode, adminConfirm, WAIT_TIME_FOR_ADMIN, WAIT_TIME_MIN, WAIT_TIME_MAX, fingilish_translation_enabled, auto_response_count
    
    await user_states.set(event.chat_id, "technical_menu")
    
    if event.raw_text == "/on":
        mode = "on"
        await user_states.clear()
        print("DEBUG: Mode changed to ON")
        await send_admin_response_with_cleanup(client, event.chat_id, "✅ **Mode:** ON", True, event.message.id)
        await notify_admins(event)
    
    elif event.raw_text == "/learn" or event.raw_text == "/l":
        mode = "learn"
        await user_states.clear()
        print("DEBUG: Mode changed to LEARN")
        await send_admin_response_with_cleanup(client, event.chat_id, "✅ **Mode:** LEARN", True, event.message.id)
        await notify_admins(event)
    
    elif event.raw_text == "/off" or event.raw_text == "/stop":
        mode = "off"
        await user_states.clear()
        print("DEBUG: Mode changed to OFF")
        await send_admin_response_with_cleanup(client, event.chat_id, "✅ **Mode:** OFF", True, event.message.id)
        await notify_admins(event)
        
    elif event.raw_text == "/training" or event.raw_text == "/t" or event.raw_text == "/train":
        mode = "on"
        adminConfirm = True
        WAIT_TIME_FOR_ADMIN = WAIT_TIME_MAX
        await user_states.clear()
        print("DEBUG: Mode changed to training")
        await send_admin_response_with_cleanup(client, event.chat_id, "✅ **Mode:** TRAINING", True, event.message.id)
        await notify_admins(event)
        
    elif event.raw_text == "/sleep" or event.raw_text == "/s":
        mode = "on"
        adminConfirm = False
        WAIT_TIME_FOR_ADMIN = WAIT_TIME_MIN
        await user_states.clear()
        print("DEBUG: Mode changed to Sleep...")
        await send_admin_response_with_cleanup(client, event.chat_id, "✅ **Mode:** SLEEP", True, event.message.id)
        await notify_admins(event)
        
    elif event.raw_text == "/status" or event.raw_text == "/stats" or event.raw_text == "/?" or event.raw_text == "/stat":
        await send_admin_response_with_cleanup(client, event.chat_id, "📊 **Status:** Checking...", True, event.message.id)
        await notify_admins(event)
        
    elif event.raw_text == "/admin" or event.raw_text == "/adminon":
        adminConfirm = True
        WAIT_TIME_FOR_ADMIN = WAIT_TIME_MAX
        await send_admin_response_with_cleanup(client, event.chat_id, "✅ **ADMIN:** ON", True, event.message.id)
        
    elif event.raw_text == "/adminoff":
        print(f"DEBUG: ROBOT active admin approval mode is OFF now!.")
        adminConfirm = False
        WAIT_TIME_FOR_ADMIN = WAIT_TIME_MIN
        await send_admin_response_with_cleanup(client, event.chat_id, "✅ **ADMIN:** OFF", True, event.message.id)
        
    elif event.raw_text == "/isadmin":
        # Add current user as admin
        chat_id = event.chat_id
        sender = await event.get_sender()
        sender_username = getattr(sender, 'username', 'Unknown')

        if is_admin_chat_id(chat_id):
            await send_admin_response_with_cleanup(client, event.chat_id, f"✅ شما قبلاً ادمین هستید! (Chat ID: {chat_id})", True, event.message.id)
        else:
            add_admin_chat_id(chat_id)
            await send_admin_response_with_cleanup(client, event.chat_id, f"✅ شما به عنوان ادمین اضافه شدید! (Chat ID: {chat_id}, Username: @{sender_username})", True, event.message.id)
            print(f"✅ New admin added: Chat ID {chat_id}, Username @{sender_username}")

    elif event.raw_text == "/isnotadmin" or event.raw_text == "/isuser":
        # Remove current user from admin list
        chat_id = event.chat_id
        sender = await event.get_sender()
        sender_username = getattr(sender, 'username', 'Unknown')

        if remove_admin_chat_id(chat_id):
            await send_admin_response_with_cleanup(client, event.chat_id, f"❌ شما از لیست ادمین‌ها حذف شدید! (Chat ID: {chat_id})", True, event.message.id)
            print(f"❌ Admin removed: Chat ID {chat_id}, Username @{sender_username}")
        else:
            await send_admin_response_with_cleanup(client, event.chat_id, f"ℹ️ شما در لیست ادمین‌ها نبودید! (Chat ID: {chat_id})", True, event.message.id)

    elif event.raw_text == "/removeadmin":
        # Remove current user from admin list
        chat_id = event.chat_id
        sender = await event.get_sender()
        sender_username = getattr(sender, 'username', 'Unknown')

        if remove_admin_chat_id(chat_id):
            await send_admin_response_with_cleanup(client, event.chat_id, f"❌ شما از لیست ادمین‌ها حذف شدید! (Chat ID: {chat_id})", True, event.message.id)
            print(f"❌ Admin removed: Chat ID {chat_id}, Username @{sender_username}")
        else:
            await send_admin_response_with_cleanup(client, event.chat_id, f"ℹ️ شما در لیست ادمین‌ها نبودید! (Chat ID: {chat_id})", True, event.message.id)

    elif event.raw_text == "/listadmins":
        # List all admin chat IDs
        if admin_chat_ids:
            admin_list = "\n".join([f"• Chat ID: {chat_id}" for chat_id in admin_chat_ids])
            await send_admin_response_with_cleanup(client, event.chat_id, f"📋 لیست ادمین‌ها:\n{admin_list}\n\nتعداد کل: {len(admin_chat_ids)}", True, event.message.id)
        else:
            await send_admin_response_with_cleanup(client, event.chat_id, "📋 هیچ ادمینی در لیست وجود ندارد.", True, event.message.id)
            
    elif event.raw_text == "/debug_history":
        # Debug conversation history for current chat
        chat_id = event.chat_id
        db_history = load_conversation_from_db(chat_id)
        memory_history = conversation_history.get(chat_id, [])
        
        debug_info = f"🔍 **Debug Conversation History**\n\n"
        debug_info += f"**Chat ID:** {chat_id}\n"
        debug_info += f"**Database entries:** {len(db_history)}\n"
        debug_info += f"**Memory entries:** {len(memory_history)}\n\n"
        
        if db_history:
            debug_info += "**Database History (last 5):**\n"
            for i, entry in enumerate(db_history[-5:], 1):
                debug_info += f"{i}. {entry['role']}: {entry['content'][:50]}...\n"
        else:
            debug_info += "**Database History:** Empty\n"
            
        if memory_history:
            debug_info += "\n**Memory History (last 5):**\n"
            for i, entry in enumerate(memory_history[-5:], 1):
                debug_info += f"{i}. {entry['role']}: {entry['content'][:50]}...\n"
        else:
            debug_info += "\n**Memory History:** Empty\n"
            
        await send_admin_response_with_cleanup(client, event.chat_id, debug_info, True, event.message.id)
        
    elif event.raw_text == "/test_history":
        # Add test conversation history for current chat
        chat_id = event.chat_id
        test_messages = [
            ("user", "سلام، چطوری؟"),
            ("bot", "سلام و عرض ادب! ممنون، خوبم. چطور می‌تونم کمکتون کنم؟"),
            ("user", "یک سوال دارم"),
            ("bot", "بله، بفرمایید. در خدمت شما هستم."),
            ("user", "ممنون از کمکتون"),
            ("bot", "خواهش می‌کنم! اگر سوال دیگه‌ای دارید، در خدمت هستم.")
        ]
        
        for role, content in test_messages:
            await append_to_conversation_history(chat_id, role, content)
            await asyncio.sleep(0.1)  # Small delay between saves
        
        await send_admin_response_with_cleanup(client, event.chat_id, f"✅ {len(test_messages)} پیام تست به تاریخچه اضافه شد. از /debug_history برای بررسی استفاده کنید.", True, event.message.id)
        
    elif event.raw_text.startswith("/prompt") or event.raw_text.startswith("/addprompt"):
        prompt_to_add = event.raw_text.split(maxsplit=1)
        if len(prompt_to_add) > 1:  # Check if there is content
            content = prompt_to_add[1].strip()  # Den Rest des Textes nach dem Befehl
        notify_message = await safe_send_message(client, event.chat_id, f" new prompt to add :: {content}.")
        print(f" new prompt to add :: {content}.")  # Nachricht senden
        add_prompt("user", content)
        

        
    elif event.raw_text.startswith("/bonous"):
        message = event.raw_text
        sender = await event.get_sender()
        is_admin = sender and sender.username and sender.username.lstrip('@') in admin_usernames

        # Splitte die Nachricht, um den neuen Text zu extrahieren
        parts = message.split(" ", 1)  # Teilt bei erstem Leerzeichen
        new_text = parts[1].strip() if len(parts) > 1 else None

        if is_admin and new_text:
            # Admin hat neuen Text angegeben, aktualisiere BONUS_TEXT
            global BONUS_TEXT
            BONUS_TEXT = new_text
            success = save_bonus_text_to_file(BONUS_TEXT)
            if success:
                await safe_send_message(client, event.chat_id, "✅ متن جوایز با موفقیت به‌روزرسانی و در فایل ذخیره شد!")
                print(f"\n\n\n\n\n\n  {reverse_text("✅ متن جوایز با موفقیت به‌روزرسانی و در فایل ذخیره شد!")})")

            else:
                await safe_send_message(client, event.chat_id, "❌ خطا در ذخیره متن جوایز!")
                print(f"\n\n\n\n\n\n  {reverse_text("❌ خطا در ذخیره متن جوایز!")})")

        elif is_admin and not new_text:
            # Admin hat keinen neuen Text angegeben, speichere aktuellen BONUS_TEXT
            success = save_bonus_text_to_file(BONUS_TEXT)
            if success:
                await safe_send_message(client, event.chat_id, "✅ متن فعلی جوایز در فایل ذخیره شد!")
            else:
                await safe_send_message(client, event.chat_id, "❌ خطا در ذخیره متن جوایز!")
        elif not is_admin and new_text:
            # Non-admin trying to change text
            await safe_send_message(client, event.chat_id, "⚠️ فقط ادمین‌ها می‌توانند متن جوایز را تغییر دهند!")
        
        # Show the current BONUS_TEXT (for admins and non-admins)
        print(f"\n\n\n\n\n\n  BONUS_TEXT = {reverse_text(BONUS_TEXT)})")
        
    elif event.raw_text.startswith("/reg"):
        message = event.raw_text.strip()

        parts = message.split(" ", 1)
        if len(parts) < 2:
            await event.reply("نام کوتاه بود...")
            print("DEBUG: No new username provided.")
            return
        new_moftbar_username = parts[1].strip()
        await client.delete_messages(event.chat_id, event.message.id)
        notify_message = await safe_send_message(client, event.chat_id, f".نام کاربری برای پشتیبانی ذخیره شد: {new_moftbar_username}")
        
        await handle_change_command(event, message, event.chat_id)
        
    elif event.raw_text in ["reset_tickets", "/reset", "/resetall"]:
        await client.delete_messages(event.chat_id, event.message.id)
        await reset_tickets(event.chat_id)
        
    elif event.raw_text in ["/clean","clean", "/clear_all", "/clear"]:
        await client.delete_messages(event.chat_id, event.message.id)
        # Get counts before clearing to show in notification
        total_pending, pending_tickets, pending_tokens, pending_screenshots_count = count_pending_items()
        # Reset auto_response_count to 0
        auto_response_count = 0
        print(f"🔄 DEBUG: auto_response_count reset to 0 by /clean command")
        await clear_timers(event)
        await reset_tickets(event.chat_id)
        await manage_separator("canceled")
        # Send notification about auto_response_count reset
        notify_message = await safe_send_message(client, event.chat_id, f"✅ All tickets removed: {total_pending} items (Tickets: {pending_tickets}, Tokens: {pending_tokens}, Screenshots: {pending_screenshots_count}). Auto response count reset to 0.")
        await asyncio.sleep(3)
        await notify_message.delete()
        
    elif event.raw_text == "/fin":
        fingilish_translation_enabled = True
        await client.delete_messages(event.chat_id, event.message.id)
        notify_message = await safe_send_message(client, event.chat_id, "✅ Fingilish translation enabled!")
        print(f"DEBUG: Fingilish translation enabled by admin")
        await asyncio.sleep(3)
        await notify_message.delete()
        
    elif event.raw_text == "/finoff":
        fingilish_translation_enabled = False
        await client.delete_messages(event.chat_id, event.message.id)
        notify_message = await safe_send_message(client, event.chat_id, "❌ Fingilish translation disabled!")
        print(f"DEBUG: Fingilish translation disabled by admin")
        await asyncio.sleep(3)
        await notify_message.delete()
        
    elif event.raw_text.startswith("/min"):
        message = event.raw_text
        parts = message.split(" ", 1)
        new_min_time = parts[1].strip() if len(parts) > 1 else None

        if new_min_time:
            try:
                min_minutes = int(new_min_time)
                if 1 <= min_minutes <= 120:
                    WAIT_TIME_MIN = min_minutes * 60  # Convert to seconds
                    await safe_send_message(client, event.chat_id, f"✅ حداقل زمان انتظار به {min_minutes} دقیقه تغییر یافت!")
                    print(f"DEBUG: Min wait time changed to {min_minutes} minutes ({WAIT_TIME_MIN} seconds)")
                else:
                    await safe_send_message(client, event.chat_id, "❌ حداقل زمان باید بین 1 تا 120 دقیقه باشد!")
                    print(f"DEBUG: Invalid min time: {min_minutes}")
            except ValueError:
                await safe_send_message(client, event.chat_id, "❌ لطفاً یک عدد صحیح بین 1 تا 120 وارد کنید!")
                print(f"DEBUG: Invalid min time value: {new_min_time}")
        else:
            # Show current min time
            current_min_minutes = WAIT_TIME_MIN // 60
            await safe_send_message(client, event.chat_id, f"📊 حداقل زمان فعلی انتظار: {current_min_minutes} دقیقه")
            print(f"DEBUG: Current min wait time: {current_min_minutes} minutes")
        
    elif event.raw_text.startswith("/max"):
        message = event.raw_text
        parts = message.split(" ", 1)
        new_max_time = parts[1].strip() if len(parts) > 1 else None

        if new_max_time:
            try:
                max_minutes = int(new_max_time)
                if 1 <= max_minutes <= 120:
                    WAIT_TIME_MAX = max_minutes * 60  # Convert to seconds
                    await safe_send_message(client, event.chat_id, f"✅ حداکثر زمان انتظار به {max_minutes} دقیقه تغییر یافت!")
                    print(f"DEBUG: Max wait time changed to {max_minutes} minutes ({WAIT_TIME_MAX} seconds)")
                else:
                    await safe_send_message(client, event.chat_id, "❌ حداکثر زمان باید بین 1 تا 120 دقیقه باشد!")
                    print(f"DEBUG: Invalid max time: {max_minutes}")
            except ValueError:
                await safe_send_message(client, event.chat_id, "❌ لطفاً یک عدد صحیح بین 1 تا 120 وارد کنید!")
                print(f"DEBUG: Invalid max time value: {new_max_time}")
        else:
            # Show current max time
            current_max_minutes = WAIT_TIME_MAX // 60
            await safe_send_message(client, event.chat_id, f"📊 حداکثر زمان فعلی انتظار: {current_max_minutes} دقیقه")
            print(f"DEBUG: Current max wait time: {current_max_minutes} minutes")
            

            
    elif event.raw_text.startswith("/userdel"):
        try:
            username_to_delete = event.raw_text.split(maxsplit=1)
            # Sicherstellen, dass `username_to_delete` ein String ist
            if isinstance(username_to_delete, list) and len(username_to_delete) > 1:
                username_to_delete = username_to_delete[1].lstrip("@")
            else:
                print("DEBUG: username_to_delete hat einen unerwarteten Typ oder ist leer.")
                return

            # Chat-ID mit await abrufen
            chat_id_to_delete = await get_chat_id_by_username(username_to_delete, client)
            if chat_id_to_delete is None:
                notify_message = await safe_send_message(client, event.chat_id, f"کاربر {username_to_delete} پیدا نشد.")
                print(f"DEBUG: No Chat ID found for username {username_to_delete}.")
                return

            success = delete_user_by_chat_id(chat_id_to_delete)
            if success:
                await client.delete_messages(event.chat_id, event.message.id)
                notify_message = await safe_send_message(client, event.chat_id, f"نام کاربری حذف شد: {username_to_delete}")
                print(f"DEBUG: Successfully deleted user with Chat ID: {chat_id_to_delete}.")
            else:
                notify_message = await safe_send_message(client, event.chat_id, "خطا در حذف کاربر.")
                print(f"DEBUG: Failed to delete user with Chat ID: {chat_id_to_delete}.")
        except Exception as e:
            print(f"ERROR: Exception during /userdel command - {e}")
            notify_message = await safe_send_message(client, event.chat_id, "خطا در حذف کاربر.")
        
        await asyncio.sleep(3)  # Wait for 3 seconds
        if 'notify_message' in locals():
            await notify_message.delete()  # Delete the message

async def handle_percentage_command(event):
    """Handle percentage command to change QA accuracy threshold"""
    global DEFAULT_QA_ACCURACY
    
    message = event.raw_text
    parts = message.split(" ", 1)  # Split at first space
    new_percentage = parts[1].strip() if len(parts) > 1 else None

    if new_percentage:
        try:
            percentage = int(new_percentage)
            if 0 <= percentage <= 100:
                DEFAULT_QA_ACCURACY = percentage
                await send_admin_response_with_cleanup(client, event.chat_id, f"✅ **QA Accuracy:** {percentage}%", True, event.message.id)
                print(f"✅ DEBUG: QA accuracy threshold changed to {percentage}%")
            else:
                await send_admin_response_with_cleanup(client, event.chat_id, "❌ **Error:** Percentage must be between 0 and 100", True, event.message.id)
        except ValueError:
            await send_admin_response_with_cleanup(client, event.chat_id, "❌ **Error:** Invalid percentage value", True, event.message.id)
    else:
        await send_admin_response_with_cleanup(client, event.chat_id, f"ℹ️ **Current QA Accuracy:** {DEFAULT_QA_ACCURACY}%", True, event.message.id)

async def handle_chat_specific_commands(event):
    """Handle chat-specific commands that only work in user chats or when replying to tickets"""
    chat_id = event.chat_id
    
    # Check if this is a reply to a ticket in the ticket channel
    replied_message = await event.get_reply_message()
    is_ticket_reply = False
    target_chat_id = chat_id
    
    if event.chat_id == ticket_channel_chat_ID and replied_message:
        # Check if replying to a ticket
        for tid, data in user_tickets.items():
            if data.get("message_id") == replied_message.id:
                target_chat_id = data["chat_id"]
                is_ticket_reply = True
                break
    
    # Only allow chat-specific commands in user chats or when replying to tickets
    if event.chat_id != ticket_channel_chat_ID and not is_ticket_reply:
        return
    
    if event.raw_text == "/always" or event.raw_text == "/alwayson":
        set_always_on(target_chat_id)
        await send_admin_response_with_cleanup(client, event.chat_id, f"✅ **Always:** ON for Chat ID {target_chat_id}", True, event.message.id)
        print(f"DEBUG: Always-On-Modus für Chat-ID {target_chat_id} aktiviert.")
    
    elif event.raw_text == "/alwaysoff":
        remove_always_on(target_chat_id)
        await send_admin_response_with_cleanup(client, event.chat_id, f"✅ **Always:** OFF for Chat ID {target_chat_id}", True, event.message.id)
        print(f"DEBUG: Always-On-Modus für Chat-ID {target_chat_id} deaktiviert.")
        
    elif event.raw_text == "/neveroff" or event.raw_text == "/zombieoff" or event.raw_text == "/unblock" or event.raw_text == "/free":
        delfrom_blacklist(target_chat_id)
        await send_admin_response_with_cleanup(client, event.chat_id, f"✅ **Never:** OFF for Chat ID {target_chat_id}", True, event.message.id)
        print(f"DEBUG: ROBOT für Chat-ID {target_chat_id} active again no blacklist!.")
        
    elif event.raw_text == "/never" or event.raw_text == "/neveron":
        add_to_blacklist(target_chat_id)
        await send_admin_response_with_cleanup(client, event.chat_id, f"✅ **Never:** ON for Chat ID {target_chat_id}", True, event.message.id)
        print(f"DEBUG: ROBOT für Chat-ID {target_chat_id} deaktiviert.")
        
    elif event.raw_text == "/zombie" or event.raw_text == "/block" or event.raw_text == "/b":
        await send_admin_response_with_cleanup(client, event.chat_id, f"✅ **Block:** User blocked (Chat ID: {target_chat_id})", True, event.message.id)
        await block_user(target_chat_id)

async def handle_history_command(event):
    """Handle /history command in ticket channel replies to show conversation history with user"""
    replied_message = await event.get_reply_message()
    
    # Skip if no replied message or if it's a separator
    if not replied_message or (replied_message.text and replied_message.text.strip()[0] in ['🟢', '🟣', '🔴']):
        print(f"DEBUG: /history command requires replying to a ticket message")
        await send_admin_response_with_cleanup(client, event.chat_id, "❌ **خطا:** برای استفاده از /history باید به پیام تیکت پاسخ دهید.", True, event.message.id)
        return
    
    # Find the ticket or screenshot that this reply is for
    ticket_id = None
    original_chat_id = None
    moftbar_username = None
    
    # Check for matching ticket
    for tid, data in user_tickets.items():
        if data.get("message_id") == replied_message.id:
            ticket_id = tid
            original_chat_id = data["chat_id"]
            moftbar_username = data.get("moftbar_username", "UnknownUser")
            break
    
    # Check for matching screenshot
    if not ticket_id:
        for sid, data in pending_screenshots.items():
            if data["message_id"] == replied_message.id:
                original_chat_id = data["chat_id"]
                moftbar_username = data.get("moftbar_username", "UnknownUser")
                break
    
    if not original_chat_id:
        print("DEBUG: No matching ticket or screenshot found for /history command")
        await send_admin_response_with_cleanup(client, event.chat_id, "❌ **خطا:** تیکت یا اسکرین‌شات مربوطه پیدا نشد.", True, event.message.id)
        return
    
    try:
        # Get conversation history from database
        conversation_history_list = load_conversation_from_db(original_chat_id)
        print(f"DEBUG: /history command - Found {len(conversation_history_list)} conversation entries for chat_id {original_chat_id}")
        
        if not conversation_history_list:
            print(f"DEBUG: /history command - No conversation history found for chat_id {original_chat_id}")
            await send_admin_response_with_cleanup(client, event.chat_id, "📝 **تاریخچه گفتگو:**\n\nهیچ تاریخچه‌ای برای این کاربر یافت نشد.", True, event.message.id)
            return
        
        # Format the history for display
        history_text = f"📝 **تاریخچه گفتگو با {moftbar_username}:**\n\n"
        
        # Show last 20 messages (10 conversations = 20 messages)
        recent_history = conversation_history_list[-20:]
        
        for i, message in enumerate(recent_history, 1):
            role = "👤 کاربر" if message.get("role") == "user" else "🤖 ربات"
            content = message.get("content", "").strip()
            timestamp = message.get("timestamp", "")
            
            # Format timestamp if available
            time_str = ""
            if timestamp:
                try:
                    dt = datetime.datetime.fromtimestamp(timestamp)
                    time_str = f" ({dt.strftime('%H:%M:%S')})"
                except:
                    pass
            
            history_text += f"{i}. {role}{time_str}:\n{content}\n\n"
        
        # Send the history
        await send_admin_response_with_cleanup(client, event.chat_id, history_text, True, event.message.id)
        print(f"DEBUG: Sent conversation history for user {moftbar_username} (Chat ID: {original_chat_id})")
        
    except Exception as e:
        print(f"ERROR: Failed to get conversation history: {e}")
        await send_admin_response_with_cleanup(client, event.chat_id, "❌ **خطا:** در دریافت تاریخچه گفتگو مشکلی پیش آمد.", True, event.message.id)


    # Commands are now handled by dedicated command handlers
    
    # Commands are now handled by dedicated command handlers

async def reset_tickets(chat_id):
    async with user_tickets_lock:
        # Search for the most recently created ticket for the given chat_id
        matching_tickets = [
            (ticket_id, ticket)
            for ticket_id, ticket in user_tickets.items()
            if ticket.get("chat_id") == chat_id
        ]

        if not matching_tickets:
            print(f"❌ Kein Ticket für chat_id {chat_id} gefunden.")
            return

        # Select the ticket with the highest created_at (i.e., the newest)
        ticket_id, ticket = max(
            matching_tickets, key=lambda item: item[1].get("created_at", 0)
        )

        # ⏹️ Timer abbrechen, falls vorhanden
        if ticket.get("timers"):
            try:
                ticket["timers"].cancel()
                print(f"✅ DEBUG: Timer für Ticket {ticket_id} (chat_id {chat_id}) abgebrochen.")
            except Exception as e:
                print(f"❌ Fehler beim Abbrechen des Timers für Ticket {ticket_id}: {e}")
            ticket["timers"] = None

        # ❌ Ticket als 'canceled' markieren
        ticket["ticket_status"] = "canceled"

        # 🔍 Debug-Ausgabe
        moftbar_username = ticket.get("moftbar_username", "Unbekannt")
        ticket_text = ticket.get("ticket_text", "N/A")
        ticket_message_id = ticket.get("ticket_message_id", "N/A")

        print(f"ℹ️ Ticket {ticket_id} wurde zurückgesetzt.")
        print(f"↪️ Nutzer: {moftbar_username}, Text: {ticket_text}, MsgID: {ticket_message_id}")















async def clear_timers(event):
    # Check if the sender is an admin (skip check for ticket channel since it's admin-only)
    sender = await event.get_sender()
    sender_username = getattr(sender, 'username', None)
    sender_id = getattr(sender, 'id', None)
    chat_id = event.chat_id
    
    # Allow all commands in ticket channel, check admin status for other chats
    if chat_id != ticket_channel_chat_ID and not is_admin_chat_id(chat_id) and not is_bot_sender(sender_id):
        print(f"⛔ DEBUG: User {sender_id} (Chat ID: {chat_id}) tried to use {event.raw_text} but is not an admin.")
        return

    # Reset auto_response_count to 0
    global auto_response_count
    auto_response_count = 0
    print(f"🔄 DEBUG: auto_response_count reset to 0 by clear_timers")

    # Send a notification message
    notify_message = await safe_send_message(client, event.chat_id, "Clearing all timers...")

    # Iterate through all user_tickets and clear the timers
    canceled_timers = 0
    tickets_to_remove = []
    async with user_tickets_lock:
        for ticket_id, data in user_tickets.items():
            # Cancel timer if it exists
            if "timers" in data and data["timers"] is not None:
                try:
                    data["timers"].cancel()
                    print(f"✅ DEBUG: Canceled timer for ticket {ticket_id}")
                except Exception as e:
                    print(f"❌ ERROR: Failed to cancel timer for ticket {ticket_id} - {e}")
                data["timers"] = None
            
            # Mark all pending and auto_responded tickets for removal
            if data.get("ticket_status") in ["pending", "auto_responded"]:
                canceled_timers += 1
                print(f"✅ DEBUG: Marked ticket {ticket_id} for removal")

                # Update the ticket in the channel to "ignored" (like "no" reply)
                if "ticket_message_id" in data and data["ticket_message_id"]:
                    moftbar_username = data.get("moftbar_username", "UnknownUser")
                    ticket_text = data.get("ticket_text", "N/A")
                    telegram_username = data.get("telegram_username", "")
                    updated_ticket_text = (
                        f"```{ticket_text}```\n"
                        f"☝️☝️☝️☝️☝️☝️\n\n"
                        f"👤 **Username:** : ```{moftbar_username}``` \n\n telegram: {telegram_username}\n\n"
                        f"🎫 **شناسه تیکت:**\n{ticket_id}\n\n"
                        f"❌ **وضعیت:** **Ignored!**"
                    )
                    try:
                        await client.edit_message(ticket_channel_chat_ID, data["ticket_message_id"], updated_ticket_text)
                        print(f"✅ DEBUG: Updated ticket {ticket_id} to 'ignored' in channel.")
                    except Exception as e:
                        print(f"❌ ERROR: Failed to update ticket {ticket_id} to 'ignored' - {e}")
                
                # Mark ticket for removal
                tickets_to_remove.append(ticket_id)
    
    # Remove all marked tickets from user_tickets
    for ticket_id in tickets_to_remove:
        if ticket_id in user_tickets:
            del user_tickets[ticket_id]
            print(f"✅ DEBUG: Removed ticket {ticket_id} from user_tickets")
    
    print(f"✅ DEBUG: Removed {len(tickets_to_remove)} tickets from user_tickets")
    
    
    
    
    
    # Clear all pending screenshots
    canceled_screenshots = 0
    screenshots_to_remove = []
    for screenshot_id, screenshot_data in pending_screenshots.items():
        try:
            # Update the screenshot in the channel to "ignored"
            moftbar_username = screenshot_data.get("moftbar_username", "UnknownUser")
            screenshot_message_id = screenshot_data.get("message_id")
            updated_screenshot_text = (
                f"👤 **Username:** : ```{moftbar_username}``` \n\n telegram: {telegram_username}\n\n"
                f"📷 **شناسه اسکرین‌شات:** \n"
                f"{screenshot_id}\n\n"
                f"❌ **وضعیت:** **Ignored!**📷"
            )
            try:
                await client.edit_message(ticket_channel_chat_ID, screenshot_message_id, updated_screenshot_text)
                print(f"✅ DEBUG: Updated screenshot {screenshot_id} to 'ignored' in channel.")
            except Exception as e:
                print(f"❌ ERROR: Failed to update screenshot {screenshot_id} to 'ignored' - {e}")

            screenshots_to_remove.append(screenshot_id)
            canceled_screenshots += 1
        except Exception as e:
            print(f"❌ ERROR: Failed to process screenshot {screenshot_id} - {e}")

    # Remove the processed screenshots from pending_screenshots
    for screenshot_id in screenshots_to_remove:
        del pending_screenshots[screenshot_id]
    print(f"✅ DEBUG: Cleared {canceled_screenshots} pending screenshots.")
    # Update the notification message with the result
    await notify_message.edit(f"✅ All pending items have been cleared. Tickets removed: {canceled_timers}, Screenshots cleared: {canceled_screenshots}. Auto response count reset to 0.")
    print(f"DEBUG: {event.raw_text} executed by admin {sender_username} (chat_id: {chat_id}, sender_id: {sender_id}, bot_id: {bot_id}), removed {canceled_timers} tickets, {canceled_screenshots} screenshots, auto_response_count reset to 0.")

    # Update the separator in the channel (like "no" reply)
    await manage_separator("canceled")
    if notify_message:
        await asyncio.sleep(3)  # Wait for 10 seconds
        await notify_message.delete()  # Delete the message




async def block_user(chat_id):
    """
    Blocks the given user by executing the same logic as the /block command.
    """
    remove_always_on(chat_id)

    add_to_blacklist(chat_id)

    
        # Add your existing /block logic here
    print(f"🚨 Blocking chat_id {chat_id} due to sensitive content.")

        # Example block logic (modify as needed)
       
    try:

        pin_message = await safe_send_message(client,chat_id, "❌بعلت تعدد و پی در پی بودن پیامها و نا مرتبط بودن موارد به پشتیبانی فنی تا اطلاع ثانوی از رسیدگی به پیام های شما معذوریم❌")
        await client.pin_message(chat_id, pin_message.id, notify=False) 
        

    except Exception as e:
        print(f"❌ ERROR: Could not archive chat {chat_id}. Reason: {e}")
 

async def enhance_admin_response(original_response, is_token=False, chat_id=None):
    """
    Enhances an admin's response by correcting spelling and punctuation while preserving the original word count
    and content. Ensures polite language, keeps IT terms in Latin, and avoids special characters within sentences.
    Optionally uses conversation history for context-aware corrections.

    Args:
        original_response (str): The admin's original response text.
        is_token (bool): Whether the response is for a token-based ticket.
        chat_id (int, optional): The chat ID for accessing conversation history.

    Returns:
        str: The enhanced response text with corrected spelling and punctuation.
    """
    import re
    import openai
    import asyncio

    # Define IT-related words to keep in Latin
    it_words = {
        "توکن": "token",
        "دیتابیس": "database",
        "سیستم": "system",
        "ای‌پی‌آی": "API",
        "سرور": "server",
        "شبکه": "network",
        "باگ": "bug",
        "آپدیت": "update",
        "ارور": "error",
        "کرش": "crash"
    }

    # Basic spelling corrections
    spelling_corrections = {
        "برسی": "بررسی",
        "مشگل": "مشکل",
        "تراخنص": "تراکنش",
        "پشتیباني": "پشتیبانی",
        "تستت": "تست",
        "خدمتت": "خدمت",
        "بررسیی": "بررسی"
    }

    # Clean the original response
    cleaned_response = original_response.strip()
    if not cleaned_response:
        cleaned_response = "پاسخ در حال بررسی است."
        print(f"DEBUG: Empty response detected, using fallback: {cleaned_response}")

    # Apply spelling corrections and preserve IT terms
    corrected_response = cleaned_response

    # Replace IT terms with placeholders to preserve them during correction
    placeholder_map = {}
    for idx, (persian_word, latin_word) in enumerate(it_words.items()):
        placeholder = f"__ITWORD{idx}__"
        placeholder_map[placeholder] = latin_word
        corrected_response = corrected_response.replace(persian_word, placeholder)

    # Apply basic spelling corrections
    for wrong, correct in spelling_corrections.items():
        corrected_response = corrected_response.replace(wrong, correct)

    # Prepare the context if chat_id is provided
    context = ""
    if chat_id and chat_id in conversation_history:
        recent_messages = [entry["content"] for entry in conversation_history[chat_id][-3:] if entry["role"] == "user"]
        context = "\n".join(recent_messages)
        print(f"DEBUG: Conversation history context: {context}")

    # Define the internal prompt for OpenAI (not included in final output)
    revise_prompt = (
        "فقط نقطه‌گذاری کن . "
        f"\n{corrected_response}"
    )

    # Use OpenAI API to correct spelling and punctuation
    try:
        openai_client = openai.OpenAI(api_key=openai.api_key)
        revise_response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "شما یک دستیار بسیار مؤدب هستید ."},
                {"role": "user", "content": revise_prompt}
            ],
            max_tokens=1000,
            temperature=0.5
        )
        revised_text = revise_response.choices[0].message.content.strip()
        print(f"DEBUG: Revised text: {revised_text}")
    except Exception as e:
        print(f"ERROR: Failed to revise text with OpenAI API - {e}")
        revised_text = corrected_response

    # Restore IT terms
    for placeholder, latin_word in placeholder_map.items():
        revised_text = revised_text.replace(placeholder, latin_word)

    # Ensure consistent punctuation (e.g., end sentences with periods where needed)
    final_lines = []
    for line in revised_text.split('\n'):
        line = line.strip()
        if line and not line.endswith(('.', '!', '?')) and not line.startswith(('-', '•')):
            line += '.'
        final_lines.append(line)

    final_text = '\n'.join(final_lines)

    return final_text







def are_strings_similar(str1, str2, threshold=96):
    """
    Checks if two strings are at least `threshold%` similar.
    Uses fuzzy matching (Levenshtein Distance).
    """
    similarity = fuzz.ratio(str1, str2)  # Get similarity percentage (0-100)
    #print(f"🔍 Similarity: {similarity}%")

    return similarity >= threshold






async def auto_ignore_screenshot(screenshot_id, chat_id, message_id, moftbar_username, original_message_id):
    """
    Automatically ignores a screenshot after 30 minutes of no admin response.
    Updates the ticket channel with 'ignored' status and removes it from pending_screenshots.

    Args:
        screenshot_id (str): The unique ID of the screenshot (e.g., #S1234).
        chat_id (int): The chat ID of the user who sent the screenshot.
        message_id (int): The message ID of the screenshot in the ticket channel.
        moftbar_username (str): The Moftbar username of the user.
        original_message_id (int): The original message ID of the screenshot from the user.
    """
    #WAIT_TIME_FOR_ADMIN = WAIT_TIME_FOR_ADMIN_LONG  # 30 minutes in seconds
    global WAIT_TIME_FOR_ADMIN, WAIT_TIME_MIN, WAIT_TIME_MAX
    REMINDER_TIME = WAIT_TIME_FOR_ADMIN -  (WAIT_TIME_FOR_ADMIN/20)   # 25 minutes in seconds
    DEBUG_INTERVAL = WAIT_TIME_FOR_ADMIN/10    # Debug print every 5 minutes
    print(f"⏳ DEBUG:REMINDER_TIME= {REMINDER_TIME}  --  WAIT_TIME_FOR_ADMIN = {WAIT_TIME_FOR_ADMIN} -- DEBUG_INTERVAL == {DEBUG_INTERVAL}")

    elapsed_time = 0
    #print(f"⏳ DEBUG: Starting 30-minute wait for Screenshot {screenshot_id}...")

    # Debug loop for the first 25 minutes
    while elapsed_time < REMINDER_TIME:
        await asyncio.sleep(DEBUG_INTERVAL)
        elapsed_time += DEBUG_INTERVAL
        print(f"⏳ DEBUG: {elapsed_time} seconds passed for Screenshot {screenshot_id}...")

    # Send a reminder to admins at 25 minutes
    if screenshot_id in pending_screenshots:
        #delete_this_later1 = await safe_send_message(
      #     client,
       #     ticket_channel_chat_ID,
      #      f"⏰ **یادآوری به ادمین‌ها**: اسکرین‌شات با شناسه {screenshot_id} هنوز پاسخ داده نشده است. "
      #      f"5 دقیقه تا نادیده گرفتن خودکار باقی مانده است. لطفاً بررسی کنید!"
      #  )
      #  delete_this_later2 = await safe_send_message(
      #      client,
      #      Support_channelchat_ID,
      #      f"⏰ **یادآوری به ادمین‌ها**: اسکرین‌شات با شناسه {screenshot_id} هنوز پاسخ داده نشده است. "
      #      f"5 دقیقه تا نادیده گرفتن خودکار باقی مانده است. لطفاً بررسی کنید!"
     #   )
        print(f"⏰ DEBUG: Sent 5-minute reminder for Screenshot {screenshot_id}")

    # Wait for the remaining 5 minutes
    while elapsed_time < WAIT_TIME_FOR_ADMIN:
        await asyncio.sleep(DEBUG_INTERVAL)
        elapsed_time += DEBUG_INTERVAL
        print(f"⏳ DEBUG: {elapsed_time} seconds passed for Screenshot {screenshot_id}...")

    # Check if the screenshot is still pending
    if screenshot_id in pending_screenshots:
        # Update the screenshot message in the ticket channel to mark it as ignored
        updated_screenshot_text = (
            f"📷 **اسکرین‌شات**\n"
            f"👤 **Username:** : ```{moftbar_username}``` \n\n telegram: {telegram_username}\n\n"
            f"🎫 **شناسه اسکرین‌شات:** \n"
            f"{screenshot_id}\n\n"
            f"🕒 **زمان:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"❌ **وضعیت:*   عدم پاسخ در 30 دقیقه، نادیده گرفته شد."
        )

        # Truncate caption if necessary
        if len(updated_screenshot_text) > 1024:
            updated_screenshot_text = updated_screenshot_text[:1000] + "…\n⚠️ [Caption truncated due to length limit]"
            print(f"⚠️ DEBUG: Truncated screenshot caption to 1024 characters for Screenshot {screenshot_id}")

        try:
            await client.edit_message(ticket_channel_chat_ID, message_id, updated_screenshot_text)
            print(f"✅ DEBUG: Screenshot {screenshot_id} marked as auto-ignored in ticket channel.")
        except Exception as e:
            print(f"❌ ERROR: Failed to edit Screenshot {screenshot_id} message - {e}")

       
        # Remove from pending_screenshots
        del pending_screenshots[screenshot_id]
        print(f"✅ DEBUG: Screenshot {screenshot_id} removed from pending_screenshots after auto-ignore.")

        # Delete reminder messages
        #await asyncio.sleep(3)
        #if delete_this_later1:
        #    await delete_this_later1.delete()
        #if delete_this_later2:
        #    await delete_this_later2.delete()

        # Update the separator to reflect the canceled status
        await manage_separator("canceled")
        # await update_pinned_pending_count()  # Uncomment if you have this function


async def append_to_conversation_history(chat_id, role, content):
    async with conversation_history_lock:
        # Add to in-memory conversation history
        if chat_id not in conversation_history:
            conversation_history[chat_id] = []
        conversation_history[chat_id].append({
            "role": role,
            "content": content,
            "timestamp": time.time()
        })
        
        # Also save to database for persistence
        try:
            save_conversation_to_db(chat_id, role, content, time.time())
        except Exception as e:
            print(f"❌ ERROR: Failed to save conversation to database: {e}")


import re

def has_link(text):
    """
    Checks if the given text contains a link (e.g., URLs or transaction links like trx://).
    
    Args:
        text (str): The input text to check for links.
    
    Returns:
        bool: True if a link is found, False otherwise.
    """
    link_pattern = r'(?:https?://|trx://|www\.)\S+|(?:\b[a-zA-Z0-9-]+\.[a-zA-Z]{2,}\b)'
    return bool(re.search(link_pattern, text, re.IGNORECASE))

def is_email(text):
    """
    Checks if the given text contains an email address.

    Args:
        text (str): The input text to check for an email.

    Returns:
        bool: True if an email is found, False otherwise.
    """
    email_pattern = r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b'
    return bool(re.search(email_pattern, text, re.IGNORECASE))


async def handle_qa_response(client, chat_id, message,original_message_id, accuracy=None):
    """
    Attempts to find and send a Q&A response with a specified accuracy.

    Args:
        client: The Telethon client instance.
        chat_id: The chat ID to send the response to.
        message: The user's message to search Q&A against.
        accuracy: The required matching accuracy percentage (default is DEFAULT_QA_ACCURACY).
    """
    # Use default accuracy if none provided
    if accuracy is None:
        accuracy = DEFAULT_QA_ACCURACY
    
    # Attempt to find a Q&A match
    answer, image_path, sticker_id = search_qa(message, accuracy)

    # If any content was found, send it
    if answer or image_path or sticker_id:
        await asyncio.sleep(5)

        if answer:
            await safe_send_message(client, chat_id, f"🤖: {answer}", reply_to=original_message_id)
            print(f"DEBUG: Q&A-Antwort mit {accuracy}% Genauigkeit gesendet - Answer: {reverse_text(answer)}")
        if image_path:
            #await client.send_file(chat_id, image_path)
            await safe_send_file(client, chat_id, image_path)

            print(f"DEBUG: Q&A-Bild gesendet - Path: {image_path}")
        if sticker_id:
            #await client.send_file(chat_id, sticker_id)
            await send_sticker(client, chat_id, sticker_id)

            print(f"DEBUG: Q&A-Sticker gesendet - ID: {sticker_id}")
        return True
    else:
        return False





async def send_sticker(client, chat_id, sticker_id):
    """
    Safely sends a Telegram sticker by its file ID.

    Args:
        client: Telethon client instance.
        chat_id (int): ID of the chat to send the sticker to.
        sticker_id (str): Telegram sticker file ID (e.g., 'CAAD...' or 'S...').

    Returns:
        bool: True if sent successfully, False if invalid or failed.
    """
    if not sticker_id or not isinstance(sticker_id, str):
        print(f"❌ ERROR: No sticker ID provided.")
        return False

    if not sticker_id.startswith(("CAAD", "CAAC", "S")):
        print(f"❌ ERROR: Invalid sticker ID format: {sticker_id}")
        return False

    try:
        await client.send_file(chat_id, sticker_id)
        print(f"✅ DEBUG: Sticker sent to {chat_id} - ID: {sticker_id}")
        return True
    except Exception as e:
        print(f"❌ ERROR: Failed to send sticker '{sticker_id}' - {e}")
        return False


#neue einheitliche er mainhandler 123456
@client.on(events.NewMessage)
async def message_handler(event):
    global mode, admin_usernames
    global BONUS_TEXT, Q_KEYWORDS,FINANCE_KEYWORDS,  TICKET_KEYWORDS,BONOUS_WORDS    

    if  mode == "off": #Robot is off nothong happens
        return
    
   
    if event.is_group: 
        return
   
    
    chat_id = event.chat_id
    if not chat_id or isinstance(chat_id, dict) and not chat_id: #chat id check
        print(f"❌ DEBUG: Invalid chat_id detected: {chat_id}")
        return
    blacklist = load_blacklist()
    is_never = str(chat_id) in blacklist


    

    if is_never: #prpcessing neverss more important like off
        return
    
    is_knownReal_kontakt = await is_known_contact(client, chat_id)
    if not is_knownReal_kontakt and not chat_id == ticket_channel_chat_ID:
        print(f"⚠️ Neuer Chat erkannt, ignoriere Nachricht von {chat_id}")
        return  # Ignoriere die Nachricht komplett

            
       
                        
        
         
         
    
       
    
    
    replied_message = await event.get_reply_message()
    sender = await event.get_sender()
    sender_username = getattr(sender, 'username', None)
    sender_id = getattr(sender, 'id', None)
    is_Admin = is_admin_chat_id(chat_id) or is_bot_sender(sender_id)
    is_user = not is_Admin

    global adminConfirm
    global WAIT_TIME_FOR_ADMIN, WAIT_TIME_FOR_ADMIN_LONG, WAIT_TIME_MIN, WAIT_TIME_MAX
    message = event.raw_text.strip()

    text_lower = message.lower()

    if event.is_channel :
            if  event.chat_id == ticket_channel_chat_ID:  # this is where tickets get a respunse we reply 
                if text_lower in [ "/clean","clean","clear", "/clear_all", "/clear"]:
                    await client.delete_messages(event.chat_id, event.message.id)
                    await clear_timers(event)
                    await manage_separator("canceled")
                    return

                # Handle /history command in ticket channel
                if text_lower == "/history":
                    print(f"DEBUG: /history command triggered in ticket channel by {sender_username} (chat_id: {chat_id})")
                    await handle_history_command(event)
                    return

                if replied_message: #this is where the magic happens a respounse in we arwe lerning from chats
                    adminConfirm = True # we know admin is awake 
                    WAIT_TIME_FOR_ADMIN = WAIT_TIME_MAX  # Admin is working, use max time
                    await handle_admin_reply(event)
                
            
            return
    
    
    is_always_onn = is_always_on(chat_id)
    moftbar_username = get_user_by_chat_id(chat_id) or f"User{chat_id}"
    # Initial username check and pinning
    print(f"\n\n\n --debug:  moftbar_username == {moftbar_username}")
   

    if moftbar_username is None or moftbar_username == "!None!" or not is_valid_username(moftbar_username):
        if is_user:

            await register_new_user(chat_id, event)  # Pass event to handle pinning/welcome inside
            return  # Exit after registration


    elif moftbar_username.startswith("User") :
        if should_ask_for_username_again(chat_id):
            if is_user:

                await register_new_user(chat_id, event)  # Pass event to handle pinning/welcome inside
                return  # Exit after registration
    else:
        await pin_user(client, event, moftbar_username)
        
        
    if moftbar_username in message.strip():
        return  



    if text_lower in START_KEYWORDS:  # For everyone can send start
        if mode == "on" or is_always_onn :
            await pin_user(client, event, moftbar_username)
            await show_main_menu(event.chat_id)
        return

    message_normalized = unicodedata.normalize('NFC', text_lower).replace("  ", " ").replace("!", "").replace("?", "")



    for keyword in ALWAYS_RESPOND_KEYWORDS.keys():
            keyword_normalized = unicodedata.normalize('NFC', keyword.lower()).replace("  ", " ").replace("!", "").replace("?", "")
            if are_strings_similar(message_normalized, keyword_normalized):
                response = ALWAYS_RESPOND_KEYWORDS[keyword]
                if  is_always_onn or mode == "on" and is_user:
                    await pin_user(client, event, moftbar_username)        
                    await safe_send_message(client, event.chat_id, response)
                    await safe_send_message(client, event.chat_id, f" برای منوی اصلی start/ را بزنید.")
                    
                    #await safe_send_message(client,event.chat_id,
                    #    "\nلطفاً مورد خود را با کلمات کلیدی و کوتاه ارسال کنید.\n")
                    #if mode == "on" or is_always_onn :
                     #   await show_main_menu(event.chat_id)
                    


                return

    # Check for bonus words and show bonus text immediately
    for bonus_word in BONOUS_WORDS:
        if bonus_word in message and is_user:
            if mode == "on" or is_always_onn:
                await pin_user(client, event, moftbar_username)
                BONUS_TEXT = load_bonus_text_from_file()
                await safe_send_message(client, event.chat_id, BONUS_TEXT)
                await safe_send_message(client, event.chat_id, f" برای منوی اصلی start/ را بزنید.")
                return

    for word in SENSITIVE_WORDS:
        if word in message and  is_user:
            user_id = event.sender_id  # Get the user ID of the sender
            print(f"🚨 WARNING: Sensitive word detected in message from {user_id}. Blocking user.")
            
            # Directly call the block function
            await block_user(user_id)
            return  # Exit to prevent further processing 12345
    
    

    # Store user message
    await append_to_conversation_history(chat_id, "user", message)
    
    # Check for OTP verification command
    if message.startswith("/verify_otp"):
        await handle_otp_verification(event, chat_id, message)
        return
  

    #normal message from users hanlder in lerning from replies
    if replied_message and is_Admin:
        
        if replied_message.photo:
            return  # we replied on a photo cannot leran from a foto
        history = await event.get_reply_message()
        if not history:
            return
        question = history.text.strip()


        if event.sticker:
            sticker_id = event.file.id
            add_qa_with_sticker(question, None, sticker_id)
            
        
        elif event.photo:

            file_path = f"images/{event.id}.jpg"
            await event.download_media(file_path)
            #question = fingilish_to_farsi(question)
            add_qa_with_image(question, image_path=file_path)
            print(f"DEBUG: Image learned - Question: {reverse_text(question)}, Image Path: {file_path}")
            
        else:  #reiner text lernen speichern
            answer = event.raw_text.strip()
            #enhance_question = await enhance_admin_response(question, is_token=False)
            #enhance_answer = await enhance_admin_response(answer, is_token=False)


            add_qa(question, answer)

        

    if is_Admin:
        print(f"Admin just typin... we ignoir....")

        return              
        
    #if not replied_message and is_user: #not replied simply user typing going to menu system
        # Only for normal users
    
    if is_user: # simply user typing or repliing going to menu system
          
        if  mode == "learn":
            if not is_always_onn:
                print("DEBUG: Bot is in learn  but always off , not this user message händler")
                return
          
        
        if event.sticker:
            return
        elif event.voice :
            await safe_send_message(client, event.chat_id, "🔇 **پیام صوتی پشتیبانی نمی‌شود!** ⚠️\n\nلطفاً از پیام متنی استفاده کنید.")
            print("DEBUG: Voice message received and rejected")
            return
        elif event.video :
            await safe_send_message(client, event.chat_id, "🎥 **پیام ویدیویی پشتیبانی نمی‌شود!** ⚠️\n\nلطفاً از پیام متنی استفاده کنید.")

            print("DEBUG: Video message received and rejected")
            return
        elif has_link(message):
            if not is_email(message):
                await safe_send_message(client, event.chat_id, "🔗 **ارسال لینک مجاز نیست!** ⚠️\n\nپیام‌های حاوی لینک نادیده گرفته می‌شوند.")
            

                print("DEBUG: Message has a link.")
                return   
        
    
        
       

        
           
   
        
          

        # Check if message exceeds 3 lines
        if (message.count("\n") >= 4 or len(message) > 255) :
            await safe_send_message(client, event.chat_id, "📝 **لطفاً درخواست خود را در یک پیام ارسال کنید!** ⚠️\n\nپیام‌های پراکنده فیلتر می‌شوند.")
            print("DEBUG: Message too long (lines or characters).")
            return   
          
        
        if event.photo:
            print(f"📷 DEBUG: User {chat_id} sent a photo, posting to ticket channel with caption.")
            # Retrieve Moftbar username

            # ✅ Create a unique screenshot ID (for internal tracking)
            #screenshot_id = f"{chat_id}-{int(time.time())}"
            screenshot_id = generate_screenshot_id()

            # ✅ Format the screenshot caption (info text)
            screenshot_caption = (
                f"📷 **اسکرین‌شات جدید**\n"
                f"👤 **Username:** : ```{moftbar_username}``` \n\n telegram: {telegram_username}\n\n"
                f"🎫 **شناسه اسکرین‌شات:** \n"
                f"{screenshot_id}\n\n"      

                f"🕒 **زمان:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"🔹 **ادمین می‌تواند reply کند یا نادیده بگیرد.**"
            )

            # ✅ Send the screenshot with the info as its caption to the ticket channel
            screenshot_message = await client.send_file(
                ticket_channel_chat_ID,
                event.photo,
                caption=screenshot_caption
            )

     

            # ✅ Store screenshot details in the new pending_screenshots dictionary
            pending_screenshots[screenshot_id] = {
                "chat_id": chat_id,
                "message_id": screenshot_message.id,
                "moftbar_username": moftbar_username,
                "original_message_id": event.message.id,
                "timers": None  # Initialize timer as None
            }

            # ✅ Start a timer for auto-ignoring the screenshot after timeout
            screenshot_data = {
                "screenshot_id": screenshot_id,
                "chat_id": chat_id,
                "message_id": screenshot_message.id,
                "moftbar_username": moftbar_username,
                "original_message_id": event.message.id
            }
            pending_screenshots[screenshot_id]["timers"] = asyncio.create_task(
                start_screenshot_timer(screenshot_data)
            )
            print(f"✅ DEBUG: Started timer for Screenshot {screenshot_id}")
            # ✅ Add a separator to the ticket channel
            await manage_separator("pending")
            await safe_send_message(client, chat_id, "📸 **تصویر شما ارسال شد!** ✅\n\nپس از بررسی، از همین طریق رسیدگی خواهد شد.", reply_to=event.message.id)
            #await update_pinned_pending_count()
            return  # Stop further processing after handling the screenshot
        
        
        
        
                

        user_input = message.strip()
        cleaned_input = user_input.replace(" ", "")
         
 

        if  cleaned_input in Q_KEYWORDS or cleaned_input in FINANCE_KEYWORDS or cleaned_input in TICKET_KEYWORDS or cleaned_input in BONOUS_WORDS:  #["1", "2", "3","۴","4", "۱", "۲", "۳"]:
            await user_states.set(chat_id, "main_menu")

            await handle_main_menu(event)
            return

        if cleaned_input.isdigit() and len(cleaned_input) < 16 :
                print("⚠️ just ignoiring Random numbers ...")
                return
        
        
       


       
        
            
        QA = await handle_qa_response(client, chat_id, message, event.message.id)
        if  QA:
            await user_states.set(chat_id, "technical_menu")

            
            return
        
     
            
        await safe_ticket(client, chat_id, message, event)
        await user_states.set(chat_id, "technical_menu")

        


       
    #await show_main_menu(chat_id)
    await handle_main_menu(event)

    


        
        
import re
import asyncio
import datetime
from telethon.errors import MessageNotModifiedError

    # Dictionary for ticket update texts
TICKET_UPDATE_TEMPLATES = {
    "ticket_text": (
        "```{ticket_text}```\n"
        "☝️☝️☝️☝️☝️☝️\n\n"
        "👤 **Username:** : ```{moftbar_username}``` \n\n telegram: {telegram_username}\n\n"
        "🎫 **شناسه تیکت:**\n{ticket_id}\n\n"
        "📝 **پاسخ:**\n"
        "```{response_text}```\n"
        "{status_text}\n"
    ),
    "ticket_token": (
        "```{token_number}```\n"
        "**☝️TOKEN NUMBER☝️**\n\n"
        "```{non_token_text}```\n"
        "👤 **Username:** : ```{moftbar_username}``` \n\n telegram: {telegram_username}\n\n"
        "🎫 **شناسه تیکت:**\n{ticket_id}\n\n"
        "📝 **پاسخ:**\n"
        "```{response_text}```\n"
        "{status_text}\n"
    ),
    "ticket_card": (
        "```{card_number}```\n"
        "**☝️CARD NUMBER☝️**\n\n"
        "👤 **Username:** : ```{moftbar_username}``` \n\n telegram: {telegram_username}\n\n"
        "🎫 **شناسه تیکت:**\n{ticket_id}\n\n"
        "📝 **پاسخ:**\n"
        "```{response_text}```\n"
        "{status_text}\n"
    ),
    "ticket_trx_wallet": (
        "```{trx_wallet}```\n"
        "**☝️TRX WALLET ADDRESS☝️**\n\n"
        "👤 **Username:** : ```{moftbar_username}``` \n\n telegram: {telegram_username}\n\n"
        "🎫 **شناسه تیکت:**\n{ticket_id}\n\n"
        "📝 **پاسخ:**\n"
        "```{response_text}```\n"
        "{status_text}\n"
    ),
    "screenshot": (
        "👤 **Username:** : ```{moftbar_username}``` \n\n telegram: {telegram_username}\n\n"
        "📷 **شناسه اسکرین‌شات:** \n"
        "{screenshot_id}\n\n"
        "📝 **پاسخ:**\n"
        "```{response_text}```\n"
        "{status_text}\n"
    ),
    "canceled": (
        "```{ticket_text}```\n"
        "☝️☝️☝️☝️☝️☝️\n\n"
        "👤 **Username:** : ```{moftbar_username}``` \n\n telegram: {telegram_username}\n\n"
        "🎫 **شناسه تیکت:**\n{ticket_id}\n\n"
        "❌ **وضعیت:** **نادیده گرفته شد.**"
    ),
    "canceled_screenshot": (
        "👤 **Username:** : ```{moftbar_username}``` \n\n telegram: {telegram_username}\n\n"
        "📷 **شناسه اسکرین‌شات:** \n"
        "{screenshot_id}\n\n"
        "❌ **وضعیت:** **نادیده گرفته شد.**📷"
    ),
    "canceled_token": (
        "```{token_number}```\n"
        "**☝️TOKEN NUMBER☝️**\n\n"
        "```{non_token_text}```\n"
        "👤 **Username:** : ```{moftbar_username}``` \n\n telegram: {telegram_username}\n\n"
        "🎫 **شناسه تیکت:**\n{ticket_id}\n\n"
        "❌ **وضعیت:** **نادیده گرفته شد.**"
    ),
    "blocked": (
        "```{ticket_text}```\n"
        "☝️☝️☝️☝️☝️☝️\n\n"
        "👤 **Username:** : ```{moftbar_username}``` \n\n telegram: {telegram_username}\n\n"
        "🎫 **شناسه تیکت:**\n{ticket_id}\n\n"
        "❌ **وضعیت:** **کاربر بلاک شد.**❌"
    ),
    "ticket_text_ai": (
        "🤖💙 **AI ANSWERED TICKET** 💙🤖\n"
        "```{ticket_text}```\n"
        "☝️☝️☝️☝️☝️☝️\n\n"
        "👤 **Username:** : ```{moftbar_username}``` \n\n telegram: {telegram_username}\n\n"
        "🎫 **شناسه تیکت:**\n{ticket_id}\n\n"
        "📝 **پاسخ AI:**\n"
        "```{response_text}```\n"
        "{status_text}\n"
    ),
    "ticket_token_ai": (
        "🤖💙 **AI ANSWERED TOKEN** 💙🤖\n"
        "```{token_number}```\n"
        "**☝️TOKEN NUMBER☝️**\n\n"
        "```{non_token_text}```\n"
        "👤 **Username:** : ```{moftbar_username}``` \n\n telegram: {telegram_username}\n\n"
        "🎫 **شناسه تیکت:**\n{ticket_id}\n\n"
        "📝 **پاسخ AI:**\n"
        "```{response_text}```\n"
        "{status_text}\n"
    ),
    "ticket_card_ai": (
        "🤖💙 **AI ANSWERED CARD** 💙🤖\n"
        "```{card_number}```\n"
        "**☝️CARD NUMBER☝️**\n\n"
        "👤 **Username:** : ```{moftbar_username}``` \n\n telegram: {telegram_username}\n\n"
        "🎫 **شناسه تیکت:**\n{ticket_id}\n\n"
        "📝 **پاسخ AI:**\n"
        "```{response_text}```\n"
        "{status_text}\n"
    ),
    "ticket_trx_wallet_ai": (
        "🤖💙 **AI ANSWERED WALLET** 💙🤖\n"
        "```{trx_wallet}```\n"
        "**☝️TRX WALLET ADDRESS☝️**\n\n"
        "👤 **Username:** : ```{moftbar_username}``` \n\n telegram: {telegram_username}\n\n"
        "🎫 **شناسه تیکت:**\n{ticket_id}\n\n"
        "📝 **پاسخ AI:**\n"
        "```{response_text}```\n"
        "{status_text}\n"
    )
}

    # Dictionary for special commands
SPECIAL_COMMANDS = {
    "cancel": ["نه", "no", "/no", "cancel", "/cancel", "/ignoir", "ignoir"],
    "block": ["/zombie", "/block", "block", "ban", "/ban"],
    "reset": ["reset_tickets", "/reset", "reset", "resetall", "/resetall"],
    "confirm": ["+", "باشه", "اوک", "اوکی", "حله", "ok", "/ok", "send", "/send", "yes", "/yes"]
}

    # Status texts for various scenarios
STATUS_TEXTS = {
    "resolved_text": "✅📩📝 **تیکت بطور دستی توسط ادمین پاسخ داده شد**",
    "resolved_ai": "📩✅🤖 **ادمین پاسخ خودکار را تایید کرد**",
    "resolved_sticker": "✅📩 **وضعیت:** رسیدگی شد.",
    "resolved_photo": "✅ **وضعیت:** با یک تصویر📷 رسیدگی شد.",
    "auto_responded": "🤖💙 **وضعیت:** پاسخ خودکار AI ارسال شد - منتظر تایید ادمین",
    "auto_responded_token": "🤖💙 **وضعیت:** پاسخ خودکار TOKEN ارسال شد - منتظر تایید ادمین",
    "auto_responded_card": "🤖💙 **وضعیت:** پاسخ خودکار CARD ارسال شد - منتظر تایید ادمین",
    "auto_responded_wallet": "🤖💙 **وضعیت:** پاسخ خودکار WALLET ارسال شد - منتظر تایید ادمین"
}

async def generate_update_text(template_key, **kwargs):
    """
    Generates the updated text for a ticket or screenshot based on a template.

    Args:
        template_key (str): The key for the template in TICKET_UPDATE_TEMPLATES.
        **kwargs: Dynamic values to fill in the template (e.g., ticket_id, moftbar_username).

    Returns:
        str: The formatted text, truncated if necessary for Telegram limits.
    """
    MAX_MESSAGE_LENGTH = 1024
    template = TICKET_UPDATE_TEMPLATES.get(template_key, "")
    
    # Set default values for required template variables
    default_values = {
        'telegram_username': '',
        'ticket_id': '',
        'moftbar_username': '',
        'ticket_text': '',
        'response_text': '',
        'status_text': '',
        'token_number': '',
        'non_token_text': '',
        'card_number': '',
        'screenshot_id': ''
    }
    
    # Clean kwargs to replace None values with empty strings and add defaults
    cleaned_kwargs = default_values.copy()
    for key, value in kwargs.items():
        if value is None:
            cleaned_kwargs[key] = ""
        else:
            cleaned_kwargs[key] = value
    
    text = template.format(**cleaned_kwargs)
    if len(text) > MAX_MESSAGE_LENGTH:
        text = text[:MAX_MESSAGE_LENGTH - 30] + "…\n⚠️ [Caption truncated due to length limit]"
        print(f"⚠️ DEBUG: Truncated message to {MAX_MESSAGE_LENGTH} characters for {template_key}")
    return text

async def cancel_timer(data, key, identifier):
    """
    Cancels the timer for a ticket or screenshot.

    Args:
        data (dict): The dictionary containing the timer (user_tickets or pending_screenshots).
        key (str): The ticket_id or screenshot_id.
        identifier (str): The identifier for logging (e.g., 'Ticket' or 'Screenshot').
    """
    if data.get(key, {}).get("timers"):
        data[key]["timers"].cancel()
        print(f"✅ DEBUG: Canceled {identifier} timer for {identifier} {key}")
        data[key]["timers"] = None













async def handle_admin_reply(event):
    """
    Handles admin replies in the ticket channel, ensuring token and non-token text are separated.
    """
    global auto_response_count, last_manual_response_time
    response_text = event.raw_text.strip().lower()
    replied_message = await event.get_reply_message()

    # Skip if no replied message or if it's a separator
    if not replied_message or (replied_message.text and replied_message.text.strip()[0] in ['🟢', '🟣', '🔴']):
        print(f"DEBUG: Skipping admin reply. {'No replied message' if not replied_message else 'Replied to separator'}")
        return

    # Check for links in the response text (exclude emails)
    if has_link(response_text) and not event.message.sticker and not event.message.photo and response_text not in SPECIAL_COMMANDS["confirm"]:
        notify_message = await safe_send_message(client, event.chat_id, "❌ **خطا:** پاسخ حاوی لینک است. لطفاً لینک‌ها را حذف کنید.")
        print(f"❌ DEBUG: Admin reply contains a link: {response_text}")
        await asyncio.sleep(3)
        await notify_message.delete()
        return

    # Initialize variables
    ticket_id = None
    screenshot_id = None
    original_chat_id = None
    moftbar_username = None
    user_message_id = None
    ticket_message_id = None
    ai_response = None
    is_token = False
    is_card = False
    original_message_id = None
    is_screenshot_reply = False
    is_ticket_reply = False
    non_token_text = None

    # Check for matching ticket
    for tid, data in user_tickets.items():
        if data.get("message_id") == replied_message.id:
            ticket_id = tid
            original_chat_id = data["chat_id"]
            moftbar_username = data.get("moftbar_username", "UnknownUser")
            user_message_id = data["user_message_id"]
            ticket_message_id = data["ticket_message_id"]
            ai_response = data.get("ai_response")
            is_token =  is_valid_token(user_tickets[ticket_id]["ticket_text"])
            is_card = bool(is_valid_cardnumber(data.get("ticket_text", ""))) if not is_token else False
            is_trx_wallet = bool(is_valid_trx_wallet(data.get("ticket_text", ""))) if not is_token and not is_card else False
            original_message_id = user_message_id
            is_ticket_reply = True
            # Dynamically extract non_token_text based on the current ticket_text
            non_token_text = extract_text_without_token(data["ticket_text"])
            break



    # Check for matching screenshot
    if not ticket_id:
        for sid, data in pending_screenshots.items():
            if data["message_id"] == replied_message.id:
                screenshot_id = sid
                original_chat_id = data["chat_id"]
                moftbar_username = data.get("moftbar_username", "UnknownUser")
                ticket_message_id = data["message_id"]
                original_message_id = data["original_message_id"]
                is_screenshot_reply = True
                break

    if not (is_ticket_reply or is_screenshot_reply):
        print("DEBUG: No matching ticket or screenshot found for reply.")
        return

    # Handle special commands
    if response_text in SPECIAL_COMMANDS["cancel"]:
        template_key = "canceled" if is_ticket_reply else "canceled_screenshot"
        status = "canceled"
        if is_token :
            template_key = "canceled_token"

        if is_ticket_reply:
            user_tickets[ticket_id]["ticket_status"] = status
            await cancel_timer(user_tickets, ticket_id, "Ticket")
        elif is_screenshot_reply:
            await cancel_timer(pending_screenshots, screenshot_id, "Screenshot")
            del pending_screenshots[screenshot_id]
        update_text = await generate_update_text(
            template_key,
            ticket_id=ticket_id,
            token_number = is_token,
            non_token_text = non_token_text,
            screenshot_id=screenshot_id,
            moftbar_username=moftbar_username,
            telegram_username=user_tickets[ticket_id].get("telegram_username", "") if is_ticket_reply else "",
            ticket_text=user_tickets[ticket_id]["ticket_text"] if is_ticket_reply else ""
        )
        await client.edit_message(ticket_channel_chat_ID, ticket_message_id, update_text)
        print(f"⛔ DEBUG: Admin canceled {'Ticket' if is_ticket_reply else 'Screenshot'} {ticket_id or screenshot_id}")
        await manage_separator("canceled")
        return

    if response_text in SPECIAL_COMMANDS["block"]:
        if is_ticket_reply:
            await block_user(original_chat_id)
            update_text = await generate_update_text(
                "blocked",
                ticket_id=ticket_id,
                moftbar_username=moftbar_username,
                telegram_username=user_tickets[ticket_id].get("telegram_username", ""),
                ticket_text=user_tickets[ticket_id]["ticket_text"]
            )
            await client.edit_message(ticket_channel_chat_ID, ticket_message_id, update_text)
            await reset_tickets(original_chat_id)
            notify_message = await safe_send_message(client, event.chat_id, f"❌**کاربر بلاک شد.**❌")
            await asyncio.sleep(3)
            await notify_message.delete()
            await manage_separator("resolved")
        return

    if response_text in SPECIAL_COMMANDS["reset"]:
        await reset_tickets(original_chat_id)
        notify_message = await safe_send_message(client, event.chat_id, f"❌**کلیه پیامهای باز `{moftbar_username}` نادیده گرفته شد**❌")
        await asyncio.sleep(3)
        await notify_message.delete()
        await manage_separator("resolved")
        return

    # Handle response types
    is_sticker = event.message.sticker is not None
    is_photo = event.message.photo is not None
    final_message = response_text
    is_ai_response = False

    if response_text in SPECIAL_COMMANDS["confirm"]:
        final_message = ai_response or "🤖 AI پاسخ خودکار موجود نیست."
        is_ai_response = True
        last_manual_response_time = time.time()
        auto_response_count = 0
        await event.message.delete()
        
        # Use AI response status for confirmed AI answers
        if is_ticket_reply:
            if is_token:
                template_key = "ticket_token"
                non_token_text = extract_text_without_token(user_tickets[ticket_id]["ticket_text"])
                update_text = await generate_update_text(
                    template_key,
                    ticket_id=ticket_id,
                    moftbar_username=moftbar_username,
                    telegram_username=user_tickets[ticket_id].get("telegram_username", ""),
                    token_number=is_token,
                    non_token_text=non_token_text,
                    response_text=final_message,
                    status_text=STATUS_TEXTS["resolved_ai"]
                )
            else:
                template_key = "ticket_text"
                update_text = await generate_update_text(
                    template_key,
                    ticket_id=ticket_id,
                    moftbar_username=moftbar_username,
                    telegram_username=user_tickets[ticket_id].get("telegram_username", ""),
                    ticket_text=user_tickets[ticket_id]["ticket_text"],
                    response_text=final_message,
                    status_text=STATUS_TEXTS["resolved_ai"]
                )
            
            # Send the AI response to user
            await safe_send_message(client, original_chat_id, final_message, reply_to=original_message_id)
            await append_to_conversation_history(original_chat_id, "bot", final_message)
            
            # Update ticket status and edit the ticket block
            user_tickets[ticket_id]["ticket_status"] = "resolved"
            user_tickets[ticket_id]["admin_response"] = final_message
            
            # Edit ticket message
            try:
                await client.edit_message(ticket_channel_chat_ID, ticket_message_id, update_text)
            except Exception as e:
                print(f"❌ ERROR: Failed to edit message - {e}")
            
            notify_message = await safe_send_message(client, event.chat_id, 
                f"✅ پاسخ AI برای تیکت `{ticket_id}` تایید و ارسال شد.")
            
            # Clean up notify message
            await asyncio.sleep(3)
            await notify_message.delete()
            
            await manage_separator("resolved")
            return

    # Handle sticker response
    if is_sticker:
        sticker_id = event.message.file.id
        await client.send_file(original_chat_id, sticker_id, reply_to=original_message_id)
        # Save conversation history for sticker response
        await append_to_conversation_history(original_chat_id, "bot", f"[Sticker sent: {sticker_id}]")
        if is_ticket_reply:
            add_qa_with_sticker(user_tickets[ticket_id]["ticket_text"], None, sticker_id)
            # Reduce AI response count if ticket was auto-responded
            if user_tickets[ticket_id].get("ticket_status") == "auto_responded" and auto_response_count > 0:
                auto_response_count -= 1
                print(f"🔄 DEBUG: auto_response_count reduziert auf {auto_response_count} für Ticket {ticket_id} nach Sticker-Antwort.")
                # Send notification about count reduction
                count_notify = await safe_send_message(client, event.chat_id, f"🤖 Auto response count reduced to {auto_response_count}")
                await asyncio.sleep(2)
                await count_notify.delete()
        template_key = "ticket_text" if is_ticket_reply else "screenshot"
        update_text = await generate_update_text(
            template_key,
            ticket_id=ticket_id,
            screenshot_id=screenshot_id,
            moftbar_username=moftbar_username,
            telegram_username=user_tickets[ticket_id].get("telegram_username", "") if is_ticket_reply else "",
            ticket_text=user_tickets[ticket_id]["ticket_text"] if is_ticket_reply else "",
            response_text="Sticker sent.",
            status_text=STATUS_TEXTS["resolved_sticker"]
        )
        notify_message = await safe_send_message(client, event.chat_id, "✅ Sticker sent to user!")

    # Handle photo response
    elif is_photo:
        file_path = await event.message.download_media()
        await client.send_file(original_chat_id, file_path, reply_to=original_message_id)
        # Save conversation history for photo response
        await append_to_conversation_history(original_chat_id, "bot", f"[Photo sent: {file_path}]")
        if is_ticket_reply:
            add_qa_with_image(user_tickets[ticket_id]["ticket_text"], image_path=file_path)
            # Reduce AI response count if ticket was auto-responded
            if user_tickets[ticket_id].get("ticket_status") == "auto_responded" and auto_response_count > 0:
                auto_response_count -= 1
                print(f"🔄 DEBUG: auto_response_count reduziert auf {auto_response_count} für Ticket {ticket_id} nach Bild-Antwort.")
                # Send notification about count reduction
                count_notify = await safe_send_message(client, event.chat_id, f"🤖 Auto response count reduced to {auto_response_count}")
                await asyncio.sleep(2)
                await count_notify.delete()
        template_key = "ticket_text" if is_ticket_reply else "screenshot"
        update_text = await generate_update_text(
            template_key,
            ticket_id=ticket_id,
            screenshot_id=screenshot_id,
            moftbar_username=moftbar_username,
            telegram_username=user_tickets[ticket_id].get("telegram_username", "") if is_ticket_reply else "",
            ticket_text=user_tickets[ticket_id]["ticket_text"] if is_ticket_reply else "",
            response_text="Photo sent.",
            status_text=STATUS_TEXTS["resolved_photo"]
        )
        notify_message = await safe_send_message(client, event.chat_id, "✅ Photo sent to user!")

    # Handle text response
    else:
        # Remove translation - just use original admin message
        final_message_to_use = final_message
        
        # Get admin username from sender
        admin_username = event.sender.username if event.sender and event.sender.username else "Admin"
        
        # Get current time for response_time
        import datetime
        response_time = datetime.datetime.now().strftime("%H:%M:%S")
        
        if is_ticket_reply:
            if is_token:
                template_key = "ticket_token"
                # Recalculate non_token_text dynamically
                non_token_text = extract_text_without_token(user_tickets[ticket_id]["ticket_text"])
                update_text = await generate_update_text(
                    template_key,
                    ticket_id=ticket_id,
                    moftbar_username=moftbar_username,
                    telegram_username=user_tickets[ticket_id].get("telegram_username", ""),
                    token_number=is_token,
                    non_token_text=non_token_text,
                    response_text=final_message_to_use,
                    status_text=STATUS_TEXTS["resolved_text"]
                )
            else:
                template_key = "ticket_text"
                update_text = await generate_update_text(
                    template_key,
                    ticket_id=ticket_id,
                    moftbar_username=moftbar_username,
                    telegram_username=user_tickets[ticket_id].get("telegram_username", ""),
                    ticket_text=user_tickets[ticket_id]["ticket_text"],
                    response_text=final_message_to_use,
                    status_text=STATUS_TEXTS["resolved_text"]
                )
        else:
            template_key = "screenshot"
            update_text = await generate_update_text(
                template_key,
                screenshot_id=screenshot_id,
                moftbar_username=moftbar_username,
                response_text=final_message_to_use,
                status_text=STATUS_TEXTS["resolved_text"]
            )
        # Send the original admin message (no translation)
        if is_ticket_reply and user_tickets[ticket_id].get("ticket_status") == "auto_responded" and auto_response_count > 0:
            try:
                await client.edit_message(original_chat_id, user_tickets[ticket_id]["ai_response_message_id"], final_message_to_use)
                print(f"🔄 DEBUG: auto_response_count reduziert auf {auto_response_count} für Ticket {ticket_id} nach manueller Admin-Antwort.")
                justEdited = True
                auto_response_count = auto_response_count - 1
                # Send notification about count reduction
                count_notify = await safe_send_message(client, event.chat_id, f"🤖 Auto response count reduced to {auto_response_count}")
                await asyncio.sleep(2)
                await count_notify.delete()

            except Exception as e:
                print(f"❌ ERROR: Failed to edit AI response - {e}")
                await safe_send_message(client, original_chat_id, final_message_to_use, reply_to=original_message_id)
        else:
            await safe_send_message(client, original_chat_id, final_message_to_use, reply_to=original_message_id)
        await append_to_conversation_history(original_chat_id, "bot", final_message_to_use)
        
        # Save admin answer to Q&A database and post to channel (like in version 51)
        if is_ticket_reply and not is_ai_response:
            # Save to database
            entry_id = add_qa(user_tickets[ticket_id]["ticket_text"], final_message_to_use)
            print(f"✅ DEBUG: Saved admin answer to Q&A database - Question: {user_tickets[ticket_id]['ticket_text'][:50]}...")
            
            # Post to Q&A channel
            if entry_id:
                try:
                    await post_to_channel(entry_id, user_tickets[ticket_id]["ticket_text"], final_message_to_use)
                    print(f"✅ DEBUG: Posted Q&A to channel - Entry ID: {entry_id}")
                except Exception as e:
                    print(f"❌ ERROR: Failed to post Q&A to channel - {e}")
        notify_message = await safe_send_message(client, event.chat_id, 
            f"✅ پاسخ به {'تیکت' if is_ticket_reply else 'اسکرین‌شات'} `{ticket_id or screenshot_id}` ارسال شد.")

        # When generating update_text for the ticket block, use translated_message as response_text
        # (This is below, so update_text will always use the translated answer)

    # Update ticket or screenshot status
    if is_ticket_reply:
        await cancel_timer(user_tickets, ticket_id, "Ticket")
        if user_tickets[ticket_id].get("pinned_warning_id"):
            try:
                await client.unpin_message(original_chat_id, user_tickets[ticket_id]["pinned_warning_id"])
                await client.delete_messages(original_chat_id, user_tickets[ticket_id]["pinned_warning_id"])
                del user_tickets[ticket_id]["pinned_warning_id"]
            except Exception as e:
                print(f"ERROR: Konnte gepinnte Warnnachricht nicht löschen - {e}")
        user_tickets[ticket_id]["ticket_status"] = "resolved"
        user_tickets[ticket_id]["admin_response"] = final_message
    elif is_screenshot_reply:
        await cancel_timer(pending_screenshots, screenshot_id, "Screenshot")
        del pending_screenshots[screenshot_id]

    # Edit ticket/screenshot message
    try:
        current_message = await client.get_messages(ticket_channel_chat_ID, ids=ticket_message_id)
        current_text = current_message.text if current_message else ""
        if update_text != current_text:
            await client.edit_message(ticket_channel_chat_ID, ticket_message_id, update_text)
        else:
            update_text += f"\n🕒 Edited: {datetime.datetime.now().strftime('%H:%M:%S')}"
            await client.edit_message(ticket_channel_chat_ID, ticket_message_id, update_text)
            print(f"⚠️ DEBUG: Forced edit with timestamp for {'Ticket' if is_ticket_reply else 'Screenshot'} {ticket_id or screenshot_id}")
    except MessageNotModifiedError:
        print(f"⚠️ DEBUG: Message not modified for {'Ticket' if is_ticket_reply else 'Screenshot'} {ticket_id or screenshot_id}")
    except Exception as e:
        print(f"❌ ERROR: Failed to edit message - {e}")

    # Clean up notify message
    if 'notify_message' in locals():
        await asyncio.sleep(3)
        await notify_message.delete()

    await manage_separator("resolved")










async def add_checkmark_to_message(channel_id, message_id):
    try:
        # Nachricht abrufen
        message = await client.get_messages(channel_id, ids=message_id)

        if message:
            new_text = f"✅ {message.text}"  # ✅ an den Anfang setzen
            
            # Nachricht bearbeiten
            await client.edit_message(channel_id, message.id, new_text)
            #print(f"✅ Nachricht {reverse_text(new_text)} im Kanal added chekmark✅!")

    except Exception as e:
        print(f"❌ Fehler beim Bearbeiten der Nachricht: {e}")


   


async def handle_main_menu(event):
    chat_id = event.chat_id
    if not chat_id or isinstance(chat_id, dict) and not chat_id: #chat id check
        print(f"❌ DEBUG: Invalid chat_id detected: {chat_id}")
        return

    global default_token_text

    global BONUS_TEXT, Q_KEYWORDS,FINANCE_KEYWORDS,  TICKET_KEYWORDS,BONOUS_WORDS


    message = event.raw_text.strip()



    # مرحله انتخاب از منوی اصلی
   
    user_choice = message
    print (f"\nanfang user_choice={user_choice},  user_states.get(chat_id) == {await user_states.get(chat_id)}")
    
    if await user_states.get(chat_id) == "main_menu":
        if user_choice in Q_KEYWORDS:#1
            await user_states.set(chat_id, "technical_menu")
            await safe_send_message(client,event.chat_id,
                "حالت متنی. لطفاً سوال خود را با کلمات کلیدی و کوتاه ارسال کنید.\n")
            return 1
            

        elif user_choice in FINANCE_KEYWORDS:#2
            file_path = f"images/Token.jpg"
            await safe_send_file(client, event.chat_id, file_path)
            await safe_send_message(client, chat_id,  
                "لطفاً توکن را در قالب صحیح 20 رقمی وارد کنید \n (XXXX XXXX XXXX XXXX XXXX)")
            await user_states.set(chat_id, "awaiting_token")
            return 2

            
        elif user_choice in TICKET_KEYWORDS:  #3
            await user_states.set(chat_id, "ticket_submission")
            await safe_send_message(client,event.chat_id,"لطفاً درخواست خود را کوتاه و با استفاده از کلمات کلیدی بیان کنید.")
            return 3

        elif user_choice in BONOUS_WORDS: #4
            await user_states.set(chat_id, "technical_menu")

            BONUS_TEXT = load_bonus_text_from_file()
            await safe_send_message(client,event.chat_id, BONUS_TEXT)
            return 4



async def handle_change_command(event, message, chat_id):
    """
    Handles the change command for modifying user data.
    Supports both /change and /ch commands.
    """
    # Extrahiere den neuen Moftbar-Username aus der Nachricht
    parts = message.split(" ", 1)
    if len(parts) < 2:
        notify_message = await safe_send_message(client, event.chat_id, "لطفاً نام جدید را وارد کنید.")
        print("DEBUG: No new username provided.")
        return

    new_moftbar_username = parts[1].strip()
    sender = await event.get_sender()
    telegram_username = sender.username if sender and sender.username else None

    if not telegram_username:
        await event.reply("خطا: نام کاربری تلگرام پیدا نشد.")
        print("DEBUG: Telegram username not found.")
        return
    
    add_user(new_moftbar_username, chat_id)

    #update_moftbar_username(telegram_username, new_moftbar_username)
    await pin_user(client, event, new_moftbar_username)
    #await event.reply(f"نام کاربری شما به {new_moftbar_username} تغییر یافت.")

    #print(f".نام کاربری برای پشتیبانی ذخیره شد: {new_moftbar_username}for cht id : {chat_id}")


def is_mostly_numbers(text):
    """
    Returns True if a message contains more digits than letters.
    Considers both Latin (a-z, A-Z) and Farsi (Persian) alphabets.
    """
    num_digits = len(re.findall(r'\d', text))  # Count digits (0-9)
    # Count Latin letters (a-z, A-Z) and Farsi letters (Unicode range U+0600 to U+06FF)
    num_letters = len(re.findall(r'[a-zA-Z\u0600-\u06FF]', text))

    return num_digits > num_letters  # True if more numbers than letters




@client.on(events.MessageEdited)
async def qa_update_handler(event):
    """
    Monitors the QA channel for edited messages and updates the database accordingly.
    This handler processes changes to QA entries without deleting the Telegram message.

    Args:
        event: The Telegram event object for the edited message.
    """
    #print("DEBUG: 🔍 Event-Handler triggered for message edit!")
    #print(f"DEBUG: 📌 Message edited in Chat ID: {event.chat_id}")
    #print(f"DEBUG: 📌 QA Channel ID: {qa_channel_id}")

    # Check if the edited message is from the QA channel using absolute IDs
    if abs(event.chat_id) != abs(qa_channel_id):
        #print("DEBUG: ❌ Message is not from the QA channel. Ignoring...")
        return  # Ignore messages from other chats

    #print("DEBUG: ✅ Message is from the QA channel! Processing edit...")

    # Extract the edited text from the message
    updated_text = event.raw_text.strip()
    print(f"DEBUG: 📝 Edited Text: {reverse_text(updated_text)}")

    # Use regex to extract ID, question, and answer from the edited message
    id_match = re.search(r"🔐 ID: (\d+)", updated_text)
    question_match = re.search(r"پرسش:(.*?)(?:پاسخ:|$)", updated_text, re.DOTALL)
    answer_match = re.search(r"پاسخ:(.*)", updated_text, re.DOTALL)

    # Check if all required parts (ID, question, answer) are present
    if id_match and question_match and answer_match:
        try:
            qa_id = id_match.group(1).strip()  # Extract the ID
            question = question_match.group(1).strip()  # Extract the question
            answer = answer_match.group(1).strip()  # Extract the answer

            print("DEBUG: \n✅ Edited entry detected!")
            print(f"DEBUG: 🔹 ID: {qa_id}")
            print(f"DEBUG: 🔹 Question: {reverse_text(question)}")
            print(f"DEBUG: 🔹 Answer: {reverse_text(answer)}")

            # Update the database with the edited values (no deletion of Telegram message)
            await replace_qa_entry(event)

            #print("DEBUG: \n✅ Database successfully updated with edited QA entry!")

        except Exception as e:
            print(f"DEBUG: \n❌ Error extracting QA data: {str(e)}")
    else:
        print("DEBUG: \n❌ No valid question/answer structure detected. Ignoring...")

    print("DEBUG: QA update handler completed for edited message.")






@client.on(events.MessageDeleted)
async def handle_message_deleted(event):
    """
    Reacts only to deleted messages in the QA channel, removing corresponding entries from the database.
    This ensures that if a QA entry is deleted in Telegram, it is also removed from the database.

    Args:
        event: The Telegram event object for the deleted message(s).
    """
    # Replace this with the actual ID of the Q&A channel
    QA_CHANNEL_ID = -1002492715418  # Ensure this matches qa_channel_id

    try:
        # Check if the deleted messages are from the Q&A channel
        if event.chat_id != QA_CHANNEL_ID:
            #print(f"DEBUG: Ignoring deleted messages from chat ID: {event.chat_id}")
            return

        # Process the deleted message IDs
        deleted_message_ids = event.deleted_ids
        print(f"DEBUG: Deleted message IDs: {deleted_message_ids}")

        # Connect to the database
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        for message_id in deleted_message_ids:
            try:
                # Delete the corresponding QA entry from the database
                cursor.execute("DELETE FROM qa WHERE message_id = ?", (message_id,))
                conn.commit()

                if cursor.rowcount > 0:
                    print(f"DEBUG: 🗑️ DELETED QA entry from database - Message ID: {message_id}")
                else:
                    print(f"DEBUG: ⚠️ WARNING: No QA entry found for Message ID: {message_id} in database.")

            except Exception as e:
                print(f"DEBUG: ❌ ERROR: Failed to delete QA entry for Message ID {message_id} - {e}")
                conn.rollback()  # Roll back in case of error

        conn.close()
        print("DEBUG: Database connection closed for deleted message operation.")

    except Exception as e:
        print(f"DEBUG: ❌ ERROR: An unexpected error occurred - {e}")

    print("DEBUG: Handle message deleted operation completed.")






















    """
    Reagiert nur auf gelöschte Nachrichten im Q&A-Kanal.
    """
              # Replace this with the actual ID of the Q&A channel

    try:
        # Check if the deleted messages are from the Q&A channel
        if event.chat_id != -1002492715418:
            #print(f"DEBUG: Ignoring deleted messages from is   418...chat ID: {event.chat_id}")
            return

        # Processing of deleted messages
        deleted_message_ids = event.deleted_ids
        print(f"DEBUG: Deleted message IDs: {deleted_message_ids}")

        for message_id in deleted_message_ids:
            await delete_qa_from_channel(message_id)

    except Exception as e:
        print(f"ERROR: An unexpected error occurred - {e}")





async def replace_qa_entry(event):
    """
    Updates an existing QA entry in the database based on the message_id with new values.
    If no entry is found, a new one is inserted. This function is called when a message in the QA channel is edited.

    Args:
        event: The Telegram event object containing the edited message.

    Returns:
        None
    """
    # Connect to the SQLite database
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Get the text of the edited message, if it exists
    message_text = event.message.message.strip() if event.message.message else None

    # Ignore messages with media (stickers, images, videos, etc.) as they are not QA entries
    if event.message.media:
        #print("DEBUG: Ignored media/sticker message in QA channel. No QA update performed.")
        conn.close()
        return

    # Extract question and answer from the message using the existing function
    question, answer = extract_qa_from_message(message_text)

    # Check if question and answer were successfully extracted
    if not question or not answer:
        print("DEBUG: ⚠️ WARNING: Could not extract Q&A from the message. Ignoring this update.")
        conn.close()
        return

    try:
        # Attempt to update the existing QA entry with the new values
        cursor.execute("""
            UPDATE qa 
            SET question = ?, answer = ?, message_id = ? 
            WHERE message_id = ?
        """, (question, answer, event.message.id, event.message.id))
        conn.commit()

        # Check if any rows were updated (rowcount > 0 indicates a successful update)
        if cursor.rowcount > 0:
            print(f"DEBUG: ✅ UPDATED QA - Question: {reverse_text(question)} | Answer: {reverse_text(answer)} | Message ID: {event.message.id}")
        else:
            print(f"DEBUG: ⚠️ WARNING: No QA entry found for message_id {event.message.id}, inserting new entry.")
            # If no entry was found, insert a new QA entry
            cursor.execute("INSERT INTO qa (message_id, question, answer) VALUES (?, ?, ?)", 
                           (event.message.id, question, answer))
            conn.commit()
            print(f"DEBUG: ✅ ADDED NEW QA - Question: {reverse_text(question)} | Answer: {reverse_text(answer)}")

    except Exception as e:
        print(f"DEBUG: ❌ ERROR: Failed to update QA entry - {e}")
        conn.rollback()  # Roll back the transaction in case of error
    finally:
        conn.close()
        #print("DEBUG: Database connection closed for QA update operation.")

    #print("DEBUG: QA update operation completed.")









def extract_qa_from_message(message_text):
    """
    Extracts the question (پرسش) and answer (پاسخ) from a Persian message format.
    """
    try:
        # Regular expression to extract the question and answer
        question_match = re.search(r"پرسش[:：](.*?)پاسخ[:：]", message_text, re.DOTALL)
        answer_match = re.search(r"پاسخ[:：](.*)", message_text, re.DOTALL)

        # Extract the matched text, stripping unnecessary spaces and newlines
        question = question_match.group(1).strip() if question_match else None
        answer = answer_match.group(1).strip() if answer_match else None

        return question, answer

    except Exception as e:
        print(f"❌ ERROR: Failed to extract QA from message - {e}")
        return None, None










async def save_qa_entry(event):
    """
    Saves a QA entry to the database, extracting the Persian question and answer.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    message_text = event.message.message.strip() if event.message.message else None

    # Ignore messages with media (stickers, images, videos, etc.)
    if event.message.media:
        #print("DEBUG: Ignored media/sticker message in QA channel.")
        return

    # Extract question and answer
    question, answer = extract_qa_from_message(message_text)

    if not question or not answer:
        print("⚠️ WARNING: Could not extract Q&A from the message. Ignoring this entry.")
        return

    try:
        cursor.execute("INSERT INTO qa (message_id, question, answer) VALUES (?, ?, ?)", 
                       (event.message.id, question, answer))
        conn.commit()
        #print(f"✅ STORED QA - Question: {reverse_text(question)} | Answer: {reverse_text(answer)}")

    except Exception as e:
        print(f"❌ ERROR: Failed to save QA entry - {e}")
    finally:
        conn.close()


def should_ask_for_username_again(chat_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT last_check FROM users WHERE chat_id = ?", (chat_id,))
    result = cursor.fetchone()
    conn.close()

    if result and result[0]:
        last_check_date = result[0]
        today = datetime.date.today().isoformat()
        return last_check_date != today
    return True


def update_last_check_date(chat_id):
    """Speichert das heutige Datum als letzte Überprüfung für den Nutzer."""
    today = datetime.date.today().isoformat()
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("UPDATE users SET last_check = ? WHERE chat_id = ?", (today, chat_id))
    
    conn.commit()
    conn.close()


async def periodic_cleanup():
    while True:

        await cleanup_resolved_tickets()
        #print("DEBUG: Periodic cleanup of resolved tickets completed.")
        await asyncio.sleep(86400)  # Run every hour


async def periodic_conversation_cleanup():
    while True:

        async with conversation_history_lock:
            current_time = time.time()
            for chat_id in list(conversation_history.keys()):
                # Filter out messages older than 24 hours
                filtered_messages = []
                for msg in conversation_history[chat_id]:
                    try:
                        # Handle different timestamp formats
                        if isinstance(msg["timestamp"], str):
                            # Parse the datetime string
                            import datetime
                            msg_timestamp = datetime.datetime.fromisoformat(msg["timestamp"].replace('Z', '+00:00'))
                            msg_timestamp_float = msg_timestamp.timestamp()
                        elif isinstance(msg["timestamp"], (int, float)):
                            # If it's already a numeric timestamp
                            msg_timestamp_float = float(msg["timestamp"])
                        else:
                            # If it's a datetime object
                            msg_timestamp_float = msg["timestamp"].timestamp()
                        
                        # Check if message is less than 24 hours old
                        if current_time - msg_timestamp_float < 24 * 60 * 60:
                            filtered_messages.append(msg)
                    except Exception as e:
                        print(f"⚠️ DEBUG: Error processing timestamp in conversation cleanup: {e}")
                        # Keep the message if we can't parse the timestamp
                        filtered_messages.append(msg)
                
                conversation_history[chat_id] = filtered_messages
                if not conversation_history[chat_id]:
                    del conversation_history[chat_id]
        await asyncio.sleep(86400)  # 24 hours


async def get_bot_info():
    """Get the bot's actual information after connection"""
    global bot_username, bot_id
    try:
        me = await client.get_me()
        bot_username = me.username
        bot_id = me.id
        print(f"✅ Bot info detected: Username: {bot_username}, ID: {bot_id}")
        return bot_username, bot_id
    except Exception as e:
        print(f"❌ Error getting bot info: {e}")
        return None, None

async def main():
    global bot_username
    await client.start()
    if not client.is_connected():
        print("❌ ERROR: TelegramClient failed to connect.")
        return
    init_db()  # Ensure DB is ready
    
    # Load admin chat IDs
    load_admin_chat_ids()
    
    # Get bot's actual information
    await get_bot_info()
    
    # Initialize conversation history from database
    await initialize_conversation_history()
    print("✅ DEBUG: Conversation history initialized from database")
    
    await manage_separator("resolved")
    global WAIT_TIME_FOR_ADMIN, WAIT_TIME_FOR_ADMIN_SHORT, WAIT_TIME_MIN, WAIT_TIME_MAX

    WAIT_TIME_FOR_ADMIN = WAIT_TIME_MAX

    print(f"🚀 DEBUG: Bot started in {mode} mode")

    # Start the periodic cleanup task
    asyncio.create_task(periodic_cleanup())
    asyncio.create_task(periodic_conversation_cleanup())  # New cleanup task

    
    # Existing initialization logic...

# Run synchronously before event loop
client.loop.run_until_complete(main())
client.run_until_disconnected()

async def send_otp_via_mavens_api(phone_number, telegram_username):
    """
    Sends OTP code via Mavens API for Telegram contact verification.
    CURRENTLY IN TEST MODE - NO ACTUAL SMS SENT
    
    Args:
        phone_number (str): The phone number to send OTP to
        telegram_username (str): The Telegram username to verify
    
    Returns:
        dict: API response with success status and OTP code
    """
    try:
        # TEST MODE - No actual API call
        print(f"🧪 TEST MODE: OTP function called for {phone_number} and @{telegram_username}")
        
        # Generate 6-digit OTP
        otp_code = str(random.randint(100000, 999999))
        
        # Simulate successful API response
        print(f"🧪 TEST MODE: Would send OTP {otp_code} to {phone_number} for @{telegram_username}")
        
        return {
            "success": True,
            "otp_code": otp_code,
            "api_response": {
                "test_mode": True,
                "message": "OTP function in test mode - no actual SMS sent",
                "phone": phone_number,
                "username": telegram_username
            }
        }
                    
    except Exception as e:
        return {
            "success": False,
            "error": f"Test mode error: {str(e)}"
        }

async def verify_telegram_username_consistency(telegram_username, moftbar_username):
    """
    Verifies if Telegram username matches Moftbar username.
    
    Args:
        telegram_username (str): The Telegram username
        moftbar_username (str): The Moftbar username
    
    Returns:
        dict: Verification result with consistency status
    """
    try:
        # Clean usernames (remove @ if present)
        telegram_clean = telegram_username.replace('@', '').lower()
        moftbar_clean = moftbar_username.lower()
        
        # Check for exact match
        if telegram_clean == moftbar_clean:
            return {
                "consistent": True,
                "match_type": "exact",
                "telegram_username": telegram_clean,
                "moftbar_username": moftbar_clean
            }
        
        # Check for similarity (using existing similarity function)
        similarity = are_strings_similar(telegram_clean, moftbar_clean, threshold=85)
        
        if similarity:
            return {
                "consistent": True,
                "match_type": "similar",
                "similarity_percentage": similarity,
                "telegram_username": telegram_clean,
                "moftbar_username": moftbar_clean
            }
        
        return {
            "consistent": False,
            "match_type": "none",
            "telegram_username": telegram_clean,
            "moftbar_username": moftbar_clean
        }
        
    except Exception as e:
        return {
            "consistent": False,
            "error": f"Verification failed: {str(e)}"
        }

async def handle_otp_verification(event, chat_id, message):
    """
    Handles OTP verification process for Telegram contact verification.
    
    Args:
        event: The Telethon event object
        chat_id: The chat ID
        message: The message containing OTP verification command
    """
    try:
        # Parse the command: /verify_otp <phone_number> <telegram_username>
        parts = message.split()
        if len(parts) != 3:
            await safe_send_message(client, chat_id, 
                "❌ فرمت نادرست. لطفاً به این شکل استفاده کنید:\n"
                "/verify_otp <شماره تلفن> <نام کاربری تلگرام>")
            return
        
        phone_number = parts[1]
        telegram_username = parts[2].replace('@', '')
        
        # Get Moftbar username for comparison
        moftbar_username = get_user_by_chat_id(chat_id) or f"User{chat_id}"
        
        # Verify username consistency
        consistency_result = await verify_telegram_username_consistency(telegram_username, moftbar_username)
        
        if not consistency_result["consistent"]:
            await safe_send_message(client, chat_id,
                f"❌ نام کاربری تلگرام و Moftbar مطابقت ندارند:\n"
                f"تلگرام: @{telegram_username}\n"
                f"Moftbar: {moftbar_username}")
            return
        
        # Send OTP via Mavens API
        otp_result = await send_otp_via_mavens_api(phone_number, telegram_username)
        
        if otp_result["success"]:
            await safe_send_message(client, chat_id,
                f"🧪 **TEST MODE** - کد تایید به شماره {phone_number} ارسال شد.\n"
                f"لطفاً کد {otp_result['otp_code']} را وارد کنید.\n"
                f"نام کاربری تایید شده: @{telegram_username}\n\n"
                f"⚠️ این یک تست است - هیچ پیامکی ارسال نشده است!")
            
            # Store OTP verification data for later use
            # You might want to store this in a database or temporary storage
            print(f"🧪 TEST MODE: OTP simulation successful for {telegram_username} to {phone_number}")
        else:
            await safe_send_message(client, chat_id,
                f"❌ خطا در ارسال کد تایید: {otp_result['error']}")
            
    except Exception as e:
        print(f"ERROR: Failed to handle OTP verification: {e}")
        await safe_send_message(client, chat_id, "❌ خطا در پردازش درخواست تایید")