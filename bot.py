"""
Telegram Channel Video → Catbox.moe Auto-Uploader Bot
------------------------------------------------------
Jab bhi channel mein koi video aaye, bot use catbox.moe par upload
karke wahi ya kisi aur chat mein link bhej deta hai.

Setup:
  1. pip install -r requirements.txt
  2. .env file mein BOT_TOKEN aur CHANNEL_ID bharo (neeche dekho)
  3. python bot.py
"""

import os
import asyncio
import aiohttp
import aiofiles
import tempfile
import logging
from pathlib import Path
from dotenv import load_dotenv

from telegram import Update, Bot
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters,
)

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ─── Config ─────────────────────────────────────────────────────────────────
load_dotenv()

BOT_TOKEN  = os.getenv("BOT_TOKEN", "")          # @BotFather se milta hai
CHANNEL_ID = os.getenv("CHANNEL_ID", "")         # e.g. -1001234567890 ya @mychannel

# Optional: catbox.moe account userhash (free account ke liye blank chhod do)
CATBOX_USERHASH = os.getenv("CATBOX_USERHASH", "")

# Agar aap chahte ho ki link kisi alag chat/channel mein jaye to yahan ID do,
# warna blank chhod do → link same channel mein reply hoga
RESULT_CHAT_ID = os.getenv("RESULT_CHAT_ID", "")

CATBOX_API = "https://catbox.moe/user/api.php"

# ─── Catbox Upload ───────────────────────────────────────────────────────────
async def upload_to_catbox(file_path: str, filename: str) -> str | None:
    """
    File ko catbox.moe par upload karta hai.
    Returns: URL string ya None (failure par)
    """
    data = aiohttp.FormData()
    data.add_field("reqtype", "fileupload")
    if CATBOX_USERHASH:
        data.add_field("userhash", CATBOX_USERHASH)

    async with aiofiles.open(file_path, "rb") as f:
        content = await f.read()

    data.add_field(
        "fileToUpload",
        content,
        filename=filename,
        content_type="video/mp4",
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(CATBOX_API, data=data, timeout=aiohttp.ClientTimeout(total=300)) as resp:
                if resp.status == 200:
                    url = (await resp.text()).strip()
                    if url.startswith("https://"):
                        return url
                log.error("Catbox response: %s — %s", resp.status, await resp.text())
    except Exception as e:
        log.error("Catbox upload error: %s", e)
    return None


# ─── Telegram Handler ────────────────────────────────────────────────────────
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.channel_post or update.message
    if not message:
        return

    # Sirf target channel ke messages process karo
    chat_id = str(message.chat.id)
    channel_username = message.chat.username or ""
    if CHANNEL_ID not in (chat_id, f"@{channel_username}"):
        return

    # Video ya document (video file) check karo
    video = message.video or message.document
    if not video:
        return

    # Document hai to MIME check karo
    if message.document and not (message.document.mime_type or "").startswith("video/"):
        return

    file_name = getattr(video, "file_name", None) or f"video_{message.message_id}.mp4"
    file_size_mb = round((video.file_size or 0) / 1024 / 1024, 2)

    log.info("New video detected: %s (%.2f MB)", file_name, file_size_mb)

    # Status message bhejo
    target = RESULT_CHAT_ID or message.chat.id
    status_msg = await context.bot.send_message(
        chat_id=target,
        text=f"⏳ *Uploading to Catbox…*\n📁 `{file_name}` ({file_size_mb} MB)",
        parse_mode="Markdown",
        reply_to_message_id=message.message_id if not RESULT_CHAT_ID else None,
    )

    # File download karo
    try:
        tg_file = await context.bot.get_file(video.file_id)
    except Exception as e:
        log.error("File download error: %s", e)
        await status_msg.edit_text("❌ File download failed. Telegram size limit (20 MB) exceeded?")
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = Path(tmpdir) / file_name
        await tg_file.download_to_drive(str(local_path))
        log.info("Downloaded to %s", local_path)

        # Catbox par upload karo
        catbox_url = await upload_to_catbox(str(local_path), file_name)

    if catbox_url:
        log.info("Uploaded: %s", catbox_url)
        await status_msg.edit_text(
            f"✅ *Upload Successful!*\n\n"
            f"📁 File: `{file_name}`\n"
            f"📦 Size: {file_size_mb} MB\n"
            f"🔗 Link: {catbox_url}",
            parse_mode="Markdown",
        )
    else:
        await status_msg.edit_text(
            "❌ *Catbox upload failed.*\nThodi der baad try karo.",
            parse_mode="Markdown",
        )


# ─── Main ────────────────────────────────────────────────────────────────────
def main() -> None:
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN .env file mein set karo!")
    if not CHANNEL_ID:
        raise ValueError("CHANNEL_ID .env file mein set karo!")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Channel posts aur normal messages dono handle karo
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))

    log.info("Bot chal raha hai... Channel: %s", CHANNEL_ID)
    app.run_polling(allowed_updates=["channel_post", "message"])


if __name__ == "__main__":
    main()
