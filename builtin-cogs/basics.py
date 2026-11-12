import discord
from discord.ext import commands
import subprocess

from app import App, Auth, command


class Basics(commands.Cog):
    def __init__(self, app: App):
        self.app: App = app

    @commands.Cog.listener()
    async def on_ready(self):
        pasta_ip = self.app.get_ip()
        msg = f'{self.app.bot.user} is online ({pasta_ip})'
        try:
            for admin in self.app.config['auth']['admin'].iter_value(str):
                await self.app.send_dm(admin, msg)
        except Exception as e:
            print(f'basics.on_ready: {e}')
        print(msg)

    @command(help='Replies with "pong!"')
    async def ping(self, ctx):
        await ctx.send('pong!')

    @command(help='Replies with the bot\'s IP')
    async def ip(self, ctx):
        await ctx.send(self.app.get_ip())

    @command(help='Repeats what you say', auth=Auth.MODERATOR)
    async def echo(self, ctx, *content):
        await ctx.send(' '.join(content))

    @command(help='Sends a DM through the bot', auth=Auth.ADMIN)
    async def dm(self, ctx, user_id, *content):
        await self.app.send_dm(user_id, ' '.join(content))

    @command(help='Replies with the username associated with the given ID')
    async def find(self, ctx, discord_id):
        user = await self.app.bot.fetch_user(int(discord_id))
        await ctx.send(str(user))

    @command(help='Replies with the avatar associated with the given ID')
    async def avatar(self, ctx, discord_id):
        user = await self.app.bot.fetch_user(int(discord_id))
        url = user.display_avatar.url
        embed = discord.Embed(title=f'avatar: {user.name}')
        embed.set_image(url=url)
        await ctx.send(embed=embed)

    @command(help='Replies with your ID')
    async def whoami(self, ctx):
        await ctx.send(ctx.author.id)

    @command(help='Raises an exception. Used to test the command decorator error handling')
    async def throw(self, ctx, *msg):
        raise Exception(' '.join(msg))

    @command(auth=Auth.MODERATOR, help='Prints to the console. Used to test stdout logging')
    async def console(self, ctx, *msg):
        print(' '.join(msg), flush=True)
