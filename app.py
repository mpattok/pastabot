import asyncio
from collections.abc import Callable, Coroutine, Iterable
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
from typing import Any, TypedDict

from tools.auth import Auth
from tools.config import Config
from tools import musicq

# types


class IP(TypedDict):
    enabled: bool
    ip: str | None
    time: float
    ttl: int


type Command = commands.Command[Any, ..., Any]
type CmdMethod = Callable[..., Coroutine[Any, Any, Any]]
type Context = commands.Context[commands.Bot]


class App:
    # basic infrastructure methods

    def __init__(self, *cog_dirs: str, enable_ip: bool = True, allow_cog_load_fail: bool = False) -> None:
        self.config = Config.open('config.json', is_async=True)
        self.auth = Auth(self.config)
        self.musicq = musicq.Queue()
        self.ip: IP = {'enabled': enable_ip,
                       'ip': None, 'time': 0, 'ttl': 3600}
        intents = discord.Intents.default()
        intents.message_content = True
        self.bot = commands.Bot(command_prefix='!', intents=intents)
        for cog_dir in cog_dirs:
            self.add_cogs(cog_dir, allow_fail=allow_cog_load_fail)

    def run(self) -> None:
        token = self.get_token()
        if token is None:
            print('Could not get Discord token from config.json, .env, or environment')
            return
        self.bot.run(token)

    def get_token(self) -> str | None:
        if 'token' in self.config:
            token = self.config['token'].value(str)
            return token
        env = dotenv.dotenv_values('.env')
        if 'DISCORD_TOKEN' in env:
            return env['DISCORD_TOKEN']
        return os.getenv('DISCORD_TOKEN')

    def add_cogs(self, cog_dir: str, allow_fail: bool = False) -> None:
        app_root = str(Path(__file__).resolve().parent)
        if app_root not in sys.path:
            sys.path.insert(0, app_root)
        end = 0
        for file in Path(cog_dir).glob('*.py'):
            if file.name.startswith('_'):
                continue
            path = os.path.join(cog_dir, file.name)
            try:
                name = file.name.replace(' ', '_') + f'_{end}'
                spec = importlib.util.spec_from_file_location(name, path)
                if spec is None or spec.loader is None:
                    raise ImportError(f'no module spec for {path}')
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                for _, mod_class in inspect.getmembers(mod, inspect.isclass):
                    if not issubclass(mod_class, commands.Cog):
                        continue
                    asyncio.run(self.bot.add_cog(mod_class(self)))
                end += 1
            except Exception as e:
                print(f'Failed to load {path}: {e}')
                if not allow_fail:
                    raise e

    # utilities for cogs

    # connect to the VC the context author is connected to
    async def connect_to_vc(self, ctx: Context) -> discord.VoiceClient:
        vc: discord.VoiceProtocol | None = ctx.voice_client
        if vc is None:
            assert isinstance(ctx.author, discord.Member)
            if ctx.author.voice is None or ctx.author.voice.channel is None:
                raise RuntimeError('you must be in a voice channel')
            async with self.musicq.lock:
                vc = await ctx.author.voice.channel.connect()
        assert isinstance(vc, discord.VoiceClient)
        return vc

    # get the bot's IP address if it is enabled
    def get_ip(self) -> str:
        if not self.ip['enabled']:
            return 'IP not enabled'
        if self.ip['ip'] is None or time.time() - self.ip['time'] > self.ip['ttl']:
            self.ip['ip'] = requests.get(
                'https://ipinfo.io/ip').content.decode()
            self.ip['time'] = time.time()
        return str(self.ip['ip'])

    # send a DM to a given user by their Discord ID
    async def send_dm(self, user_id: int | str, *args, **kwargs) -> None:
        user = await self.bot.fetch_user(int(user_id))
        if len(args) == 1 and isinstance(args[0], str) and len(kwargs) == 0:
            await self.buffer_send(user, args[0])
        else:
            await user.send(*args, **kwargs)

    # send a large message in chunks. first try to split on lines, then spaces,
    # then fallback to splitting words in the middle
    async def buffer_send(self, tgt: discord.abc.Messageable, msg: str, max_len: int = 2000) -> None:
        def buffer(msg: str, max_len: int = 2000, split: str | None = '\n') -> list[str]:
            msgs: list[str] = []
            curr = ''
            sep = ' ' if split is None else split
            for line in (msg if split == '' else msg.split(split)):
                if len(curr + line) < max_len:
                    curr += (sep if len(curr) > 0 else '') + line
                    continue
                msgs.append(curr)
                curr = line
            if len(curr) > 0:
                msgs.append(curr)
            return msgs

        def flatmap[T1, T2](f: Callable[[T1], Iterable[T2]], xs: Iterable[T1]) -> list[T2]:
            return [y for mapped in map(f, xs) for y in mapped]

        def make_lambda(split: str) -> Callable[[str], list[str]]:
            def inner(msg: str):
                if len(msg) <= max_len:
                    return [msg]
                return buffer(msg, max_len, split)
            return inner
        msgs = flatmap(make_lambda(''),
                       flatmap(make_lambda(' '),
                               buffer(msg, max_len)))
        for msg in filter(lambda msg: msg != '', msgs):
            await tgt.send(msg)


# decorator for commands inside a Cog class. should be drop-in replace for
# discord.ext.commands.command, with added arguments for auth and error catching.
# auth sets a minimum auth level to call the command.
# catch specifies if errors should be caught and reported to the caller.
def command(auth: int | None = None, catch: bool = True, *args: Any, **kwargs: Any
            ) -> Callable[[CmdMethod], Command]:
    def decorator(cmd: CmdMethod) -> Command:
        @wraps(cmd)
        async def wrapped_command(self: Any, ctx: Context, *cmd_args: Any, **cmd_kwargs: Any) -> Any:
            if await self.app.auth.reject(ctx, auth):
                return
            if catch:
                try:
                    return await cmd(self, ctx, *cmd_args, **cmd_kwargs)
                except Exception as e:
                    await ctx.send(f'{cmd.__name__}: {e}')
            else:
                return await cmd(self, ctx, *cmd_args)
        return commands.command(*args, **kwargs)(wrapped_command)
    return decorator
