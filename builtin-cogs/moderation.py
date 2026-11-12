from discord.ext import commands
import os
import subprocess
import sys
import time

from app import App, Auth, command


class Moderation(commands.Cog):
    def __init__(self, app: App):
        self.app: App = app
        self.muted = {}

    @command(help='Set a user\'s auth level. Your auth must be higher than theirs and the indicated level')
    async def auth(self, ctx, tgt_id, tgt_auth=None):
        if tgt_auth is None:
            await ctx.send(self.app.auth.get_auth_string(tgt_id))
            return
        tgt_user = await self.app.bot.fetch_user(int(tgt_id))
        await self.app.auth.update_auth(ctx, tgt_id, str(tgt_user), tgt_auth)

    @command(auth=Auth.MODERATOR)
    async def delete(self, ctx, *msg_ids):
        for msg_id in msg_ids:
            try:
                msg = await ctx.fetch_message(msg_id)
                await ctx.message.delete()
                await msg.delete()
            except Exception as e:
                await ctx.send(f'moderation.delete: {e}')

    @command(help='Reset pastabot', auth=Auth.TRUSTED)
    async def reset(self, ctx):
        await ctx.send('Resetting...')
        cmd = ['python3'] + sys.argv
        try:
            os.execv(sys.executable, cmd)
        except Exception as e:
            await ctx.send(f'moderation.reset: {e}')

    @command(help='Automatically delete a user\'s messages for 10 minutes', auth=Auth.MODERATOR)
    async def mute(self, ctx, user_id):
        async with self.app.config as config:
            config.get_or('muted', {}).get_or(user_id, {})[
                str(ctx.channel.id)] = int(time.time())

    @command(help='Stop deleting a user\'s messages', auth=Auth.MODERATOR)
    async def unmute(self, ctx, user_id):
        if 'muted' not in self.app.config:
            return
        if user_id not in self.app.config['muted']:
            return
        if str(ctx.channel.id) not in self.app.config['muted'][user_id]:
            return
        async with self.app.config as config:
            del config['muted'][user_id][str(ctx.channel.id)]

    def is_muted(self, user_id, channel_id):
        if 'muted' not in self.app.config:
            return False
        if user_id not in self.app.config['muted']:
            return False
        if channel_id not in self.app.config['muted'][user_id]:
            return False
        return time.time() - self.app.config['muted'][user_id][channel_id].value(int) < 10*60

    @commands.Cog.listener()
    async def on_message(self, msg):
        if self.is_muted(str(msg.author.id), str(msg.channel.id)):
            try:
                await msg.delete()
            except Exception as e:
                print(f'moderation.on_message: {e}')
