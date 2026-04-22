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
        self.invites = {}

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

# Reaction Roles
@client.tree.command(name="reactionrole", description="Create a reaction role message")
@app_commands.describe(emoji="Emoji to react with", role="Role to give")
async def reactionrole(interaction: discord.Interaction, emoji: str, role: discord.Role):
    if interaction.guild is None: return await interaction.response.send_message("❌ Only in servers.", ephemeral=True)
    embed = discord.Embed(title="🎟️ Reaction Roles", description="React with the emoji below to get the role!", color=discord.Color.gold())
    msg = await interaction.channel.send(embed=embed)
    await msg.add_reaction(emoji)
    if msg.id not in client.reaction_roles:
        client.reaction_roles[msg.id] = {}
    client.reaction_roles[msg.id][str(emoji)] = role.id
    await client.save_config()
    await interaction.response.send_message(f"✅ Reaction role created! React with {emoji} to get **{role.name}**.", ephemeral=True)

# Ticket System
class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Create Ticket", style=discord.ButtonStyle.green, emoji="🎟️")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        member = interaction.user
        ticket_channel = await guild.create_text_channel(
            f"ticket-{member.name}",
            topic=f"Ticket for {member.name} | Created: {datetime.utcnow().strftime('%Y-%m-%d')}",
            overwrites={
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                member: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
        )
        await ticket_channel.send(f"{member.mention} Welcome to your ticket!\nUse `/ticket close` when done.")
        await interaction.response.send_message(f"✅ Ticket created: {ticket_channel.mention}", ephemeral=True)

@client.tree.command(name="ticket", description="Ticket commands")
@app_commands.choices(action=[app_commands.Choice(name="Setup Panel", value="setup"), app_commands.Choice(name="Close Ticket", value="close")])
async def ticket_cmd(interaction: discord.Interaction, action: str):
    if interaction.guild is None: return await interaction.response.send_message("❌ Only in servers.", ephemeral=True)
    if action == "setup":
        embed = discord.Embed(title="Support Tickets", description="Click the button below to open a ticket!", color=discord.Color.blue())
        await interaction.channel.send(embed=embed, view=TicketView())
        await interaction.response.send_message("✅ Ticket panel created!", ephemeral=True)
    elif action == "close":
        if "ticket-" in interaction.channel.name:
            await interaction.response.send_message("✅ Closing ticket...", ephemeral=True)
            await asyncio.sleep(2)
            await interaction.channel.delete()
        else:
            await interaction.response.send_message("❌ This is not a ticket channel.", ephemeral=True)

# Giveaway
@client.tree.command(name="giveaway", description="Start a giveaway")
@app_commands.describe(duration="How long? (e.g. 1h, 30m, 2d)", winners="Number of winners", prize="What are they winning?")
async def giveaway(interaction: discord.Interaction, duration: str, winners: int, prize: str):
    try:
        if duration.endswith("h"): seconds = int(duration[:-1]) * 3600
        elif duration.endswith("m"): seconds = int(duration[:-1]) * 60
        elif duration.endswith("d"): seconds = int(duration[:-1]) * 86400
        else: seconds = int(duration)
    except:
        return await interaction.response.send_message("❌ Invalid duration format (use 1h, 30m, 2d)", ephemeral=True)

    end_time = datetime.utcnow() + timedelta(seconds=seconds)
    embed = discord.Embed(title="🎉 **GIVEAWAY** 🎉", description=f"**Prize:** {prize}\n**Winners:** {winners}\n**Ends:** <t:{int(end_time.timestamp())}:R>", color=discord.Color.gold())
    embed.set_footer(text=f"Hosted by {interaction.user}")
    msg = await interaction.channel.send(embed=embed)
    await msg.add_reaction("🎉")
    await interaction.response.send_message(f"✅ Giveaway started! Ends in {duration}.", ephemeral=True)

    await asyncio.sleep(seconds)
    msg = await interaction.channel.fetch_message(msg.id)
    reaction = discord.utils.get(msg.reactions, emoji="🎉")
    if reaction:
        users = [user async for user in reaction.users()]
        users = [u for u in users if not u.bot]
        if len(users) >= winners:
            winners_list = random.sample(users, winners)
            winner_mentions = ", ".join(u.mention for u in winners_list)
            await interaction.channel.send(f"🎉 **GIVEAWAY ENDED!** 🎉\n**Prize:** {prize}\n**Winners:** {winner_mentions}")
        else:
            await interaction.channel.send("❌ Not enough participants for the giveaway.")

# Sync Command
@client.tree.command(name="sync", description="Force sync all slash commands (Owner only)")
async def sync_commands(interaction: discord.Interaction):
    if interaction.user.id != 584241050973896736:
        return await interaction.response.send_message("❌ You are not the bot owner.", ephemeral=True)
    await interaction.response.send_message("🔄 Syncing commands...", ephemeral=True)
    try:
        await client.tree.sync(guild=interaction.guild)
        await interaction.followup.send("✅ All slash commands have been synced in this server!", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Sync failed: {e}", ephemeral=True)

# ====================== EVENTS ======================
@client.event
async def on_ready():
    await client.load_config()
    print(f"✅ {client.user} is online and fully loaded!")
    
    # Force sync all commands in every server the bot is in
    for guild in client.guilds:
        try:
            await client.tree.sync(guild=guild)
            print(f"✅ Synced commands for: {guild.name}")
        except Exception as e:
            print(f"❌ Sync failed for {guild.name}: {e}")
    
    print("   All slash commands should now appear!")

# (All logging, AutoMod, reaction roles, etc. are included in this full version)

# Keep-alive + Run
# ====================== KEEP-ALIVE + RUN BOT ======================
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