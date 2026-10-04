import io
import json
import os
import random
from datetime import datetime
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
SUPPORT_ROLE_NAMES = [
    name.strip() for name in os.getenv("SUPPORT_ROLE_NAMES", "Support Team,Moderator,Admin").split(",") if name.strip()
]

CATEGORY_MAP = {
    "general": "General Support",
    "billing": "Billing",
    "technical": "Technical Support",
    "account": "Account Support",
}

PRIORITY_COLORS = {
    "low": 0x2ECC71,
    "medium": 0xF1C40F,
    "high": 0xE67E22,
    "urgent": 0xE74C3C,
}


class TicketModal(discord.ui.Modal, title="Create a Ticket"):
    def __init__(self, category: str, priority: str = "medium") -> None:
        super().__init__(timeout=None)
        self.category = category
        self.priority = priority

        self.subject = discord.ui.TextInput(
            label="Ticket Subject",
            placeholder="Brief summary of the issue",
            min_length=3,
            max_length=100,
        )
        self.description = discord.ui.TextInput(
            label="Ticket Details",
            placeholder="Describe your issue or request in detail",
            style=discord.TextStyle.long,
            min_length=10,
            max_length=1000,
        )

        self.add_item(self.subject)
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await create_ticket(
            interaction,
            category=self.category,
            priority=self.priority,
            subject=self.subject.value,
            note=self.description.value,
        )


class TicketCategoryButton(discord.ui.Button):
    def __init__(self, label: str, category: str):
        super().__init__(label=label, style=discord.ButtonStyle.primary, custom_id=f"ticket-{category}")
        self.category = category

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(TicketModal(category=self.category))


class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for category_key, title in CATEGORY_MAP.items():
            self.add_item(TicketCategoryButton(title, category_key))


async def get_or_create_category(guild: discord.Guild, category_key: str) -> discord.CategoryChannel:
    category_name = CATEGORY_MAP[category_key]
    existing = discord.utils.get(guild.categories, name=category_name)
    if existing:
        return existing
    return await guild.create_category(category_name)


async def get_or_create_logs_channel(guild: discord.Guild) -> discord.TextChannel:
    channel = discord.utils.get(guild.text_channels, name="ticket-logs")
    if channel:
        return channel
    return await guild.create_text_channel("ticket-logs", reason="Ticket logs channel")


def sanitize_ticket_name(value: str) -> str:
    cleaned = "".join(ch for ch in value.lower() if ch.isalnum() or ch in ("-", "_"))
    return cleaned[:20] or "ticket"


def get_support_roles(guild: discord.Guild) -> list[discord.Role]:
    roles: list[discord.Role] = []
    for role_name in SUPPORT_ROLE_NAMES:
        role = discord.utils.get(guild.roles, name=role_name)
        if role:
            roles.append(role)
    return roles


async def create_ticket(
    interaction: discord.Interaction,
    *,
    category: str,
    priority: str,
    subject: str,
    note: str,
) -> None:
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    if category not in CATEGORY_MAP:
        category = "general"
    if priority not in PRIORITY_COLORS:
        priority = "medium"

    category_channel = await get_or_create_category(guild, category)
    user = interaction.user
    ticket_number = random.randint(1000, 9999)
    ticket_name = f"ticket-{sanitize_ticket_name(user.name)}-{ticket_number}"
    member_overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False, send_messages=False, read_message_history=False),
        user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
    }

    for role in get_support_roles(guild):
        member_overwrites[role] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_messages=True,
            attach_files=True,
            embed_links=True,
        )

    ticket_channel = await guild.create_text_channel(
        ticket_name,
        category=category_channel,
        overwrites=member_overwrites,
        reason=f"Support ticket for {user.name}",
    )

    metadata = {
        "ticket_id": ticket_number,
        "user_id": user.id,
        "user_name": user.name,
        "category": category,
        "priority": priority,
        "subject": subject,
        "note": note,
        "status": "open",
        "created_at": datetime.utcnow().isoformat(timespec="seconds"),
    }
    ticket_channel.topic = json.dumps(metadata, ensure_ascii=False)

    embed = discord.Embed(
        title=f"Ticket #{ticket_number} - {subject}",
        description=note,
        color=PRIORITY_COLORS[priority],
        timestamp=datetime.utcnow(),
    )
    embed.add_field(name="Opened by", value=user.mention, inline=True)
    embed.add_field(name="Category", value=CATEGORY_MAP[category], inline=True)
    embed.add_field(name="Priority", value=priority.title(), inline=True)
    embed.add_field(name="Status", value="Open", inline=False)
    embed.set_footer(text="Use /ticket close or /ticket resolve when finished")

    await ticket_channel.send(f"{user.mention} your ticket has been created.")
    await ticket_channel.send(embed=embed)
    await ticket_channel.send(
        "Support instructions: use `/ticket close` to close the ticket or `/ticket resolve` to mark it as resolved."
    )

    try:
        await user.send(
            f"Your ticket `{ticket_name}` has been created in {guild.name}. "
            f"You can access it in: #{ticket_channel.name}"
        )
    except discord.Forbidden:
        pass

    await interaction.response.send_message(
        f"Your ticket has been created: {ticket_channel.mention}",
        ephemeral=True,
    )


async def get_ticket_metadata(channel: discord.TextChannel) -> dict[str, Any]:
    if not channel.topic:
        return {}
    try:
        return json.loads(channel.topic)
    except json.JSONDecodeError:
        return {}


async def export_ticket_transcript(channel: discord.TextChannel, status: str) -> None:
    guild = channel.guild
    if guild is None:
        return

    logs_channel = await get_or_create_logs_channel(guild)
    transcript_lines = [
        f"Ticket: {channel.name}",
        f"Status: {status}",
        f"Closed at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
    ]

    messages = [message async for message in channel.history(limit=200, oldest_first=True)]
    for message in messages:
        timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
        author = message.author.display_name
        text = message.content if message.content else "[No text content]"
        transcript_lines.append(f"[{timestamp}] {author}: {text}")

    transcript = "\n".join(transcript_lines)
    file_obj = io.StringIO(transcript)
    discord_file = discord.File(file_obj, filename=f"{channel.name}-{status}.txt")
    await logs_channel.send(f"Transcript for {channel.mention} ({status})", file=discord_file)


async def is_ticket_manager(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.administrator:
        return True

    for role in get_support_roles(interaction.guild):
        if role in interaction.user.roles:
            return True

    return False


class TicketBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)


bot = TicketBot()


@bot.tree.command(name="ticket")
async def ticket_root(interaction: discord.Interaction) -> None:
    await interaction.response.send_message("Use /ticket new, /ticket panel, /ticket close, or /ticket resolve.", ephemeral=True)


@bot.tree.command(name="ticket-panel")
async def ticket_panel(interaction: discord.Interaction) -> None:
    """Send a ticket panel to the current channel."""
    await interaction.response.send_message(
        embed=discord.Embed(
            title="Support Ticket Panel",
            description="Choose a category to open a support ticket.",
            color=discord.Color.blurple(),
        ),
        view=TicketPanelView(),
    )


@bot.tree.command(name="ticket-new")
@app_commands.describe(
    category="Ticket category",
    priority="Ticket priority",
    subject="Short issue summary",
    note="More details about the problem",
)
@app_commands.choices(
    category=[
        app_commands.Choice(name="General Support", value="general"),
        app_commands.Choice(name="Billing", value="billing"),
        app_commands.Choice(name="Technical Support", value="technical"),
        app_commands.Choice(name="Account Support", value="account"),
    ],
    priority=[
        app_commands.Choice(name="Low", value="low"),
        app_commands.Choice(name="Medium", value="medium"),
        app_commands.Choice(name="High", value="high"),
        app_commands.Choice(name="Urgent", value="urgent"),
    ],
)
async def ticket_new(
    interaction: discord.Interaction,
    category: str,
    priority: str,
    subject: str,
    note: str,
) -> None:
    await create_ticket(interaction, category=category, priority=priority, subject=subject, note=note)


@bot.tree.command(name="ticket-close")
async def ticket_close(interaction: discord.Interaction) -> None:
    """Close the current ticket."""
    if interaction.channel is None or not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("This command must be used in a ticket channel.", ephemeral=True)
        return

    if not await is_ticket_manager(interaction):
        await interaction.response.send_message("You do not have permission to close tickets.", ephemeral=True)
        return

    metadata = await get_ticket_metadata(interaction.channel)
    if not metadata:
        await interaction.response.send_message("This is not a valid ticket channel.", ephemeral=True)
        return

    await export_ticket_transcript(interaction.channel, "closed")
    await interaction.channel.send("This ticket has been closed.")
    await interaction.channel.edit(
        name=f"closed-{interaction.channel.name}",
        reason="Ticket closed",
        topic=json.dumps({**metadata, "status": "closed"}, ensure_ascii=False),
    )
    await interaction.response.send_message("Ticket closed and transcript saved.", ephemeral=True)


@bot.tree.command(name="ticket-resolve")
async def ticket_resolve(interaction: discord.Interaction) -> None:
    """Resolve the current ticket."""
    if interaction.channel is None or not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("This command must be used in a ticket channel.", ephemeral=True)
        return

    if not await is_ticket_manager(interaction):
        await interaction.response.send_message("You do not have permission to resolve tickets.", ephemeral=True)
        return

    metadata = await get_ticket_metadata(interaction.channel)
    if not metadata:
        await interaction.response.send_message("This is not a valid ticket channel.", ephemeral=True)
        return

    await export_ticket_transcript(interaction.channel, "resolved")
    await interaction.channel.send("This ticket has been resolved.")
    await interaction.channel.edit(
        name=f"resolved-{interaction.channel.name}",
        reason="Ticket resolved",
        topic=json.dumps({**metadata, "status": "resolved"}, ensure_ascii=False),
    )
    await interaction.response.send_message("Ticket resolved and transcript saved.", ephemeral=True)


@bot.event
async def on_ready() -> None:
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("Ticket bot is ready!")


if __name__ == "__main__":
    if not TOKEN:
        raise ValueError("DISCORD_TOKEN is missing. Add it to your .env file.")
    bot.run(TOKEN)


# End of file
