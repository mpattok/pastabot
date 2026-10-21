import asyncio
import discord
from discord.ext import commands
import dotenv
from functools import wraps
import importlib.util
import inspect
import os
from pathlib import Path
import requests
import sys
import time

from tools.auth import Auth
from tools.config import Config
from tools import musicq

class App:
    # basic infrastructure methods
    def __init__(self, *cog_dirs, enable_ip=True):
        self.config = Config('config.json', is_async=True)
        self.auth = Auth(self.config)
        self.musicq = musicq.Queue()
        self.ip = {'enabled': enable_ip, 'ip': None, 'time': 0, 'ttl': 3600}
        intents = discord.Intents.default()
        intents.message_content = True
        self.bot = commands.Bot(command_prefix='!', intents=intents)
        for cog_dir in cog_dirs: self.add_cogs(cog_dir)
    def run(self):
        token = self.get_token()
        if token is None:
            print('Could not get Discord token from config.json, .env, or environment')
            return
        self.bot.run(token)
    def get_token(self):
        if 'token' in self.config: return self.config['token']
        env = dotenv.dotenv_values('.env')
        if 'DISCORD_TOKEN' in env: return env['DISCORD_TOKEN']
        return os.getenv('DISCORD_TOKEN')
    def add_cogs(self, cog_dir):
        app_root = str(Path(__file__).resolve().parent)
        if app_root not in sys.path: sys.path.insert(0, app_root)
        end = 0
        for file in Path(cog_dir).glob('*.py'):
            if file.name.startswith('_'): continue
            try:
                name = file.name.replace(' ', '_') + f'_{end}'
                path = os.path.join(cog_dir, file.name)
                spec = importlib.util.spec_from_file_location(name, path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                for _, mod_class in inspect.getmembers(mod, inspect.isclass):
                    if not issubclass(mod_class, commands.Cog): continue
                    asyncio.run(self.bot.add_cog(mod_class(self)))
                end += 1
            except Exception as e:
                print(f'Failed to load {path}: {e}')
    # utilities for cogs
    async def connect_to_vc(self, ctx):
        vc = ctx.voice_client
        if vc is None:
            async with self.musicq.lock: 
                vc = await ctx.author.voice.channel.connect()
        return vc
    def get_ip(self):
        if not self.ip['enabled']: return 'IP not enabled'
        if self.ip['ip'] is None or time.time() - self.ip['time'] > self.ip['ttl']:
            self.ip['ip'] = requests.get('https://ipinfo.io/ip').content.decode()
            self.ip['time'] = time.time()
        return str(self.ip['ip'])
    async def send_dm(self, user_id, msg):
        user = await self.bot.fetch_user(int(user_id))
        channel = user.dm_channel or await self.bot.create_dm(user)
        await channel.send(msg)

def command(auth=None, *args, **kwargs):
    def decorator(cmd):
        @wraps(cmd)
        async def checked_command(self, ctx, *cmd_args):
            if await self.app.auth.verify(ctx, auth): return
            try: return await cmd(self, ctx, *cmd_args)
            except Exception as e: await ctx.send(f'{cmd.__name__}: {e}')
        return commands.command(*args, **kwargs)(checked_command)
    return decorator
