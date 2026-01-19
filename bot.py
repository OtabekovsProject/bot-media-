import os
import asyncio
import logging
import re
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

# Import local modules
from config import BOT_TOKEN, ADMIN_IDS, DOWNLOAD_PATH
from database import init_db, add_user, get_stats, add_channel, remove_channel, get_channels, get_all_users, check_admin, set_admin
from services import download_media, recognize_music, search_and_download_song
from middlewares import ForceSubMiddleware

# --- PRIVACY-ENHANCED LOGGING ---
class PrivacyFilter(logging.Filter):
    """Filters out sensitive data from logs"""
    PATTERNS = [
        (r'id=\d+', 'id=***'),
        (r'token=[\w-]+', 'token=***'),
        (r'@\w+', '@***'),
        (r'\d{9,}', '***ID***'),
    ]
    
    def filter(self, record):
        msg = str(record.msg)
        for pattern, replacement in self.PATTERNS:
            msg = re.sub(pattern, replacement, msg)
        record.msg = msg
        return True

# Apply privacy filter
logging.basicConfig(level=logging.WARNING)  # Reduce log verbosity
for handler in logging.root.handlers:
    handler.addFilter(PrivacyFilter())

# Bot Setup
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

# Webhook config
WEBHOOK_PATH = "/webhook"
WEBHOOK_PORT = int(os.getenv("PORT", 8080))

# Register Middleware for ALL event types
dp.message.middleware(ForceSubMiddleware())
dp.callback_query.middleware(ForceSubMiddleware())

# --- STATES ---
class AppStates(StatesGroup):
    waiting_for_channel_link = State()
    waiting_for_broadcast = State()
    waiting_for_admin_id = State()
    waiting_for_admin_remove = State()

# --- HELPER: CHECK ADMIN ---
async def is_admin(user_id):
    if user_id in ADMIN_IDS:
        return True
    return await check_admin(user_id)

# --- USER HANDLERS ---
@dp.message(Command("start"))
async def start_handler(message: types.Message):
    await add_user(message.from_user.id, message.from_user.full_name, message.from_user.username)
    await message.answer(
      f"👋 Salom, <b>{message.from_user.full_name}</b>!\n\n"
"🎧 Men <b>TopTuneX bot</b> — universal yuklovchi va aqlli musiqa topuvchi botman.\n\n"
"📥 <b>Imkoniyatlarim:</b>\n"
"• Instagram, TikTok, YouTube, Facebook,  videolar va musiqasini yuklab beraman\n"
"• Video yoki audio orqali musiqani aniqlayman (Shazam texnologiyasi)\n"
"• Topilgan musiqani nomi bilan birga MP3 formatda taqdim etaman\n"
"• Yuqori sifat va tezkor ishlashni kafolatlayman\n\n"
"⚡ <b>Qanday foydalaniladi?</b>\n"
"• Havola yuboring — men yuklab beraman\n"
"• Audio yoki video tashlang — musiqani topib beraman\n\n"
"🚀 <b>Boshlash uchun hoziroq havola yoki fayl yuboring!</b>"
)

@dp.callback_query(F.data == "check_sub")
async def check_sub_handler(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("✅ <b>Rahmat! Obuna tasdiqlandi.</b>\nEndi bemalol foydalanishingiz mumkin.")

# --- ADMIN HANDLER: ADD CHANNEL (High Priority) ---
@dp.message(AppStates.waiting_for_channel_link)
async def admin_add_channel_handler(message: types.Message, state: FSMContext):
    try:
        text = message.text.strip()
        chat = None
        
        # 1. Resolve ID if text is username/link
        if text.startswith("https://t.me/") or text.startswith("@"):
            username = text.replace("https://t.me/", "").replace("@", "")
            try:
                chat = await bot.get_chat(f"@{username}")
            except Exception as e:
                await message.reply(f"❌ Kanal topilmadi: {e}")
                return
        elif text.lstrip("-").isdigit(): # If ID provided directly
             try:
                chat = await bot.get_chat(text)
             except:
                await message.reply("❌ Kanal topilmadi (ID xato).")
                return
        else:
             await message.reply("❌ Noto'g'ri format. Username (@kanal) yoki Link yuboring.")
             return

        ch_id = str(chat.id)
        ch_url = chat.invite_link or f"https://t.me/{chat.username}" if chat.username else text
        
        # 2. Verify Bot Admin
        try:
            chat_member = await bot.get_chat_member(chat_id=ch_id, user_id=(await bot.get_me()).id)
            if chat_member.status not in ['administrator', 'creator']:
                await message.reply("🚫 <b>Xatolik!</b> Bot bu kanalda admin emas.")
                return
        except Exception as e:
            await message.reply(f"🚫 <b>Tekshirishda xatolik:</b> {e}")
            return
            
        await add_channel(ch_id, ch_url)
        await message.reply(f"✅ <b>Kanal qo'shildi!</b>\nID: {ch_id}\nLink: {ch_url}")
        await state.clear()
        
    except Exception:
        await message.reply("😔 Kechirasiz, kanal qo'shishda muammo yuz berdi. Qaytadan urinib ko'ring.")

# --- ADMIN HANDLER: GRANT ADMIN ---
@dp.message(AppStates.waiting_for_admin_id)
async def admin_grant_handler(message: types.Message, state: FSMContext):
    try:
        target_id = int(message.text.strip())
        await set_admin(target_id, True)
        await message.reply(f"✅ Foydalanuvchi ({target_id}) ADMIN qilindi!")
        await state.clear()
    except:
        await message.reply("❌ ID raqam bo'lishi kerak.")

# --- ADMIN HANDLER: BROADCAST ---
@dp.message(AppStates.waiting_for_broadcast)
async def admin_broadcast_handler(message: types.Message, state: FSMContext):
    users = await get_all_users()
    count = 0
    status_msg = await message.reply("⏳ <b>Xabar yuborilmoqda...</b>")
    
    for user in users:
        user_id = user[0]
        try:
            # Send header first
            await bot.send_message(chat_id=user_id, text="📢 <b>ADMIN XABARI</b>")
            # Then copy the message
            await message.copy_to(chat_id=user_id)
            count += 1
            await asyncio.sleep(0.05)
        except:
            pass
            
    await status_msg.edit_text(f"✅ <b>Xabar tarqatildi!</b>\n\nJami: {len(users)}\nYuborildi: {count}")
    await state.clear()

# --- DOWNLOAD HANDLER (Links) ---
@dp.message(F.text.regexp(r'(https?://(?:www\.|(?!www))[a-zA-Z0-9][a-zA-Z0-9-]+[a-zA-Z0-9]\.[^\s]{2,}|www\.[a-zA-Z0-9][a-zA-Z0-9-]+[a-zA-Z0-9]\.[^\s]{2,}|https?://(?:www\.|(?!www))[a-zA-Z0-9]+\.[^\s]{2,})'))
async def link_handler(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📹 Video", callback_data="dl_video"),
            InlineKeyboardButton(text="🎵 Musiqa (To'liq)", callback_data="dl_music")
        ]
    ])
    await message.reply("� <b>Formatni tanlang:</b>", reply_markup=keyboard)

@dp.callback_query(F.data == "dl_video")
async def video_callback_handler(callback: CallbackQuery):
    if not callback.message.reply_to_message or not callback.message.reply_to_message.text:
        await callback.answer("❌ Havola topilmadi.", show_alert=True)
        return
        
    url = callback.message.reply_to_message.text.strip()
    await callback.answer(cache_time=1)
    status_msg = await callback.message.reply("⏳ <b>Video yuklanmoqda...</b>")
    
    file_path, title, media_type = await download_media(url)
    
    if file_path and os.path.exists(file_path):
        try:
            await status_msg.edit_text("📤 <b>Video yuklanmoqda biroz kuting😊...</b>")
            file_to_send = FSInputFile(file_path)
            caption_text = f"📹 <b>{title}</b>\n🤖 @{ (await bot.get_me()).username}"
            
            if media_type == 'image':
                await callback.message.answer_photo(photo=file_to_send, caption=caption_text)
            elif media_type == 'audio':
                await callback.message.answer_audio(audio=file_to_send, caption=caption_text)
            else:
                await callback.message.answer_video(video=file_to_send, caption=caption_text)
            await status_msg.delete()
        except:
            await status_msg.edit_text("😔 Afsuski, bu videoni yuborib bo'lmadi. Boshqa havola bilan urining.")
        finally:
            if os.path.exists(file_path): 
                try: os.remove(file_path)
                except: pass
    else:
        await status_msg.edit_text("😔 Bu havola hozircha mavjud emas yoki himoyalangan. Boshqa havola bilan urining.")

@dp.callback_query(F.data == "dl_music")
async def music_callback_handler(callback: CallbackQuery):
    if not callback.message.reply_to_message or not callback.message.reply_to_message.text:
        await callback.answer("❌ Havola topilmadi.", show_alert=True)
        return

    url = callback.message.reply_to_message.text.strip()
    await callback.answer(cache_time=1)
    status_msg = await callback.message.reply("🎵 <b>Musiqa aniqlanmoqda ..</b>")
    
    file_path, title, _ = await download_media(url)
    if not file_path or not os.path.exists(file_path):
        await status_msg.edit_text("😔 Bu video hozircha mavjud emas. Boshqa havola bilan urining.")
        return

    result = await recognize_music(file_path)
    if os.path.exists(file_path):
        try: os.remove(file_path)
        except: pass

    if result:
        await status_msg.edit_text(f"✅ <b>Topildi!</b>\n🎤 {result['subtitle']} - {result['title']}\n🔍 <b>To'liq MP3 yuklanmoqda...</b>")
        search_query = f"{result['subtitle']} - {result['title']}"
        mp3_path, info = await search_and_download_song(search_query)
        
        if mp3_path and os.path.exists(mp3_path):
            try:
                audio_file = FSInputFile(mp3_path)
                await callback.message.answer_audio(
                    audio=audio_file,
                    title=result['title'],
                    performer=result['subtitle'],
                    caption="🤖 @yuklovchishazam_bot - To'liq musiqa"
                )
                await status_msg.delete()
            except:
                await status_msg.edit_text("😔 Musiqa yuborib bo'lmadi. Keyinroq urinib ko'ring.")
            finally:
                if os.path.exists(mp3_path):
                    try: os.remove(mp3_path)
                    except: pass
        else:
            await status_msg.edit_text(f"⚠️ Musiqa topildi, lekin MP3 yuklab bo'lmadi.\n🔗 <a href='{result['url']}'>Shazam</a>")
    else:
        await status_msg.edit_text("🎵 Musiqa aniqlanmadi. Aniqroq qism bilan urining.")

# --- MUSIC RECOGNITION HANDLER (Files) ---
@dp.message(F.video | F.audio | F.voice | F.video_note)
async def file_recognition_handler(message: types.Message):
    try:
        status_msg = await message.reply("🎵 <b>Musiqa aniqlanmoqda...</b>")
        
        # Get file ID based on message type
        if message.video:
            file_id = message.video.file_id
        elif message.audio:
            file_id = message.audio.file_id
        elif message.voice:
            file_id = message.voice.file_id
        elif message.video_note:
            file_id = message.video_note.file_id
        else:
            await status_msg.edit_text("😔 Bu turdagi fayl qo'llab-quvvatlanmaydi.")
            return
        
        file = await bot.get_file(file_id)
        file_path = f"{DOWNLOAD_PATH}/{file_id}.tmp"
        await bot.download_file(file.file_path, file_path)
        
        result = await recognize_music(file_path)
        
        # Cleanup
        if os.path.exists(file_path):
            try: os.remove(file_path)
            except: pass
            
        if result:
            await status_msg.edit_text(f"✅ <b>Topildi!</b>\n🎤 {result['subtitle']} - {result['title']}\n🔍 <b>To'liq MP3 yuklanmoqda...</b>")
            search_query = f"{result['subtitle']} {result['title']}"
            mp3_path, info = await search_and_download_song(search_query)
            
            if mp3_path and os.path.exists(mp3_path):
                try:
                    audio_file = FSInputFile(mp3_path)
                    await message.answer_audio(
                        audio=audio_file, 
                        title=result['title'], 
                        performer=result['subtitle'], 
                        caption="🤖 @yuklovchishazam_bot"
                    )
                    await status_msg.delete()
                except:
                    await status_msg.edit_text("😔 Musiqa yuborib bo'lmadi.")
                finally:
                    if os.path.exists(mp3_path):
                        try: os.remove(mp3_path)
                        except: pass
            else:
                await status_msg.edit_text(f"✅ <b>{result['title']}</b> topildi!\n📀 {result['subtitle']}\n🔗 <a href='{result['url']}'>Shazam'da ochish</a>")
        else:
            await status_msg.edit_text("🎵 Musiqa aniqlanmadi. Boshqa qism bilan urining.")
    except Exception:
        await message.reply("😔 Kechirasiz, hozir xizmat mavjud emas.")

# --- TEXT MUSIC SEARCH ---
@dp.message(F.text & ~F.text.startswith("/"))
async def text_music_handler(message: types.Message):
    query = message.text.strip()
    status_msg = await message.reply(f"🔎 <b>'{query}'</b> qidirilmoqda...")
    mp3_path, info = await search_and_download_song(query)
    
    if mp3_path and os.path.exists(mp3_path):
        try:
            await status_msg.edit_text("📤 <b>Yuklanmoqda...</b>")
            audio_file = FSInputFile(mp3_path)
            title = info.get('title', query)
            performer = info.get('uploader', 'Music Bot')
            await message.answer_audio(audio=audio_file, title=title, performer=performer, caption=f"🎧 <b>{title}</b>\n🤖 @{(await bot.get_me()).username}")
            await status_msg.delete()
        except:
             await status_msg.edit_text("❌ Yuborishda xatolik.")
        finally:
            if os.path.exists(mp3_path):
                try: os.remove(mp3_path)
                except: pass
    else:
        await status_msg.edit_text("❌ Topilmadi.")

# --- ADMIN PANEL ---
# --- ADMIN PANEL LOGIC ---
async def show_admin_ui(target, is_callback=False):
    stats = await get_stats()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Kanallar", callback_data="admin_channels"),
         InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="admin_add_channel")],
        [InlineKeyboardButton(text="🗣 Reklama (Broadcast)", callback_data="admin_broadcast"),
         InlineKeyboardButton(text="👥 Users", callback_data="admin_users")],
        [InlineKeyboardButton(text="👮‍♂️ Admin qilish", callback_data="admin_grant"),
         InlineKeyboardButton(text="❌ Admin o'chirish", callback_data="admin_remove")],
        [InlineKeyboardButton(text="🗑 Kanal o'chirish", callback_data="admin_del_channel_menu")]
    ])
    
    text = (
        f"⚙️ <b>Admin Panel</b>\n\n"
        f"👥 <b>Jami foydalanuvchilar:</b> {stats}\n\n"
        "Boshqaruv uchun tugmani bosing:"
    )

    if is_callback:
        await target.edit_text(text, reply_markup=keyboard)
    else:
        await target.answer(text, reply_markup=keyboard)

@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if not await is_admin(message.from_user.id): return
    await show_admin_ui(message, is_callback=False)

@dp.callback_query(F.data == "admin_channels")
async def admin_channels_list(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id): return
    channels = await get_channels()
    if not channels:
        await callback.answer("📭 Kanallar yo'q", show_alert=True)
        return
    
    text = "📋 <b>Ulangan kanallar:</b>\n\n"
    for cid, url in channels:
        text += f"ID: <code>{cid}</code>\nLink: {url}\n\n"
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Ortga", callback_data="admin_back")]]))

@dp.callback_query(F.data == "admin_add_channel")
async def admin_add_channel_start(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    await state.set_state(AppStates.waiting_for_channel_link)
    await callback.message.edit_text(
        "📝 <b>Kanal linkini yuboring.</b>\n\nMisol: <code>@kanalim</code> yoki <code>https://t.me/kanalim</code>\n\n⚠️ Bot kanalga ADMIN bo'lishi shart!", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="admin_back")]])
    )

@dp.callback_query(F.data == "admin_users")
async def admin_users_list(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id): return
    users = await get_all_users()
    
    if len(users) > 50:
         with open("users.txt", "w", encoding="utf-8") as f:
             for u in users:
                 f.write(f"ID: {u[0]} | Name: {u[1]} | User: @{u[2] or 'None'} | Admin: {u[3]}\n")
         await callback.message.answer_document(FSInputFile("users.txt"), caption="📋 Barcha foydalanuvchilar ro'yxati")
         os.remove("users.txt")
         return

    text = "👥 <b>Foydalanuvchilar:</b>\n\n"
    for u in users:
        admin_tag = "👮‍♂️ " if u[3] else ""
        text += f"{admin_tag}ID: <code>{u[0]}</code> | <a href='tg://user?id={u[0]}'>{u[1]}</a> (@{u[2]})\n"
    
    if len(text) > 4000:
        text = text[:4000] + "..."
        
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Ortga", callback_data="admin_back")]]))

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    await state.set_state(AppStates.waiting_for_broadcast)
    await callback.message.edit_text(
        "🗣 <b>Xabarni yuboring.</b>\n\nMatn, Rasm, Video yoki Forward qilishingiz mumkin.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="admin_back")]])
    )

@dp.callback_query(F.data == "admin_grant")
async def admin_grant_start(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    await state.set_state(AppStates.waiting_for_admin_id)
    await callback.message.edit_text(
        "👮‍♂️ <b>Admin qilish uchun ID yuboring.</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="admin_back")]])
    )

@dp.callback_query(F.data == "admin_back")
async def admin_back_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if not await is_admin(callback.from_user.id): return
    await show_admin_ui(callback.message, is_callback=True)

@dp.callback_query(F.data == "admin_remove")
async def admin_remove_start(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    
    # Get list of dynamic admins from database
    users = await get_all_users()
    admins = [u for u in users if u[3]]  # u[3] is is_admin flag
    
    if not admins:
        await callback.answer("📭 O'chirish uchun admin yo'q", show_alert=True)
        return
    
    # Create inline buttons for each admin
    buttons = []
    for u in admins:
        user_id, full_name, username, _ = u
        name = f"{full_name} (@{username})" if username else full_name
        buttons.append([InlineKeyboardButton(text=f"❌ {name[:25]}", callback_data=f"rm_admin_{user_id}")])
    
    buttons.append([InlineKeyboardButton(text="🔙 Ortga", callback_data="admin_back")])
    
    await callback.message.edit_text(
        "❌ <b>Adminlikdan o'chirish uchun tanlang:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

@dp.callback_query(F.data.startswith("rm_admin_"))
async def admin_remove_handler(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id): return
    
    target_id = int(callback.data.replace("rm_admin_", ""))
    
    try:
        await set_admin(target_id, False)
        await callback.answer("✅ Adminlik olib tashlandi!", show_alert=True)
        await show_admin_ui(callback.message, is_callback=True)
    except Exception:
        await callback.answer("😔 O'chirishda xatolik.", show_alert=True)

@dp.callback_query(F.data == "admin_del_channel_menu")
async def admin_del_channel_menu(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id): return
    
    channels = await get_channels()
    if not channels:
        await callback.answer("📭 O'chirish uchun kanal yo'q", show_alert=True)
        return
    
    # Create inline buttons for each channel
    buttons = []
    for ch_id, ch_url in channels:
        # Get channel name from URL
        name = ch_url.replace("https://t.me/", "@").replace("https://", "")[:20]
        buttons.append([InlineKeyboardButton(text=f"🗑 {name}", callback_data=f"del_ch_{ch_id}")])
    
    buttons.append([InlineKeyboardButton(text="🔙 Ortga", callback_data="admin_back")])
    
    await callback.message.edit_text(
        "🗑 <b>O'chirish uchun kanalni tanlang:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

@dp.callback_query(F.data.startswith("del_ch_"))
async def admin_delete_channel_handler(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id): return
    
    ch_id = callback.data.replace("del_ch_", "")
    
    try:
        await remove_channel(ch_id)
        await callback.answer("✅ Kanal o'chirildi!", show_alert=True)
        await show_admin_ui(callback.message, is_callback=True)
    except Exception:
        await callback.answer("😔 O'chirishda xatolik.", show_alert=True)

# --- GLOBAL ERROR HANDLER ---
@dp.error()
async def error_handler(event, exception):
    logging.error(f"Update {event} raised exception: {exception}")
    return True  # Prevent crash

# --- START BOT ---
async def on_startup(app):
    """Called when webhook server starts"""
    await init_db()
    if not os.path.exists(DOWNLOAD_PATH): os.makedirs(DOWNLOAD_PATH)
    
    # Set webhook URL from environment
    webhook_url = os.getenv("WEBHOOK_URL", "")
    if webhook_url:
        await bot.set_webhook(f"{webhook_url}{WEBHOOK_PATH}")
        print(f"🤖 Bot ishga tushdi (webhook mode): {webhook_url}")
    else:
        print("⚠️ WEBHOOK_URL topilmadi!")

async def on_shutdown(app):
    """Called when webhook server stops"""
    await bot.delete_webhook()

async def root_handler(request):
    """Check bot status and webhook info"""
    try:
        webhook_info = await bot.get_webhook_info()
        info_text = (
            f"🤖 <b>TopTuneX Bot is running!</b><br>"
            f"Unique ID: {bot.id}<br>"
            f"Webhook URL: {webhook_info.url}<br>"
            f"Pension updates: {webhook_info.pending_update_count}<br>"
            f"Last error: {webhook_info.last_error_message}"
        )
        return web.Response(text=info_text, content_type='text/html')
    except Exception as e:
        return web.Response(text=f"Bot running, but failed to get webhook info: {e}", status=500)

def run_webhook():
    """Run bot in webhook mode (for Render/Production)"""
    app = web.Application()
    
    # Setup webhook handler
    webhook_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    
    # Add root route for checking status
    app.router.add_get('/', root_handler)
    
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    
    # Run web server
    web.run_app(app, host="0.0.0.0", port=WEBHOOK_PORT)

async def run_polling():
    """Run bot in polling mode (for local development)"""
    if not os.path.exists(DOWNLOAD_PATH): os.makedirs(DOWNLOAD_PATH)
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    print("🤖 Bot ishga tushdi (polling mode)")
    await dp.start_polling(bot)

if __name__ == "__main__":
    # Check if running on Render (has PORT env variable)
    if os.getenv("RENDER") or os.getenv("WEBHOOK_URL"):
        run_webhook()
    else:
        # Local development - use polling
        while True:
            try:
                asyncio.run(run_polling())
            except KeyboardInterrupt:
                break
            except Exception as e:
                logging.error(f"Error: {e}")
                continue