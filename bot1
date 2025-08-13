import os
import asyncio
import discord
from discord.ext import commands, tasks
from discord import FFmpegPCMAudio
from yt_dlp import YoutubeDL
from fastapi import FastAPI
import uvicorn

# ---------- Environment Variables ----------
TOKEN = os.getenv("DISCORD_BOT_TOKEN")  # Your bot token here
PREFIX = os.getenv("DISCORD_BOT_PREFIX", "!")  # Default prefix: !

# ---------- Discord Bot Setup ----------
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# ---------- FastAPI Web App ----------
app = FastAPI()

@app.get("/")
async def home():
    return {"status": "Bot is running"}

# ---------- Music Player Variables ----------
music_queues = {}  # {guild_id: [song_url, ...]}
current_players = {}  # {guild_id: voice_client}

ydl_opts = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
}

ffmpeg_opts = {
    'options': '-vn'
}

# ---------- Helper Functions ----------
async def play_next(ctx, guild_id):
    queue = music_queues.get(guild_id)
    if not queue or len(queue) == 0:
        await ctx.send("Queue is empty. Leaving voice channel.")
        vc = current_players.get(guild_id)
        if vc:
            await vc.disconnect()
        return

    url = queue.pop(0)
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        audio_url = info['url']

    vc = current_players[guild_id]
    vc.play(FFmpegPCMAudio(audio_url, **ffmpeg_opts), after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx, guild_id), bot.loop))
    await ctx.send(f"Now playing: {info.get('title')}")

# ---------- Discord Bot Events ----------
@bot.event
async def on_ready():
    print(f"[DISCORD] Logged in as {bot.user}")

# ---------- Music Commands ----------
@bot.command()
async def join(ctx):
    if ctx.author.voice:
        channel = ctx.author.voice.channel
        try:
            vc = await channel.connect()
            current_players[ctx.guild.id] = vc
            await ctx.send(f"Joined {channel.name}")
        except discord.ClientException:
            await ctx.send("Already connected.")
    else:
        await ctx.send("You are not in a voice channel.")

@bot.command()
async def leave(ctx):
    vc = current_players.get(ctx.guild.id)
    if vc:
        await vc.disconnect()
        music_queues[ctx.guild.id] = []
        current_players.pop(ctx.guild.id)
        await ctx.send("Disconnected.")
    else:
        await ctx.send("Not connected to any voice channel.")

@bot.command()
async def play(ctx, *, url):
    guild_id = ctx.guild.id
    if guild_id not in music_queues:
        music_queues[guild_id] = []

    music_queues[guild_id].append(url)
    await ctx.send(f"Added to queue: {url}")

    vc = current_players.get(guild_id)
    if not vc:
        if ctx.author.voice:
            vc = await ctx.author.voice.channel.connect()
            current_players[guild_id] = vc
        else:
            await ctx.send("You need to be in a voice channel.")
            return

    if not vc.is_playing():
        await play_next(ctx, guild_id)

@bot.command()
async def skip(ctx):
    vc = current_players.get(ctx.guild.id)
    if vc and vc.is_playing():
        vc.stop()
        await ctx.send("Skipped current song.")
    else:
        await ctx.send("Nothing is playing.")

@bot.command()
async def stop(ctx):
    vc = current_players.get(ctx.guild.id)
    if vc:
        vc.stop()
        music_queues[ctx.guild.id] = []
        await ctx.send("Stopped playback and cleared queue.")
    else:
        await ctx.send("Nothing is playing.")

@bot.command()
async def queue(ctx):
    q = music_queues.get(ctx.guild.id, [])
    if not q:
        await ctx.send("Queue is empty.")
    else:
        msg = "\n".join([f"{i+1}. {song}" for i, song in enumerate(q)])
        await ctx.send(f"Current Queue:\n{msg}")

# ---------- FastAPI Startup Event ----------
@app.on_event("startup")
async def start_discord_bot():
    asyncio.create_task(bot.start(TOKEN))

# ---------- Run Web Server ----------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
