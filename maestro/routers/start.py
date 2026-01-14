from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

router = Router()


@router.message(CommandStart())
async def start(message: Message) -> None:
    await message.reply("Hello!")


@router.message(Command(commands=["chatid", "id"]))
async def get_chat_id(message: Message) -> None:
    await message.reply(
        f"Your chat ID is: `{message.chat.id}`\n\n"
        "Use this ID in your servers.yaml configuration.",
        parse_mode="Markdown"
    )
