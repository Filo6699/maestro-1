from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

router = Router()


@router.message(CommandStart())
async def start(message: Message) -> None:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Deploy", callback_data="deploy:menu")],
            [InlineKeyboardButton(text="Get Chat ID", callback_data="chatid:show")],
        ]
    )
    await message.reply("Choose an action:", reply_markup=keyboard)


@router.callback_query(F.data == "chatid:show")
async def get_chat_id_callback(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        f"Current chat ID is: `{callback.message.chat.id}`\n\n"
        "Use this ID in your servers.yaml configuration.",
        parse_mode="Markdown",
    )
    await callback.answer()


@router.message(Command(commands=["chatid", "id"]))
async def get_chat_id(message: Message) -> None:
    await message.reply(
        f"Your chat ID is: `{message.chat.id}`\n\n"
        "Use this ID in your servers.yaml configuration.",
        parse_mode="Markdown",
    )
