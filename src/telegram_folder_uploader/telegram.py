from __future__ import annotations

import re
from typing import Any

from telethon import TelegramClient, functions, types
from telethon.errors import RPCError


def clean_group_input(value: str) -> str:
    value = value.strip()
    return re.sub(r"^tg://openmessage\?user_id=", "", value)


async def resolve_chat(client: TelegramClient, raw: str) -> Any:
    raw = clean_group_input(raw)
    if not raw:
        raise ValueError("No Telegram destination was supplied.")

    if raw.startswith("@"):
        return await client.get_entity(raw)

    public_match = re.fullmatch(r"https?://t\.me/([A-Za-z0-9_]+)(?:\?.*)?", raw)
    if public_match:
        return await client.get_entity(public_match.group(1))

    invite_match = re.search(r"(?:https?://)?t\.me/(?:\+|joinchat/)([^/?#]+)", raw)
    if invite_match:
        invite_hash = invite_match.group(1)
        try:
            checked = await client(functions.messages.CheckChatInviteRequest(hash=invite_hash))
        except RPCError as exc:
            raise ValueError(f"Telegram could not inspect that invite link: {exc}") from exc

        if isinstance(checked, types.messages.ChatInviteAlready):
            return await client.get_entity(checked.chat)

        title = getattr(checked, "title", "this chat")
        print(f"Invite link refers to: {title}")
        answer = input("You are not currently in this chat. Join it now? [y/N]: ").strip().lower()
        if answer != "y":
            raise ValueError("Not joining the invite chat. Join it in Telegram first, then run again.")

        joined = await client(functions.messages.ImportChatInviteRequest(hash=invite_hash))
        if getattr(joined, "chats", None):
            return joined.chats[0]
        raise ValueError("Telegram did not return the joined chat.")

    try:
        return await client.get_entity(int(raw))
    except ValueError:
        return await client.get_entity(raw)


async def choose_from_dialogs(client: TelegramClient) -> Any:
    print("\nLoading your groups/channels...")
    choices = []
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, (types.Chat, types.Channel)):
            choices.append(dialog)
        if len(choices) >= 100:
            break

    if not choices:
        raise ValueError("No groups/channels were found in your Telegram account.")

    for index, dialog in enumerate(choices, 1):
        is_channel = isinstance(dialog.entity, types.Channel) and getattr(dialog.entity, "broadcast", False)
        kind = "channel" if is_channel else "group"
        print(f"  {index:3d}. [{kind}] {dialog.name}")

    while True:
        raw = input(f"\nSelect destination [1-{len(choices)}]: ").strip()
        try:
            selected = int(raw)
        except ValueError:
            selected = -1
        if 1 <= selected <= len(choices):
            return choices[selected - 1].entity
        print("Please enter one of the displayed numbers.")


def display_destination(entity: Any) -> str:
    title = getattr(entity, "title", None)
    username = getattr(entity, "username", None)
    if title and username:
        return f"{title} (@{username})"
    return title or (f"@{username}" if username else str(entity))
