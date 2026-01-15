import asyncio
from datetime import datetime
from io import BytesIO

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    Message,
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaDocument,
)
from aiogram.utils.media_group import MediaGroupBuilder

from maestro.config import Server, Action, Config
from maestro.ssh_client import connect_to_server
from maestro.text_to_png import text_to_png

router = Router()


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
    if len(args) == 2:
        # /deploy <server> <action>
        server, action = args
        server_obj = config.servers.get(server)
        if not server_obj:
            await message.reply("Server not found")
            return

        allowed = (
            chat_id in config.allowed_chat_ids or chat_id in server_obj.allowed_chat_ids
        )
        if not allowed:
            await message.reply("You are not allowed to deploy to this server")
            return

        actions = [server_obj.actions.get(action)]
        if not actions and action != "all":
            await message.reply("Action not found")
            return
        if action == "all":
            actions = server_obj.actions.values()

        for action_obj in actions:
            await deploy_use_case(message, server_obj, action_obj)
        return

    await show_server_selection(message, config, chat_id, auto_select_single=True)


@router.callback_query(F.data.startswith("deploy:"))
async def handle_deploy_callback(callback: CallbackQuery, config: Config) -> None:
    chat_id = callback.message.chat.id
    parts = callback.data.split(":", 3)

    if len(parts) < 2:
        await callback.answer("Invalid callback data", show_alert=True)
        return

    if parts[1] == "menu":
        await show_server_selection(callback.message, config, chat_id, is_callback=True)
        await callback.answer()
    elif parts[1] == "server" and len(parts) >= 3:
        server_name = parts[2]
        await show_action_selection(
            callback.message, config, chat_id, server_name, is_callback=True
        )
        await callback.answer()
    elif parts[1] == "action" and len(parts) >= 4:
        server_name = parts[2]
        action_name = parts[3]
        await execute_deployment(
            callback.message, config, chat_id, server_name, action_name
        )
        await callback.answer()
    else:
        await callback.answer("Unknown action", show_alert=True)


async def show_server_selection(
    message: Message,
    config: Config,
    chat_id: int,
    is_callback: bool = False,
    return_message: bool = False,
    standalone: bool = False,
    auto_select_single: bool = False,
) -> Message | None:
    """Show interactive buttons for server selection"""
    allowed = chat_id in config.allowed_chat_ids

    buttons = []
    accessible_servers = []
    for server_name, server in config.servers.items():
        server_allowed = allowed or chat_id in server.allowed_chat_ids
        if server_allowed:
            accessible_servers.append(server_name)
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=server_name, callback_data=f"deploy:server:{server_name}"
                    )
                ]
            )

    if not buttons:
        text = "You don't have access to any servers."
        if is_callback:
            await message.edit_text(text)
            return message if return_message else None
        else:
            sent_msg = await message.reply(text)
            return sent_msg if return_message else None

    if auto_select_single and len(accessible_servers) == 1:
        server_name = accessible_servers[0]
        await show_action_selection(
            message, config, chat_id, server_name, is_callback=is_callback
        )
        return None

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = "Select a server:"
    if is_callback:
        await message.edit_text(text, reply_markup=keyboard)
        return message if return_message else None
    else:
        if standalone:
            sent_msg = await message.bot.send_message(
                chat_id=message.chat.id, text=text, reply_markup=keyboard
            )
        else:
            sent_msg = await message.reply(text, reply_markup=keyboard)
        return sent_msg if return_message else None


async def show_action_selection(
    message: Message,
    config: Config,
    chat_id: int,
    server_name: str,
    is_callback: bool = False,
) -> None:
    """Show interactive buttons for action selection"""

    server = config.servers.get(server_name)
    if not server:
        text = "Server not found"
        if is_callback:
            await message.edit_text(text)
        else:
            await message.reply(text)
        return

    allowed = chat_id in config.allowed_chat_ids or chat_id in server.allowed_chat_ids
    if not allowed:
        text = "You are not allowed to deploy to this server"
        if is_callback:
            await message.edit_text(text)
        else:
            await message.reply(text)
        return

    buttons = []
    for action_name, action in server.actions.items():
        description = f": {action.description}" if action.description else ""
        button_text = f"{action_name}{description}"
        # Truncate button text if too long (limit is 64 chars)
        if len(button_text) > 60:
            button_text = button_text[:57] + "..."
        buttons.append(
            [
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"deploy:action:{server_name}:{action_name}",
                )
            ]
        )

    if server.allow_run_all:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="Run All Actions",
                    callback_data=f"deploy:action:{server_name}:all",
                )
            ]
        )

    buttons.append(
        [InlineKeyboardButton(text="Back to Servers", callback_data="deploy:menu")]
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = f"Select an action for server **{server_name}**:"
    if is_callback:
        await message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    else:
        await message.reply(text, reply_markup=keyboard, parse_mode="Markdown")


async def execute_deployment(
    message: Message, config: Config, chat_id: int, server_name: str, action_name: str
) -> None:
    """Execute the selected deployment action"""
    server = config.servers.get(server_name)
    if not server:
        await message.reply("Server not found")
        return

    allowed = chat_id in config.allowed_chat_ids or chat_id in server.allowed_chat_ids
    if not allowed:
        await message.reply("You are not allowed to deploy to this server")
        return

    if action_name == "all":
        actions = list(server.actions.values())
    else:
        action = server.actions.get(action_name)
        if not action:
            await message.reply("Action not found")
            return
        actions = [action]

    # Deploy message
    action_list = ", ".join(a.name for a in actions)
    progress_text = f"Running: {action_list} on {server_name}..."

    # Attachment placeholders
    placeholder_text = "Loading results..."
    placeholder_png = text_to_png(placeholder_text)
    placeholder_png.name = "placeholder.png"

    placeholder_txt = BytesIO(b"Loading...")
    placeholder_txt.name = "placeholder.txt"

    # Replace placeholders with results
    placeholder_group = MediaGroupBuilder(caption=progress_text)
    placeholder_group.add_document(
        BufferedInputFile(placeholder_png.read(), placeholder_png.name)
    )
    placeholder_group.add_document(
        BufferedInputFile(placeholder_txt.read(), placeholder_txt.name)
    )

    placeholder_msgs = await message.bot.send_media_group(
        chat_id=message.chat.id, media=placeholder_group.build()
    )
    progress_msg = placeholder_msgs[0] if placeholder_msgs else None

    # Delete previous menu if it exists
    try:
        await message.delete()
    except Exception:
        pass

    await show_server_selection(
        progress_msg, config, chat_id, is_callback=False, standalone=True
    )

    asyncio.create_task(
        run_deployment_async(
            progress_msg, placeholder_msgs, server, actions, server_name
        )
    )


async def run_deployment_async(
    progress_msg: Message,
    placeholder_msgs: list[Message],
    server: Server,
    actions: list[Action],
    server_name: str,
) -> None:
    """Run deployment asynchronously and replace placeholder with actual results"""
    if not progress_msg or not placeholder_msgs:
        return

    bot = progress_msg.bot
    results = []
    errors = []
    all_media_data = []  # Store (png_file, txt_file, action) tuples

    async def run_single_action(action: Action):
        try:
            txt_file, png_file = await asyncio.to_thread(run_action, server, action)
            return (png_file, txt_file, action, None)
        except Exception as e:
            return (None, None, action, str(e))

    action_results = await asyncio.gather(
        *[run_single_action(action) for action in actions]
    )

    # Process results
    for png_file, txt_file, action, error in action_results:
        if error:
            error_msg = f"{action.name}: {error}"
            errors.append(error_msg)
            results.append(error_msg)
        else:
            all_media_data.append((png_file, txt_file, action))
            results.append(f"{action.name}")

    # Edit placeholder messages with results
    if all_media_data and len(placeholder_msgs) >= 2:
        # Edit the placeholder messages
        if len(all_media_data) == 1 and len(actions) == 1:
            png_file, txt_file, action = all_media_data[0]
            png_file.seek(0)
            txt_file.seek(0)

            result_text = f"Result of action {action.name} on {server_name}"

            try:
                await bot.edit_message_media(
                    chat_id=progress_msg.chat.id,
                    message_id=placeholder_msgs[0].message_id,
                    media=InputMediaDocument(
                        media=BufferedInputFile(png_file.read(), png_file.name),
                        caption=result_text,
                    ),
                )
                png_file.seek(0)
                txt_file.seek(0)

                await bot.edit_message_media(
                    chat_id=progress_msg.chat.id,
                    message_id=placeholder_msgs[1].message_id,
                    media=InputMediaDocument(
                        media=BufferedInputFile(txt_file.read(), txt_file.name)
                    ),
                )
                png_file.close()
                txt_file.close()
            except Exception as e:
                for msg in placeholder_msgs:
                    try:
                        await msg.delete()
                    except Exception:
                        pass
                png_file.seek(0)
                txt_file.seek(0)
                # Send new media group
                media_group = MediaGroupBuilder(caption=result_text)
                media_group.add_document(
                    BufferedInputFile(png_file.read(), png_file.name)
                )
                media_group.add_document(
                    BufferedInputFile(txt_file.read(), txt_file.name)
                )
                await bot.send_media_group(
                    chat_id=progress_msg.chat.id, media=media_group.build()
                )
                png_file.close()
                txt_file.close()
        else:
            # Multiple actions - edit caption of first placeholder
            if all_media_data:
                first_action = all_media_data[0][2]
                first_caption = f"Result of action {first_action.name} on {server.name}"
                try:
                    await bot.edit_message_caption(
                        chat_id=progress_msg.chat.id,
                        message_id=placeholder_msgs[0].message_id,
                        caption=first_caption,
                    )
                except Exception:
                    pass

            for png_file, txt_file, action in all_media_data[1:]:
                media_group = MediaGroupBuilder(
                    caption=f"Result of action {action.name} on {server.name}"
                )
                media_group.add_document(
                    BufferedInputFile(png_file.read(), png_file.name)
                )
                media_group.add_document(
                    BufferedInputFile(txt_file.read(), txt_file.name)
                )
                try:
                    await bot.send_media_group(
                        chat_id=progress_msg.chat.id, media=media_group.build()
                    )
                except Exception:
                    pass
                png_file.close()
                txt_file.close()
    else:
        if actions:
            first_action = actions[0]
            error_caption = f"Result of action {first_action.name} on {server_name}"
            if errors:
                error_caption += f"\n\nErrors:\n" + "\n".join(errors)
        else:
            error_caption = f"Result on {server_name}"

        try:
            await bot.edit_message_caption(
                chat_id=progress_msg.chat.id,
                message_id=placeholder_msgs[0].message_id,
                caption=error_caption,
            )
        except Exception:
            for msg in placeholder_msgs:
                try:
                    await msg.delete()
                except Exception:
                    pass
            await bot.send_message(chat_id=progress_msg.chat.id, text=error_caption)


async def deploy_use_case(
    message: Message, server: Server, action: Action
) -> Message | None:
    """Execute a deployment action"""

    info = await message.reply(f"Running action {action.name} on {server.name}...")
    txt_file, png_file = run_action(server, action)

    media_group = MediaGroupBuilder(
        caption=f"Result of action {action.name} on {server.name}"
    )
    media_group.add_document(BufferedInputFile(png_file.read(), png_file.name))
    media_group.add_document(BufferedInputFile(txt_file.read(), txt_file.name))

    await info.reply_media_group(media_group.build())

    txt_file.close(), png_file.close()

    return info
