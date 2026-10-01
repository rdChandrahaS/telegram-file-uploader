from __future__ import annotations

import re
from typing import Any

import questionary
from rich.console import Console
from telethon import TelegramClient, functions, types
from telethon.errors import (
    ChannelInvalidError,
    ChatIdInvalidError,
    PeerIdInvalidError,
    RPCError,
)
from telethon.utils import get_peer_id

console = Console()


def clean_group_input(value: str) -> str:
    """Normalize Telegram destination input."""
    value = value.strip()

    # Support tg://openmessage?user_id=...
    value = re.sub(
        r"^tg://openmessage\?user_id=",
        "",
        value,
        flags=re.IGNORECASE,
    )

    return value


async def _ensure_valid_entity(
    client: TelegramClient,
    entity: Any,
) -> Any:
    """
    Normalize a Telegram entity.

    Handles:
    - basic group -> supergroup migration
    - incomplete/min channel entities
    """
    migrated = getattr(entity, "migrated_to", None)

    if isinstance(migrated, types.InputChannel):
        entity = await client.get_entity(migrated)

    if getattr(entity, "min", False):
        entity = await client.get_entity(
            get_peer_id(entity)
        )

    return entity


async def get_valid_input_peer(
    client: TelegramClient,
    entity: Any,
) -> Any:
    """
    Refresh and return the best InputPeer available for the entity.

    The important path is:
        Telegram dialogs -> Dialog.input_entity

    Dialog.input_entity contains the peer information Telethon received
    for that chat, including the access hash where applicable.

    This avoids depending solely on a stale ID/entity cached in the session.
    """

    entity = await _ensure_valid_entity(
        client,
        entity,
    )

    target_peer_id = get_peer_id(entity)
    last_error: Exception | None = None

    # ---------------------------------------------------------------
    # 1. Refresh dialogs from Telegram and use the matching
    #    dialog.input_entity directly.
    # ---------------------------------------------------------------
    try:
        async for dialog in client.iter_dialogs(
            limit=None
        ):
            try:
                dialog_entity = await _ensure_valid_entity(
                    client,
                    dialog.entity,
                )
            except Exception:
                continue

            try:
                dialog_peer_id = get_peer_id(
                    dialog_entity
                )
            except (TypeError, ValueError):
                continue

            if dialog_peer_id != target_peer_id:
                continue

            # This is the important object:
            # Telegram supplied it as part of the dialog response.
            input_entity = dialog.input_entity

            if input_entity is None:
                continue

            return input_entity

    except RPCError as exc:
        last_error = exc

    # ---------------------------------------------------------------
    # 2. Try a fresh entity lookup.
    # ---------------------------------------------------------------
    try:
        username = getattr(
            entity,
            "username",
            None,
        )

        if username:
            fresh_entity = await client.get_entity(
                username
            )
        else:
            fresh_entity = await client.get_entity(
                entity
            )

        fresh_entity = await _ensure_valid_entity(
            client,
            fresh_entity,
        )

        input_entity = await client.get_input_entity(
            fresh_entity
        )

        return input_entity

    except (
        PeerIdInvalidError,
        ChannelInvalidError,
        ChatIdInvalidError,
        ValueError,
        TypeError,
        RPCError,
    ) as exc:
        last_error = exc

    # ---------------------------------------------------------------
    # 3. Final Telethon cache fallback.
    # ---------------------------------------------------------------
    try:
        input_entity = await client.get_input_entity(
            entity
        )

        return input_entity

    except Exception as exc:  # noqa: BLE001
        last_error = exc

    title = (
        getattr(entity, "title", None)
        or getattr(entity, "username", None)
        or str(target_peer_id)
    )

    raise RuntimeError(
        f"Could not resolve a usable Telegram peer for "
        f"'{title}'. The account may not currently have "
        f"access to that chat."
    ) from last_error


async def resolve_chat(
    client: TelegramClient,
    raw: str,
) -> Any:
    """
    Resolve a Telegram destination.

    Supported:
    - Telegram Web URLs
    - public t.me / telegram.me links
    - private invite links
    - private /c/ links
    - @username
    - numeric IDs
    """

    raw = clean_group_input(raw)

    if not raw:
        raise ValueError(
            "No Telegram destination was supplied."
        )

    # Refresh entity/dialog cache.
    await client.get_dialogs(
        limit=200
    )

    # ---------------------------------------------------------------
    # 1. Telegram Web URL
    #
    # Examples:
    # https://web.telegram.org/a/#-1001234567890
    # https://web.telegram.org/k/#-123456789
    # ---------------------------------------------------------------
    web_match = re.search(
        r"web\.telegram\.org/.*#(-?\d+)",
        raw,
        re.IGNORECASE,
    )

    if web_match:
        peer_id = int(
            web_match.group(1)
        )

        try:
            entity = await client.get_entity(
                peer_id
            )
        except ValueError as exc:
            raise ValueError(
                "Telegram could not resolve the Web Telegram "
                "destination. Select the group from your "
                "Telegram dialogs instead."
            ) from exc

        return await _ensure_valid_entity(
            client,
            entity,
        )

    # ---------------------------------------------------------------
    # 2. Private invite link
    #
    # https://t.me/+xxxx
    # https://t.me/joinchat/xxxx
    # ---------------------------------------------------------------
    invite_match = re.search(
        r"(?:https?://)?(?:t|telegram)\.me/"
        r"(?:\+|joinchat/)([^/?#\s]+)",
        raw,
        re.IGNORECASE,
    )

    if invite_match:
        invite_hash = invite_match.group(1)

        try:
            checked = await client(
                functions.messages.CheckChatInviteRequest(
                    hash=invite_hash
                )
            )
        except RPCError as exc:
            raise ValueError(
                f"Telegram could not inspect that invite link: {exc}"
            ) from exc

        if isinstance(
            checked,
            types.messages.ChatInviteAlready,
        ):
            return await _ensure_valid_entity(
                client,
                checked.chat,
            )

        title = getattr(
            checked,
            "title",
            "this chat",
        )

        join_now = await questionary.confirm(
            f"Invite link points to '{title}'. "
            f"Join this group now?",
            default=True,
        ).ask_async()

        if join_now is None:
            raise KeyboardInterrupt

        if not join_now:
            raise ValueError(
                "Cancelled joining invite link."
            )

        try:
            joined = await client(
                functions.messages.ImportChatInviteRequest(
                    hash=invite_hash
                )
            )
        except RPCError as exc:
            raise ValueError(
                f"Telegram could not join that invite link: {exc}"
            ) from exc

        if not getattr(
            joined,
            "chats",
            None,
        ):
            raise ValueError(
                "Telegram did not return the joined chat."
            )

        return await _ensure_valid_entity(
            client,
            joined.chats[0],
        )

    # ---------------------------------------------------------------
    # 3. Private /c/ link
    #
    # https://t.me/c/1234567890/123
    #
    # The actual channel/supergroup must already be known to
    # the account/session.
    # ---------------------------------------------------------------
    private_c_match = re.search(
        r"(?:https?://)?(?:t|telegram)\.me/"
        r"c/(\d+)(?:/\d+)?",
        raw,
        re.IGNORECASE,
    )

    if private_c_match:
        channel_id = int(
            f"-100{private_c_match.group(1)}"
        )

        try:
            entity = await client.get_entity(
                channel_id
            )
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "Telegram could not resolve this private /c/ link. "
                "Select the group from your Telegram dialogs first."
            ) from exc

        return await _ensure_valid_entity(
            client,
            entity,
        )

    # ---------------------------------------------------------------
    # 4. Public Telegram link
    #
    # https://t.me/groupname
    # https://telegram.me/groupname
    # ---------------------------------------------------------------
    public_match = re.fullmatch(
        r"(?:https?://)?(?:t|telegram)\.me/"
        r"([A-Za-z0-9_]+)/?(?:\?.*)?",
        raw,
        re.IGNORECASE,
    )

    if public_match:
        username = public_match.group(1)

        try:
            entity = await client.get_entity(
                username
            )
        except ValueError as exc:
            raise ValueError(
                f"Telegram could not resolve @{username}."
            ) from exc

        return await _ensure_valid_entity(
            client,
            entity,
        )

    # ---------------------------------------------------------------
    # 5. @username
    # ---------------------------------------------------------------
    if raw.startswith("@"):
        entity = await client.get_entity(
            raw
        )

        return await _ensure_valid_entity(
            client,
            entity,
        )

    # ---------------------------------------------------------------
    # 6. Numeric ID or other Telethon-supported input.
    # ---------------------------------------------------------------
    try:
        entity = await client.get_entity(
            int(raw)
        )
    except ValueError:
        entity = await client.get_entity(
            raw
        )

    return await _ensure_valid_entity(
        client,
        entity,
    )


async def _create_new_private_group(
    client: TelegramClient,
) -> Any:
    """Create a new private Telegram supergroup."""
    title = await questionary.text(
        "Enter a name for your new private Telegram group:",
        validate=lambda value: (
            bool(value.strip())
            or "Group name cannot be empty"
        ),
    ).ask_async()

    if title is None:
        raise KeyboardInterrupt

    title = title.strip()

    if not title:
        raise ValueError(
            "Group name cannot be empty."
        )

    result = await client(
        functions.channels.CreateChannelRequest(
            title=title,
            about="Created by telegram-folder-uploader",
            megagroup=True,
        )
    )

    if not getattr(
        result,
        "chats",
        None,
    ):
        raise ValueError(
            "Failed to create the Telegram group."
        )

    new_group = result.chats[0]

    console.print(
        "[green]✔ Created new private "
        "supergroup:[/green] "
        f"[bold]{title}[/bold]"
    )

    return await _ensure_valid_entity(
        client,
        new_group,
    )


async def prompt_destination(
    client: TelegramClient,
    prefilled_group: str | None = None,
) -> Any:
    """Prompt the user to select a Telegram destination."""

    # ---------------------------------------------------------------
    # Direct --group argument
    # ---------------------------------------------------------------
    if prefilled_group:
        return await resolve_chat(
            client,
            prefilled_group,
        )

    mode = await questionary.select(
        "How would you like to select the destination Telegram group?",
        choices=[
            questionary.Choice(
                "📋 Choose from my Telegram Groups / Channels",
                value="list",
            ),
            questionary.Choice(
                "➕ Create a New Private Group right now",
                value="create",
            ),
            questionary.Choice(
                "🔗 Paste a Group / Invite Link "
                "(Public or Private)",
                value="link",
            ),
        ],
    ).ask_async()

    if mode is None:
        raise KeyboardInterrupt

    # ---------------------------------------------------------------
    # Create a group
    # ---------------------------------------------------------------
    if mode == "create":
        return await _create_new_private_group(
            client
        )

    # ---------------------------------------------------------------
    # Paste link
    # ---------------------------------------------------------------
    if mode == "link":
        raw_link = await questionary.text(
            "Paste Telegram group link "
            "(e.g. https://t.me/+xxxx "
            "or https://t.me/groupname):",
            validate=lambda value: (
                bool(value.strip())
                or "Please enter a valid group link"
            ),
        ).ask_async()

        if raw_link is None:
            raise KeyboardInterrupt

        raw_link = raw_link.strip()

        if not raw_link:
            raise ValueError(
                "No Telegram destination was supplied."
            )

        return await resolve_chat(
            client,
            raw_link,
        )

    # ---------------------------------------------------------------
    # Select from dialogs
    # ---------------------------------------------------------------
    console.print(
        "[cyan]Loading your Telegram groups "
        "and channels...[/cyan]"
    )

    choices: list[questionary.Choice] = []
    seen_ids: set[int] = set()

    # Fetch all dialogs. This is also important for obtaining fresh
    # dialog.input_entity values from Telegram.
    async for dialog in client.iter_dialogs(
        limit=None
    ):
        entity = dialog.entity

        if not isinstance(
            entity,
            (types.Chat, types.Channel),
        ):
            continue

        if getattr(
            entity,
            "left",
            False,
        ):
            continue

        if getattr(
            entity,
            "kicked",
            False,
        ):
            continue

        if getattr(
            entity,
            "deactivated",
            False,
        ):
            continue

        # Follow basic-group migration.
        migrated = getattr(
            entity,
            "migrated_to",
            None,
        )

        if isinstance(
            migrated,
            types.InputChannel,
        ):
            try:
                entity = await client.get_entity(
                    migrated
                )
            except RPCError:
                continue

        try:
            peer_id = get_peer_id(entity)
        except (ValueError, TypeError):
            continue

        if peer_id in seen_ids:
            continue

        seen_ids.add(peer_id)

        is_broadcast = (
            isinstance(entity, types.Channel)
            and getattr(
                entity,
                "broadcast",
                False,
            )
        )

        badge = (
            "📢 Channel"
            if is_broadcast
            else "👥 Group  "
        )

        title = (
            getattr(
                entity,
                "title",
                None,
            )
            or dialog.name
            or str(peer_id)
        )

        choices.append(
            questionary.Choice(
                f"{badge} | {title}",
                value=entity,
            )
        )

    if not choices:
        raise ValueError(
            "No active groups or channels found "
            "in your Telegram account."
        )

    selected = await questionary.select(
        "Select destination group/channel "
        "(Use ↑/↓ arrows and press Enter):",
        choices=choices,
        use_indicator=True,
    ).ask_async()

    if selected is None:
        raise KeyboardInterrupt

    return await _ensure_valid_entity(
        client,
        selected,
    )


def display_destination(
    entity: Any,
) -> str:
    """Return a human-readable Telegram destination name."""
    title = getattr(
        entity,
        "title",
        None,
    )

    username = getattr(
        entity,
        "username",
        None,
    )

    if title and username:
        return f"{title} (@{username})"

    if title:
        return title

    if username:
        return f"@{username}"

    return str(
        get_peer_id(entity)
    )