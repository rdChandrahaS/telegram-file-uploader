from __future__ import annotations

import re
from typing import Any
import questionary
from rich.console import Console
from telethon import TelegramClient, functions, types
from telethon.errors import RPCError
from telethon.utils import get_peer_id

console = Console()


def clean_group_input(value: str) -> str:
    value = value.strip()
    return re.sub(r"^tg://openmessage\?user_id=", "", value)


async def resolve_chat(client: TelegramClient, raw: str) -> Any:
    raw = clean_group_input(raw)
    if not raw:
        raise ValueError("No Telegram destination was supplied.")

    # 1. Private invite links: https://t.me/+XXXX or https://t.me/joinchat/XXXX
    invite_match = re.search(
        r"(?:https?://)?(?:t|telegram)\.me/(?:\+|joinchat/)([^/?#\s]+)",
        raw,
        re.IGNORECASE,
    )
    if invite_match:
        invite_hash = invite_match.group(1)
        try:
            checked = await client(functions.messages.CheckChatInviteRequest(hash=invite_hash))
        except RPCError as exc:
            raise ValueError(f"Telegram could not inspect that invite link: {exc}") from exc

        if isinstance(checked, types.messages.ChatInviteAlready):
            return checked.chat

        title = getattr(checked, "title", "this chat")
        join_now = await questionary.confirm(
            f"Invite link points to '{title}'. Join this group now?", default=True
        ).ask_async()
        if not join_now:
            raise ValueError("Cancelled joining invite link.")

        joined = await client(functions.messages.ImportChatInviteRequest(hash=invite_hash))
        if getattr(joined, "chats", None):
            return joined.chats[0]
        raise ValueError("Telegram did not return the joined chat.")

    # 2. Private chat/channel internal links: https://t.me/c/1234567890/1
    private_c_match = re.search(
        r"(?:https?://)?(?:t|telegram)\.me/c/(\d+)(?:/\d+)?",
        raw,
        re.IGNORECASE,
    )
    if private_c_match:
        channel_id = int(f"-100{private_c_match.group(1)}")
        return await client.get_entity(channel_id)

    # 3. Public t.me / telegram.me links: https://t.me/username or t.me/username/
    public_match = re.fullmatch(
        r"(?:https?://)?(?:t|telegram)\.me/([A-Za-z0-9_]+)/?(?:\?.*)?",
        raw,
        re.IGNORECASE,
    )
    if public_match:
        return await client.get_entity(public_match.group(1))

    # 4. Direct @username or numeric ID
    if raw.startswith("@"):
        return await client.get_entity(raw)

    try:
        return await client.get_entity(int(raw))
    except ValueError:
        return await client.get_entity(raw)


async def prompt_destination(client: TelegramClient, prefilled_group: str | None = None) -> Any:
    if prefilled_group:
        return await resolve_chat(client, prefilled_group)

    mode = await questionary.select(
        "How would you like to select the destination Telegram group?",
        choices=[
            questionary.Choice("🔗 Paste a Group / Invite Link (Public or Private)", value="link"),
            questionary.Choice("📋 Choose from my Telegram Groups / Channels", value="list"),
        ],
    ).ask_async()

    if mode is None:
        raise KeyboardInterrupt

    if mode == "link":
        raw_link = await questionary.text(
            "Paste Telegram group link (e.g. https://t.me/+xxxx or https://t.me/groupname):",
            validate=lambda text: bool(text.strip()) or "Please enter a valid group link or @username",
        ).ask_async()
        if not raw_link:
            raise KeyboardInterrupt
        return await resolve_chat(client, raw_link)

    console.print("[cyan]Loading your Telegram groups and channels...[/cyan]")
    choices = []
    async for dialog in client.iter_dialogs(limit=150):
        entity = dialog.entity
        if isinstance(entity, (types.Chat, types.Channel)):
            is_channel = isinstance(entity, types.Channel) and getattr(entity, "broadcast", False)
            badge = "📢 Channel" if is_channel else "👥 Group  "
            choices.append(questionary.Choice(f"{badge} | {dialog.name}", value=entity))

    if not choices:
        raise ValueError("No groups or channels found in your Telegram account.")

    selected = await questionary.select(
        "Select destination group/channel (Use ↑/↓ arrows and press Enter):",
        choices=choices,
        use_indicator=True,
    ).ask_async()

    if selected is None:
        raise KeyboardInterrupt
    return selected


def display_destination(entity: Any) -> str:
    title = getattr(entity, "title", None)
    username = getattr(entity, "username", None)
    if title and username:
        return f"{title} (@{username})"
    return title or (f"@{username}" if username else str(get_peer_id(entity)))