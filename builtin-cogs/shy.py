import discord
from discord.ext import commands
import time

from app import App, Auth, command


class Shy(commands.Cog):
    def __init__(self, app: App):
        self.app: App = app
        self.notified_deafened = {}

    async def notify_deafened(self, channel, users):
        cid = int(channel.id)
        if cid in self.notified_deafened and time.time() - self.notified_deafened[cid] < 5:
            return
        self.notified_deafened[cid] = time.time()
        msg = f'people have been deafened because these shy users are unmuted: {', '.join(users)}'
        await channel.send(msg)

    def user_shy_data(self, user_id):
        if 'shy' not in self.app.config:
            return (False, [])
        if str(user_id) not in self.app.config['shy']:
            return (False, [])
        return (True, self.app.config['shy'][str(user_id)])

    def shy_user_here(self, channel, user_id):
        for member in channel.members:
            if str(user_id) == str(member.id):
                continue
            (shy, allowed) = self.user_shy_data(member.id)
            if not shy:
                continue
            if member.voice.self_mute or member.voice.mute:
                continue
            if str(user_id) in allowed:
                continue
            return str(member)
        return None

    async def maybe_deafen_vc(self, channel):
        if channel is None:
            return
        shy = set()
        deafen = set()
        for member in channel.members:
            deafen_for = self.shy_user_here(channel, member.id)
            if deafen_for is None:
                continue
            if not member.voice.deaf:
                shy.add(deafen_for)
            deafen.add(member.id)
        for member in channel.members:
            if member.voice.deaf != (member.id in deafen):
                await member.edit(deafen=(member.id in deafen))
        if len(shy) != 0:
            await self.notify_deafened(channel, shy)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        await self.maybe_deafen_vc(before.channel)
        if before.channel != after.channel:
            await self.maybe_deafen_vc(after.channel)

    @command(help='Register as shy, so that everyone in VC is deafened when you unmute', auth=Auth.TRUSTED)
    async def shy(self, ctx):
        async with self.app.config as config:
            config.get_or('shy', {}).get_or(str(ctx.author.id), [])
        await self.maybe_deafen_vc(ctx.channel)

    @command(help='Unregister as shy')
    async def notshy(self, ctx):
        if 'shy' not in self.app.config:
            return
        if str(ctx.author.id) not in self.app.config['shy']:
            return
        async with self.app.config as config:
            del config['shy'][str(ctx.author.id)]
        await self.maybe_deafen_vc(ctx.channel)

    @command(help='Allow a user to be undeafened when you are unmuted')
    async def allow(self, ctx, user_id):
        await self.shy(ctx)
        if str(user_id) in self.app.config['shy'][str(ctx.author.id)]:
            return
        async with self.app.config as config:
            config['shy'][str(ctx.author.id)].append(str(user_id))
        await self.maybe_deafen_vc(ctx.channel)

    @command(help='No longer allow a user to be undeafened when you are unmuted', auth=Auth.TRUSTED)
    async def disallow(self, ctx, user_id):
        async with self.app.config as config:
            config.get_or('shy', {}).get_or(
                str(ctx.author.id), []).remove(user_id)
        await self.maybe_deafen_vc(ctx.channel)
