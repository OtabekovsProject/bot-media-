from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ChatMemberStatus
from database import get_channels

class ForceSubMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        # Determine user and type
        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id
        else:
            return await handler(event, data)

        bot = data['bot']
        channels = await get_channels()
        
        not_subscribed = []

        for ch_id, ch_url in channels:
            try:
                member = await bot.get_chat_member(chat_id=ch_id, user_id=user_id)
                if member.status not in ['member', 'administrator', 'creator']:
                    not_subscribed.append(ch_url)
            except Exception:
                continue

        if not_subscribed:
            # Prepare buttons
            buttons = [
                [InlineKeyboardButton(text="📢 Kanalga obuna bo‘lish", url=url)] 
                for url in not_subscribed
            ]
            buttons.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_sub")])
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            
            # Handle Response based on event type
            if isinstance(event, CallbackQuery):
                # If they clicked check_sub but still not subbed
                if event.data == "check_sub":
                    await event.answer("❌ Hali obuna bo'lmadingiz! Iltimos, kanallarga a'zo bo'ling.", show_alert=True)
                else:
                    await event.answer("🚫 Foydalanish uchun obuna bo'ling!", show_alert=True)
                return # Stop processing
            
            elif isinstance(event, Message):
                await event.answer(
                    "🚫 <b>Kechirasiz! Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:</b>",
                    reply_markup=keyboard
                )
                return # Stop processing

        return await handler(event, data)