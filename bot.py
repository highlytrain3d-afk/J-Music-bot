#!/usr/bin/env python3
"""
Discord Music Bot (prefix: J/)

Features
- Play from YouTube & YouTube Music URLs or search terms (uses yt-dlp + FFmpeg)
- Queue, playlists, skip, pause/resume, stop/clear, leave, now playing
- Per-server player with a background consumer task
- Friendly error handling + helpful messages

IMPORTANT
- Create a **bot** application in the Discord Developer Portal and add it to your server.
  Do NOT log in with a user account (self-bots violate Discord ToS).
- Set an environment variable DISCORD_TOKEN with your bot token before running.
- Install system FFmpeg and Python deps listed below.

Quick start
  1) Install FFmpeg on your system so it’s on PATH.
  2) pip install -U discord.py yt-dlp PyNaCl
  3) export DISCORD_TOKEN=YOUR_TOKEN_HERE  (or set in .env)
  4) python bot.py
"""

import asyncio
import os
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

import discord
from discord.ext import commands

PREFIX = "J/"
INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.guilds = True
INTENTS.voice_states = True

YTDL_OPTS: Dict[str, Any] = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}

FFMPEG_BEFORE_OPTS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
FFMPEG_OPTS = "-vn"

@dataclass
class Track:
    title: str
    url: str
    stream_url: str
    requester_id: int

    @classmethod
    async def create(cls, query: str, requester_id: int) -> "Track":
        import yt_dlp
        ydl_opts = YTDL_OPTS.copy()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=False)
        if "entries" in info:
            info = next((e for e in info["entries"] if e), None)
            if info is None:
                raise RuntimeError("No results found.")
        title = info.get("title") or "Unknown title"
        webpage_url = info.get("webpage_url") or info.get("url")
        stream_url = info.get("url")
        if not stream_url:
            fmts = info.get("formats") or []
            audio_fmts = [f for f in fmts if f.get("acodec") and f.get("vcodec") == "none" and f.get("url")]
            if not audio_fmts:
                raise RuntimeError("No audio stream found.")
            stream_url = sorted(audio_fmts, key=lambda f: f.get("abr") or 0, reverse=True)[0]["url"]
        return cls(title=title, url=webpage_url, stream_url=stream_url, requester_id=requester_id)


class MusicPlayer:
    def __init__(self, bot: commands.Bot, guild: discord.Guild):
        self.bot = bot
        self.guild = guild
        self.queue: asyncio.Queue[Track] = asyncio.Queue()
        self.now_playing: Optional[Track] = None
        self._player_task: Optional[asyncio.Task] = None
        self._stopped = asyncio.Event()

    async def start(self):
        if self._player_task is None or self._player_task.done():
            self._stopped.clear()
            self._player_task = asyncio.create_task(self._player_loop())

    async def stop(self):
        self._stopped.set()
        if self.guild.voice_client and self.guild.voice_client.is_playing():
            self.guild.voice_client.stop()
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except asyncio.QueueEmpty:
                break
        if self._player_task:
            self._player_task.cancel()

    async def enqueue(self, track: Track):
        await self.queue.put(track)
        await self.start()

    async def _player_loop(self):
        while not self._stopped.is_set():
            try:
                track = await asyncio.wait_for(self.queue.get(), timeout=300)
            except asyncio.TimeoutError:
                vc = self.guild.voice_client
                if vc and not vc.is_playing():
                    await vc.disconnect(force=False)
                break
            self.now_playing = track
            vc = self.guild.voice_client
            if not vc or not vc.is_connected():
                self.queue.task_done()
                self.now_playing = None
                continue
            source = discord.FFmpegPCMAudio(
                track.stream_url,
                before_options=FFMPEG_BEFORE_OPTS,
                options=FFMPEG_OPTS,
            )
            vc.play(source, after=lambda e: self.bot.loop.call_soon_threadsafe(self.queue.task_done))
            while vc.is_playing() and not self._stopped.is_set():
                await asyncio.sleep(1)
            self.now_playing = None


bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS, help_command=None)
players: Dict[int, MusicPlayer] = {}


def get_player(guild: discord.Guild) -> MusicPlayer:
    player = players.get(guild.id)
    if not player:
        player = MusicPlayer(bot, guild)
        players[guild.id] = player
    return player


async def ensure_voice(ctx: commands.Context) -> Optional[discord.VoiceClient]:
    if ctx.author.voice is None or ctx.author.voice.channel is None:
        await ctx.reply("You need to be in a voice channel first.")
        return None
    channel = ctx.author.voice.channel
    if ctx.voice_client is None:
        try:
            vc = await channel.connect(self_deaf=True)
        except discord.ClientException:
            await ctx.reply("I couldn't connect to the voice channel.")
            return None
        return vc
    else:
        if ctx.voice_client.channel != channel:
            try:
                await ctx.voice_client.move_to(channel)
            except discord.ClientException:
                await ctx.reply("I couldn't move to your voice channel.")
                return None
        return ctx.voice_client


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")


@bot.command(name="help")
async def help_cmd(ctx: commands.Context):
    msg = (
        "**Commands (prefix: J/)**\n"
        "J/join — join your voice channel\n"
        "J/play <url or search> — queue a song (YouTube or YouTube Music)\n"
        "J/playlist <playlist_url> — queue an entire YouTube playlist\n"
        "J/queue — show queued tracks\n"
        "J/np — show now playing\n"
        "J/skip — skip current track\n"
        "J/pause — pause playback\n"
        "J/resume — resume playback\n"
        "J/stop — stop and clear queue\n"
        "J/leave — disconnect from voice\n"
    )
    await ctx.reply(msg)


@bot.command(name="join")
async def join_cmd(ctx: commands.Context):
    vc = await ensure_voice(ctx)
    if vc:
        await ctx.reply(f"Joined **{vc.channel.name}**.")
        await get_player(ctx.guild).start()


@bot.command(name="leave")
async def leave_cmd(ctx: commands.Context):
    if ctx.voice_client:
        await ctx.voice_client.disconnect(force=False)
        await ctx.reply("Left the voice channel.")
    else:
        await ctx.reply("I'm not in a voice channel.")


@bot.command(name="play")
async def play_cmd(ctx: commands.Context, *, query: str):
    vc = await ensure_voice(ctx)
    if not vc:
        return
    async with ctx.typing():
        try:
            track = await Track.create(query, requester_id=ctx.author.id)
        except Exception as e:
            await ctx.reply(f"Couldn't resolve that track: {e}")
            return
    player = get_player(ctx.guild)
    await player.enqueue(track)
    await ctx.reply(f"Queued **{track.title}** — <{track.url}>")


@bot.command(name="playlist")
async def playlist_cmd(ctx: commands.Context, playlist_url: str):
    vc = await ensure_voice(ctx)
    if not vc:
        return
    async with ctx.typing():
        try:
            import yt_dlp
            ydl_opts = YTDL_OPTS.copy()
            ydl_opts["noplaylist"] = False
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(playlist_url, download=False)
            if "entries" not in info:
                await ctx.reply("That doesn't look like a playlist.")
                return
            entries = [e for e in info["entries"] if e]
        except Exception as e:
            await ctx.reply(f"Couldn't fetch playlist: {e}")
            return
    player = get_player(ctx.guild)
    added = 0
    for ent in entries:
        try:
            title = ent.get("title") or "Unknown title"
            webpage_url = ent.get("webpage_url") or ent.get("url")
            if "url" in ent and ent.get("vcodec") == "none":
                stream_url = ent["url"]
            else:
                t = await Track.create(webpage_url, requester_id=ctx.author.id)
                stream_url = t.stream_url
            track = Track(title=title, url=webpage_url, stream_url=stream_url, requester_id=ctx.author.id)
            await player.enqueue(track)
            added += 1
        except Exception:
            continue
    await ctx.reply(f"Queued **{added}** tracks from the playlist.")


@bot.command(name="queue")
async def queue_cmd(ctx: commands.Context):
    player = get_player(ctx.guild)
    items: List[Track] = []
    try:
        size = player.queue.qsize()
        for _ in range(size):
            t = await player.queue.get()
            items.append(t)
            player.queue.put_nowait(t)
    except Exception:
        pass
    if not items:
        await ctx.reply("The queue is empty.")
        return
    lines = [f"{i+1}. {t.title}" for i, t in enumerate(items[:15])]
    more = "" if len(items) <= 15 else f"\n…and {len(items)-15} more"
    await ctx.reply("**Queue:**\n" + "\n".join(lines) + more)


@bot.command(name="np")
async def now_playing_cmd(ctx: commands.Context):
    player = get_player(ctx.guild)
    if player.now_playing:
        await ctx.reply(f"Now playing: **{player.now_playing.title}** — <{player.now_playing.url}>")
    else:
        await ctx.reply("Nothing is playing right now.")


@bot.command(name="skip")
async def skip_cmd(ctx: commands.Context):
    vc = ctx.voice_client
    if vc and vc.is_playing():
        vc.stop()
        await ctx.reply("Skipped.")
    else:
        await ctx.reply("Nothing to skip.")


@bot.command(name="pause")
async def pause_cmd(ctx: commands.Context):
    vc = ctx.voice_client
    if vc and vc.is_playing():
        vc.pause()
        await ctx.reply("Paused.")
    else:
        await ctx.reply("Nothing is playing.")


@bot.command(name="resume")
async def resume_cmd(ctx: commands.Context):
    vc = ctx.voice_client
    if vc and vc.is_paused():
        vc.resume()
        await ctx.reply("Resumed.")
    else:
        await ctx.reply("Nothing is paused.")


@bot.command(name="stop")
async def stop_cmd(ctx: commands.Context):
    player = get_player(ctx.guild)
    await player.stop()
    await ctx.reply("Stopped and cleared the queue.")


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("Please set the DISCORD_TOKEN environment variable.")
    bot.run(token)