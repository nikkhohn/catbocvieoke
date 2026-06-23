"""
Telegram Channel Video → Catbox.moe Auto-Uploader Bot
+ PagalBhabhi Website Integration
"""

import os, json, time, random
import asyncio, aiohttp, aiofiles, tempfile, logging
from pathlib import Path
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    CallbackQueryHandler, ContextTypes, filters,
)

import firebase_admin
from firebase_admin import credentials, db

load_dotenv()

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ─── Config ──────────────────────────────────────────────────────────────────
BOT_TOKEN       = os.getenv("BOT_TOKEN", "")
CHANNEL_ID      = os.getenv("CHANNEL_ID", "")
CATBOX_USERHASH = os.getenv("CATBOX_USERHASH", "")
RESULT_CHAT_ID  = os.getenv("RESULT_CHAT_ID", "")
ADMIN_ID        = int(os.getenv("OWNER_ID", os.getenv("ADMIN_ID", "0")))
FIREBASE_URL    = os.getenv("FIREBASE_URL", "")
FIREBASE_CRED_JSON = os.getenv("FIREBASE_CRED_JSON", "")
FIREBASE_CRED_PATH = os.getenv("FIREBASE_CRED_PATH", "serviceAccountKey.json")

CATBOX_API = "https://catbox.moe/user/api.php"

CAPTIONS = [
    "Ekdum Mast Content! Dekhte raho...",
    "Aaj ka sabse hot upload!",
    "Itna spicy content pehle kabhi nahi dekha!",
    "Dhamaka content! Miss mat karna...",
    "Premium quality, free mein enjoy karo!",
    "Ye dekh ke pagal ho jaoge!",
    "Sirf adults ke liye — 18+ content!",
    "Aaj raat ke liye perfect entertainment!",
    "Full masti, full entertainment!",
    "Popcorn lo aur enjoy karo!",
    "Bhabhi ka naya jawab nahi!",
    "Devar bhabhi ka dhamakedar scene!",
    "Aaj ki raat rangeen hogi!",
    "Ye video dekhe bina mat sona!",
    "Seedha dil pe lagega yeh content!",
]

# ─── Firebase ────────────────────────────────────────────────────────────────
cred = credentials.Certificate(
    json.loads(FIREBASE_CRED_JSON) if FIREBASE_CRED_JSON else FIREBASE_CRED_PATH
)
firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_URL})

def save_post(video_url: str, image_url: str, caption: str) -> str:
    post = db.reference("posts").push({
        "name": caption, "caption": caption,
        "image": image_url, "redirect": video_url,
        "premium": False, "isNew": True,
        "order": int(time.time() * 1000)
    })
    return post.key

def get_post_num(post_id: str) -> int:
    try:
        posts = db.reference("posts").get() or {}
        ids = sorted(posts, key=lambda k: posts[k].get("order", 0), reverse=True)
        return ids.index(post_id) + 1 if post_id in ids else 0
    except: return 0

def set_premium(post_id: str, val: bool):
    db.reference(f"posts/{post_id}").update({"premium": val})

# ─── Catbox Upload (original) ────────────────────────────────────────────────
async def upload_to_catbox(file_path: str, filename: str, content_type: str = "video/mp4") -> str | None:
    data = aiohttp.FormData()
    data.add_field("reqtype", "fileupload")
    if CATBOX_USERHASH:
        data.add_field("userhash", CATBOX_USERHASH)
    async with aiofiles.open(file_path, "rb") as f:
        content = await f.read()
    data.add_field("fileToUpload", content, filename=filename, content_type=content_type)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(CATBOX_API, data=data, timeout=aiohttp.ClientTimeout(total=300)) as resp:
                if resp.status == 200:
                    url = (await resp.text()).strip()
                    if url.startswith("https://"):
                        return url
                log.error("Catbox response: %s", resp.status)
    except Exception as e:
        log.error("Catbox upload error: %s", e)
    return None

# ─── Telegram Handler ────────────────────────────────────────────────────────
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.channel_post or update.message
    if not message: return

    chat_id = str(message.chat.id)
    channel_username = message.chat.username or ""
    if CHANNEL_ID not in (chat_id, f"@{channel_username}"): return

    video = message.video or message.document
    if not video: return
    if message.document and not (message.document.mime_type or "").startswith("video/"): return

    file_name    = getattr(video, "file_name", None) or f"video_{message.message_id}.mp4"
    file_size_mb = round((video.file_size or 0) / 1024 / 1024, 2)
    log.info("New video: %s (%.2f MB)", file_name, file_size_mb)

    target = RESULT_CHAT_ID or message.chat.id
    status_msg = await context.bot.send_message(
        chat_id=target,
        text=f"⏳ *Uploading to Catbox…*\n📁 `{file_name}` ({file_size_mb} MB)",
        parse_mode="Markdown",
        reply_to_message_id=message.message_id if not RESULT_CHAT_ID else None,
    )

    try:
        tg_file = await context.bot.get_file(video.file_id)
    except Exception as e:
        log.error("File download error: %s", e)
        await status_msg.edit_text("❌ File download failed.")
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = Path(tmpdir) / file_name
        await tg_file.download_to_drive(str(local_path))
        log.info("Downloaded: %s", local_path)

        # Thumbnail catbox pe upload karo
        image_url = ""
        if message.video and message.video.thumbnail:
            try:
                thumb_file = await context.bot.get_file(message.video.thumbnail.file_id)
                thumb_path = str(Path(tmpdir) / "thumb.jpg")
                await thumb_file.download_to_drive(thumb_path)
                image_url = await upload_to_catbox(thumb_path, "thumb.jpg", "image/jpeg") or ""
                log.info("Thumb: %s", image_url)
            except Exception as e:
                log.warning("Thumb failed: %s", e)

        catbox_url = await upload_to_catbox(str(local_path), file_name)

    if catbox_url:
        log.info("Uploaded: %s", catbox_url)

        # ── Website pe post save karo ────────────────────────────────────────
        caption  = random.choice(CAPTIONS)
        loop     = asyncio.get_event_loop()
        post_id  = await loop.run_in_executor(None, save_post, catbox_url, image_url, caption)
        post_num = await loop.run_in_executor(None, get_post_num, post_id)
        log.info("Post #%d saved: %s", post_num, post_id)

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("👑 Premium Karo", callback_data=f"premium:{post_id}"),
            InlineKeyboardButton("🆓 Free Rakho",   callback_data=f"free:{post_id}"),
        ]])

        await status_msg.edit_text(
            f"✅ *Post #{post_num} Complete!*\n\n"
            f"📁 `{file_name}` ({file_size_mb} MB)\n"
            f"📝 _{caption}_\n"
            f"🔗 {catbox_url}\n"
            f"🖼️ {image_url or 'N/A'}\n"
            f"👑 Status: 🆓 Free",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    else:
        await status_msg.edit_text("❌ *Catbox upload failed.*", parse_mode="Markdown")

# ─── Commands ────────────────────────────────────────────────────────────────
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    await update.message.reply_text(
        "🔥 *PagalBhabhi Bot*\n\n"
        "👑 `/premium POST_ID`\n"
        "🆓 `/free POST_ID`\n"
        "📊 `/status`",
        parse_mode="Markdown"
    )

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    posts = db.reference("posts").get() or {}
    prem  = sum(1 for p in posts.values() if p.get("premium"))
    await update.message.reply_text(
        f"📊 *Status*\n\n"
        f"📹 Posts: `{len(posts)}`\n"
        f"👑 Premium: `{prem}`\n"
        f"🆓 Free: `{len(posts)-prem}`",
        parse_mode="Markdown"
    )

async def premium_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args:
        return await update.message.reply_text("Usage: `/premium POST_ID`", parse_mode="Markdown")
    pid = context.args[0]
    try:
        set_premium(pid, True)
        await update.message.reply_text(f"👑 Post #{get_post_num(pid)} premium ho gaya!")
    except Exception as e: await update.message.reply_text(f"❌ {e}")

async def free_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args:
        return await update.message.reply_text("Usage: `/free POST_ID`", parse_mode="Markdown")
    pid = context.args[0]
    try:
        set_premium(pid, False)
        await update.message.reply_text(f"🆓 Post #{get_post_num(pid)} free ho gaya!")
    except Exception as e: await update.message.reply_text(f"❌ {e}")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID: return
    if ":" not in query.data: return
    action, pid = query.data.split(":", 1)
    try:
        if action == "premium":
            set_premium(pid, True)
            new_text = query.message.text.replace("👑 Status: 🆓 Free", "👑 Status: 👑 Premium")
            await query.edit_message_text(new_text, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Premium", callback_data="noop"),
                    InlineKeyboardButton("🆓 Free Karo", callback_data=f"free:{pid}"),
                ]]))
        elif action == "free":
            set_premium(pid, False)
            new_text = query.message.text.replace("👑 Status: 👑 Premium", "👑 Status: 🆓 Free")
            await query.edit_message_text(new_text, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("👑 Premium Karo", callback_data=f"premium:{pid}"),
                    InlineKeyboardButton("✅ Free", callback_data="noop"),
                ]]))
    except Exception as e: log.error("Callback error: %s", e)

# ─── Main ────────────────────────────────────────────────────────────────────
def main() -> None:
    if not BOT_TOKEN:  raise ValueError("BOT_TOKEN set karo!")
    if not CHANNEL_ID: raise ValueError("CHANNEL_ID set karo!")

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",   start_cmd))
    app.add_handler(CommandHandler("status",  status_cmd))
    app.add_handler(CommandHandler("premium", premium_cmd))
    app.add_handler(CommandHandler("free",    free_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))

    log.info("🚀 Bot started! Channel: %s", CHANNEL_ID)
    app.run_polling(allowed_updates=["channel_post", "message", "callback_query"])

if __name__ == "__main__":
    main()
