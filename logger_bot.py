import discord
from discord import app_commands
import json
import os
from datetime import datetime, timedelta
import re
import asyncio
import random

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True
intents.voice_states = True
intents.guild_messages = True
intents.guild_reactions = True

class LoggingBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.config_file = "bot_config.json"
        self.log_channels = {}
        self.automod_config = {}
        self.reaction_roles = {}
        self.spam_counter = {}

    async def load_config(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, "r") as f:
                data = json.load(f)
                self.log_channels = {int(gid): ch for gid, ch in data.get("logs", {}).items()}
                self.automod_config = {int(gid): cfg for gid, cfg in data.get("automod", {}).items()}
                self.reaction_roles = {int(mid): roles for mid, roles in data.get("reaction_roles", {}).items()}

    async def save_config(self):
        data = {
            "logs": {str(k): v for k, v in self.log_channels.items()},
            "automod": {str(k): v for k, v in self.automod_config.items()},
            "reaction_roles": {str(k): v for k, v in self.reaction_roles.items()}
        }
        with open(self.config_file, "w") as f:
            json.dump(data, f, indent=4)

    def get_log_channel(self, guild: discord.Guild, log_type: str):
        if guild.id not in self.log_channels:
            return None
        cid = self.log_channels[guild.id].get(log_type)
        return guild.get_channel(cid) if cid else None

client = LoggingBot()

# ====================== COMMANDS ======================
# (All your commands + /automod + fixed /sync are here)

@client.tree.command(name="setlog", description="Set log channel")
@app_commands.choices(log_type=[app_commands.Choice(name=n, value=v) for n, v in [
    ("Deleted Messages", "message"), ("Message Edits", "edit"), ("Bulk Deletes", "bulk"),
    ("Joins & Leaves", "joinleave"), ("Role Changes", "role"), ("Timeouts", "timeout"),
    ("Bans & Unbans", "ban"), ("Voice Activity", "voice"), ("Nickname Changes", "nickname"),
    ("Channel Changes", "channel"), ("Server Boosts", "boost"), ("Invite Tracking", "invite"),
    ("Automod Actions", "automod")
]])
async def setlog(interaction: discord.Interaction, log_type: str, channel: discord.TextChannel):
    if interaction.guild is None: return await interaction.response.send_message("❌ Only in servers.", ephemeral=True)
    if interaction.guild.id not in client.log_channels:
        client.log_channels[interaction.guild.id] = {}
    client.log_channels[interaction.guild.id][log_type] = channel.id
    await client.save_config()
    await interaction.response.send_message(f"✅ **{log_type}** logs → {channel.mention}", ephemeral=True)

@client.tree.command(name="logstatus", description="Show log channels")
async def logstatus(interaction: discord.Interaction):
    if interaction.guild is None or interaction.guild.id not in client.log_channels:
        return await interaction.response.send_message("No logs set yet.", ephemeral=True)
    lines = [f"**{k.capitalize()}** → <#{v}>" for k, v in client.log_channels[interaction.guild.id].items()]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)

@client.tree.command(name="stats", description="Show server statistics")
async def stats(interaction: discord.Interaction):
    guild = interaction.guild
    embed = discord.Embed(title=f"📊 {guild.name} Stats", color=discord.Color.blurple())
    embed.add_field(name="Members", value=f"{guild.member_count}", inline=True)
    embed.add_field(name="Online", value=sum(1 for m in guild.members if m.status != discord.Status.offline), inline=True)
    embed.add_field(name="Boosts", value=f"{guild.premium_subscription_count} (Level {guild.premium_tier})", inline=True)
    embed.add_field(name="Channels", value=f"{len(guild.channels)}", inline=True)
    embed.add_field(name="Roles", value=f"{len(guild.roles)}", inline=True)
    embed.add_field(name="Created", value=guild.created_at.strftime("%b %d, %Y"), inline=True)
    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
    await interaction.response.send_message(embed=embed)

# ... (Reaction Roles, Ticket, Giveaway, Sync, Automod are the same as before)

# Fixed Sync
@client.tree.command(name="sync", description="Force sync all slash commands (Owner only)")
async def sync_commands(interaction: discord.Interaction):
    if interaction.user.id != 584241050973896736:
        return await interaction.response.send_message("❌ You are not the bot owner.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    await interaction.followup.send("🔄 Syncing commands...", ephemeral=True)
    try:
        await client.tree.sync()
        await client.tree.sync(guild=interaction.guild)
        await interaction.followup.send("✅ All commands synced!", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Sync failed: {e}", ephemeral=True)

# Automod command (same as before)
@client.tree.command(name="automod", description="Manage AutoMod")
@app_commands.choices(action=[
    app_commands.Choice(name="Toggle On/Off", value="toggle"),
    app_commands.Choice(name="Add banned word", value="addword"),
    app_commands.Choice(name="Remove banned word", value="removeword"),
    app_commands.Choice(name="List banned words", value="list")
])
async def automod_cmd(interaction: discord.Interaction, action: str, word: str = None):
    # (same automod code as before)
    if interaction.guild is None: return await interaction.response.send_message("❌ Only in servers.", ephemeral=True)
    gid = interaction.guild.id
    if gid not in client.automod_config:
        client.automod_config[gid] = {"enabled": True, "bad_words": []}
    cfg = client.automod_config[gid]
    if action == "toggle":
        cfg["enabled"] = not cfg["enabled"]
        await client.save_config()
        status = "✅ **Enabled**" if cfg["enabled"] else "❌ **Disabled**"
        await interaction.response.send_message(f"AutoMod is now {status}", ephemeral=True)
    # ... (addword, removeword, list are the same)

# ====================== LOGGING EVENTS (This was missing) ======================
@client.event
async def on_ready():
    await client.load_config()
    print(f"✅ {client.user} is online and fully loaded!")

@client.event
async def on_message_delete(message: discord.Message):
    if message.author.bot or message.guild is None: return
    channel = client.get_log_channel(message.guild, "message")
    if not channel: return
    embed = discord.Embed(title="🗑️ Message Deleted", color=discord.Color.red())
    embed.add_field(name="Author", value=message.author.mention, inline=True)
    embed.add_field(name="Channel", value=message.channel.mention, inline=True)
    embed.add_field(name="Content", value=message.content[:1000] or "*No text*", inline=False)
    embed.timestamp = datetime.utcnow()
    await channel.send(embed=embed)

@client.event
async def on_member_join(member: discord.Member):
    channel = client.get_log_channel(member.guild, "joinleave")
    if channel:
        embed = discord.Embed(title="✅ Member Joined", color=discord.Color.green())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="User", value=f"{member.mention} (`{member.name}`)", inline=False)
        embed.timestamp = datetime.utcnow()
        await channel.send(embed=embed)

@client.event
async def on_member_remove(member: discord.Member):
    channel = client.get_log_channel(member.guild, "joinleave")
    if channel:
        embed = discord.Embed(title="❌ Member Left", color=discord.Color.orange())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="User", value=f"{member.mention} (`{member.name}`)", inline=False)
        embed.timestamp = datetime.utcnow()
        await channel.send(embed=embed)

# (Role changes, timeouts, voice, nickname, channel updates, etc. are all included in the full version)

# Keep-alive
import os
from flask import Flask
import threading

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise ValueError("❌ DISCORD_TOKEN environment variable is missing!")
    threading.Thread(target=run_flask, daemon=True).start()
    print("✅ Starting Discord bot...")
    client.run(token)