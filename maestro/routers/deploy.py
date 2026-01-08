from datetime import datetime
from io import BytesIO

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, BufferedInputFile
from aiogram.utils.media_group import MediaGroupBuilder

from maestro.config import Server, Action, Config
from maestro.ssh_client import connect_to_server
from maestro.text_to_png import text_to_png

router = Router()


def is_allowed(chat_id: int, config: Config, server: Server = None) -> bool:
    """Check if a chat_id has access to a server or globally."""
    if chat_id in config.allowed_chat_ids:
        return True
    if server and chat_id in server.allowed_chat_ids:
        return True
    return False


def run_action(server: Server, action: Action) -> (BytesIO, BytesIO):
    name = f"deploy_result_{action.name}_{datetime.now()}"
    client = connect_to_server(server)
    stdin, stdout, stderr = client.exec_command(action.command)
    text = f"{stdout.read().decode()}\n{stderr.read().decode()}".strip()
    client.close()

    png_file = text_to_png(text)
    png_file.name = f"{name}.png"

    txt_file = BytesIO(text.encode())
    txt_file.name = "output.txt"
    txt_file.seek(0)

    return txt_file, png_file


@router.message(
    Command(commands=["d", "deploy"]),
    F.chat.id.as_("chat_id"),
)
async def handle_command_deploy(
    message: Message, command: CommandObject, config: Config, chat_id: int
) -> None:
    args = (command.args or "").split()
    if len(args) == 0:
        # here we will show the list of servers
        servers = "\n".join(
            name for name, server in config.servers.items()
            if is_allowed(chat_id, config, server)
        )
        await message.reply(
            f"Usage: /deploy <server> <action>\nAvailable servers:\n{servers}"
        )
        return
    if len(args) == 1:
        # here we will show the list of actions
        server = config.servers.get(args[0])
        if not server:
            await message.reply("Server not found")
            return
        # Check if user has access to this server
        if not is_allowed(chat_id, config, server):
            await message.reply("You are not allowed to access this server")
            return
        actions = "\n".join(
            f" - {action.name}: {action.description}"
            if action.description
            else f" - {action.name}"
            for action in server.actions.values()
        )
        actions += "\n - all: Run all available actions"
        await message.reply(
            f"Usage: /deploy {args[0]} <action>\nAvailable actions:\n{actions}"
        )
        return
    if len(args) != 2:
        await message.reply("Usage: /deploy <server> <action>")
        return

    server, action = args
    server = config.servers.get(server)

    if not server:
        await message.reply("Server not found")
        return
    if not is_allowed(chat_id, config, server):
        await message.reply("You are not allowed to deploy to this server")
        return

    if action == "all":
        actions = server.actions.values()
    else:
        action_obj = server.actions.get(action)
        if not action_obj:
            await message.reply("Action not found")
            return
        actions = [action_obj]

    for action in actions:
        await deploy_use_case(message, server, action)


async def deploy_use_case(message: Message, server: Server, action: Action):
    info = await message.reply(f"Running action {action.name} on {server.name}...")
    txt_file, png_file = run_action(server, action)

    media_group = MediaGroupBuilder(
        caption=f"Result of action {action.name} on {server.name}"
    )
    media_group.add_document(BufferedInputFile(png_file.read(), png_file.name))
    media_group.add_document(BufferedInputFile(txt_file.read(), txt_file.name))

    await info.reply_media_group(media_group.build())

    txt_file.close(), png_file.close()
