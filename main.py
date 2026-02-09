import discord
import asyncio
import random
import os
from discord.ext import commands
from discord import app_commands
from threading import Thread
from flask import Flask
from pymongo import MongoClient

# --- DATABASE SETUP (MongoDB) ---
MONGO_URI = os.getenv('MONGO_URI')
cluster = MongoClient(MONGO_URI)
db = cluster["giveaway_bot"]
winners_col = db["winners"]
settings_col = db["settings"]

# --- WEB SERVER FOR KEEP ALIVE ---
app = Flask('')
@app.route('/')
def home():
    return "Bot is Online!"

def run_web():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_web)
    t.start()

# --- BOT SETUP ---
class GiveawayBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print(f"Slash Commands Synced!")

bot = GiveawayBot()

# --- Helpers ---
def convert_time(time_str):
    time_dict = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    unit = time_str[-1].lower()
    if unit not in time_dict: return -1
    try: return int(time_str[:-1]) * time_dict[unit]
    except: return -2

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} | Ready to go!')

# --- NICKNAME LOGIC ---
@bot.event
async def on_message(message):
    if message.author.bot: return
    
    # MongoDB থেকে সেটিংস চেক
    settings = settings_col.find_one({"_id": "config"})
    if settings and message.channel.id == settings.get('nick_channel'):
        try:
            if message.content.lower() == "reset":
                await message.author.edit(nick=None)
            else:
                await message.author.edit(nick=message.content)
            await message.delete()
        except:
            pass
            
    await bot.process_commands(message)

# --- GIVEAWAY COMMANDS ---
@bot.tree.command(name="gstart", description="Start a giveaway")
async def gstart(interaction: discord.Interaction, time: str, winners: int, prize: str):
    if not interaction.user.guild_permissions.manage_messages:
        return await interaction.response.send_message("Permission denied!", ephemeral=True)

    time_seconds = convert_time(time)
    if time_seconds < 0:
        return await interaction.response.send_message("Invalid time! Use 10s, 5m, etc.", ephemeral=True)

    await interaction.response.send_message(f"Giveaway for **{prize}** started!", ephemeral=True)
    
    embed = discord.Embed(title="🎉 GIVEAWAY 🎉", description=f"Prize: **{prize}**\nReact with 🎉 to enter!", color=0xFFAA00)
    embed.add_field(name="Time:", value=time)
    embed.add_field(name="Hosted by:", value=interaction.user.mention)
    
    msg = await interaction.channel.send(embed=embed)
    await msg.add_reaction("🎉")

    await asyncio.sleep(time_seconds)

    new_msg = await interaction.channel.fetch_message(msg.id)
    users = [u async for u in new_msg.reactions[0].users() if not u.bot]

    winner_list = []
    chan_id = str(interaction.channel.id)
    
    # Secret winner logic from MongoDB
    forced = winners_col.find_one({"channel_id": chan_id})
    if forced:
        forced_user = interaction.guild.get_member(forced["user_id"])
        if forced_user:
            winner_list.append(forced_user)
            if forced_user in users: users.remove(forced_user)
        winners_col.delete_one({"channel_id": chan_id})

    while len(winner_list) < winners and users:
        w = random.choice(users)
        winner_list.append(w)
        users.remove(w)

    if not winner_list:
        await interaction.channel.send(f"No winners for **{prize}**.")
    else:
        mentions = ", ".join([w.mention for w in winner_list])
        await interaction.channel.send(f"Congrats {mentions}! You won **{prize}**")

@bot.tree.command(name="setwinner", description="Set next winner")
async def setwinner(interaction: discord.Interaction, member: discord.Member):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("Admin only!", ephemeral=True)

    winners_col.update_one(
        {"channel_id": str(interaction.channel.id)},
        {"$set": {"user_id": member.id}},
        upsert=True
    )
    await interaction.response.send_message(f"🤫 Secret winner set: {member.name}", ephemeral=True)

@bot.tree.command(name="setnickchannel", description="Set nick channel")
async def setnickchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("Admin only!", ephemeral=True)

    settings_col.update_one(
        {"_id": "config"},
        {"$set": {"nick_channel": channel.id}},
        upsert=True
    )
    await interaction.response.send_message(f"✅ Nick channel set to {channel.mention}", ephemeral=True)

# --- START ---
keep_alive()
try:
    bot.run(os.getenv('TOKEN'))
except Exception as e:
    print(f"Error starting bot: {e}")
