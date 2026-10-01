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


async def _ensure_valid_peer(client: TelegramClient, entity: Any) -> Any:
    """Follows basic-group -> supergroup migrations and ensures a valid entity."""
    migrated = getattr(entity, "migrated_to", None)

    if isinstance(migrated, types.InputChannel):
        entity = await client.get_entity(migrated)

    if getattr(entity, "min", False):
        entity = await client.get_entity(get_peer_id(entity))

    return entity


async def _peer_is_usable(client: TelegramClient, peer: Any) -> bool:
    """Cheap live check: ask Telegram for 1 message from this peer.

    Telethon happily builds an InputPeer with a missing/zero access_hash from a
    stale entity object, and the failure only shows up later in SendMediaRequest
    ("An invalid Peer was used"), *after* the whole file has been uploaded.
    Probing first catches that immediately.
    """
    try:
        await client.get_messages(peer, limit=1)
        return True
    except (RPCError, ValueError, TypeError):
        return False


async def get_valid_input_peer(client: TelegramClient, entity: Any) -> Any:
    """Return an InputPeer that Telegram has actually accepted.

    Tries, in order:
      1. the entity passed in (following basic-group -> supergroup migration),
      2. Telethon's session cache for that peer id,
      3. the matching dialog's own ``input_entity`` (always carries a fresh
         access_hash straight from the dialog list).
    """
    peer_id = get_peer_id(entity)
    candidates: list[Any] = []

    # 1. Follow migration (old basic group -> supergroup) if needed
    try:
        entity = await _ensure_valid_peer(client, entity)
        peer_id = get_peer_id(entity)
        candidates.append(await client.get_input_entity(entity))
    except (RPCError, ValueError, TypeError):
        pass

    # 2. Session cache lookup by id
    try:
        candidates.append(await client.get_input_entity(peer_id))
    except (RPCError, ValueError, TypeError):
        pass

    for peer in candidates:
        if await _peer_is_usable(client, peer):
            return peer

    # 3. Fall back to the dialog list (fresh access hashes)
    async for dialog in client.iter_dialogs():
        if dialog.id == peer_id:
            if await _peer_is_usable(client, dialog.input_entity):
                return dialog.input_entity
            break

    raise ValueError(
        "Telegram rejected this destination as an invalid peer. The chat may have "
        "been migrated/deleted, or your account can no longer access it. "
        "Pick another group, or choose '➕ Create a New Private Group'."
    )


async def resolve_chat(client: TelegramClient, raw: str) -> Any:
    raw = clean_group_input(raw)
    if not raw:
        raise ValueError("No Telegram destination was supplied.")

    # Warm up the in-memory session cache with recent dialogs
    await client.get_dialogs(limit=150)

    # 1. Telegram Web browser URLs: https://web.telegram.org/a/#-100123456 or /k/#-123456
    web_match = re.search(r"web\.telegram\.org/.*#(-?\d+)", raw, re.IGNORECASE)
    if web_match:
        peer_id = int(web_match.group(1))
        entity = await client.get_entity(peer_id)
        return await _ensure_valid_peer(client, entity)

    # 2. Private invite links: https://t.me/+XXXX or https://t.me/joinchat/XXXX
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
            return await _ensure_valid_peer(client, checked.chat)

        title = getattr(checked, "title", "this chat")
        join_now = await questionary.confirm(
            f"Invite link points to '{title}'. Join this group now?", default=True
        ).ask_async()
        if not join_now:
            raise ValueError("Cancelled joining invite link.")

        joined = await client(functions.messages.ImportChatInviteRequest(hash=invite_hash))
        if getattr(joined, "chats", None):
            return await _ensure_valid_peer(client, joined.chats[0])
        raise ValueError("Telegram did not return the joined chat.")

    # 3. Private chat/channel internal links: https://t.me/c/1234567890/1
    private_c_match = re.search(
        r"(?:https?://)?(?:t|telegram)\.me/c/(\d+)(?:/\d+)?",
        raw,
        re.IGNORECASE,
    )
    if private_c_match:
        channel_id = int(f"-100{private_c_match.group(1)}")
        entity = await client.get_entity(channel_id)
        return await _ensure_valid_peer(client, entity)

    # 4. Public t.me / telegram.me links: https://t.me/username or t.me/username/
    public_match = re.fullmatch(
        r"(?:https?://)?(?:t|telegram)\.me/([A-Za-z0-9_]+)/?(?:\?.*)?",
        raw,
        re.IGNORECASE,
    )
    if public_match:
        entity = await client.get_entity(public_match.group(1))
        return await _ensure_valid_peer(client, entity)

    # 5. Direct @username or numeric ID
    if raw.startswith("@"):
        entity = await client.get_entity(raw)
        return await _ensure_valid_peer(client, entity)

    try:
        entity = await client.get_entity(int(raw))
    except ValueError:
        entity = await client.get_entity(raw)
    return await _ensure_valid_peer(client, entity)


async def _create_new_private_group(client: TelegramClient) -> Any:
    """Creates a new private Supergroup directly in your Telegram account."""
    title = await questionary.text(
        "Enter a name for your new private Telegram group:",
        validate=lambda t: bool(t.strip()) or "Group name cannot be empty",
    ).ask_async()
    if not title:
        raise KeyboardInterrupt

    result = await client(
        functions.channels.CreateChannelRequest(
            title=title.strip(),
            about="Created by upload-telegram",
            megagroup=True,
        )
    )
    if getattr(result, "chats", None):
        new_group = result.chats[0]
        console.print(f"[green]✔ Created new private supergroup:[/green] [bold]{title.strip()}[/bold]")
        return await _ensure_valid_peer(client, new_group)
    raise ValueError("Failed to create the Telegram group.")


async def prompt_destination(client: TelegramClient, prefilled_group: str | None = None) -> Any:
    if prefilled_group:
        return await resolve_chat(client, prefilled_group)

    mode = await questionary.select(
        "How would you like to select the destination Telegram group?",
        choices=[
            questionary.Choice("📋 Choose from my Telegram Groups / Channels", value="list"),
            questionary.Choice("➕ Create a New Private Group right now", value="create"),
            questionary.Choice("🔗 Paste a Group / Invite Link (Public or Private)", value="link"),
        ],
    ).ask_async()

    if mode is None:
        raise KeyboardInterrupt

    if mode == "create":
        return await _create_new_private_group(client)

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
    seen_ids: set[int] = set()

    async for dialog in client.iter_dialogs(limit=200):
        entity = dialog.entity
        if not isinstance(entity, (types.Chat, types.Channel)):
            continue

        # Skip left, kicked, or forbidden chats
        if getattr(entity, "left", False) or getattr(entity, "kicked", False):
            continue

        # If a basic Chat was migrated to a Supergroup, resolve the Supergroup instead
        if getattr(entity, "deactivated", False) or getattr(entity, "migrated_to", None):
            migrated = getattr(entity, "migrated_to", None)
            if isinstance(migrated, types.InputChannel):
                try:
                    entity = await client.get_entity(migrated)
                except Exception:  # noqa: BLE001
                    continue
            else:
                continue

        peer_id = get_peer_id(entity)
        if peer_id in seen_ids:
            continue
        seen_ids.add(peer_id)

        is_channel = isinstance(entity, types.Channel) and getattr(entity, "broadcast", False)
        badge = "📢 Channel" if is_channel else "👥 Group  "
        title = getattr(entity, "title", dialog.name)
        choices.append(questionary.Choice(f"{badge} | {title}", value=entity))

    if not choices:
        raise ValueError("No active groups or channels found in your Telegram account.")

    selected = await questionary.select(
        "Select destination group/channel (Use ↑/↓ arrows and press Enter):",
        choices=choices,
        use_indicator=True,
    ).ask_async()

    if selected is None:
        raise KeyboardInterrupt
    return await _ensure_valid_peer(client, selected)


def display_destination(entity: Any) -> str:
    title = getattr(entity, "title", None)
    username = getattr(entity, "username", None)
    if title and username:
        return f"{title} (@{username})"
    return title or (f"@{username}" if username else str(get_peer_id(entity)))