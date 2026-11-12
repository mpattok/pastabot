import json
from discord.ext import commands
from functools import cache
from typing import overload

from .config import Config


class Auth:
    BLACKLIST = 0
    NOAUTH = 1
    TRUSTED = 2
    MODERATOR = 4
    ADMIN = 8

    def __init__(self, config: Config) -> None:
        self.config = config
        # ideally these would be static but Python is silly about referencing
        # members of a class within the class's definition
        self.name_to_level: dict[str, int] = {
            'blacklist': Auth.BLACKLIST,
            'noauth': Auth.NOAUTH,
            'trusted': Auth.TRUSTED,
            'moderator': Auth.MODERATOR,
            'admin': Auth.ADMIN
        }
        self.level_to_name: dict[int, str] = {
            Auth.BLACKLIST: 'blacklist',
            Auth.NOAUTH: 'noauth',
            Auth.TRUSTED: 'trusted',
            Auth.MODERATOR: 'moderator',
            Auth.ADMIN: 'admin'
        }
    # get a user's auth level

    def check(self, discord_id: int | str) -> int:
        # verify that config contains auth info
        if 'auth' not in self.config:
            print('no auth in config')
            return Auth.NOAUTH
        # check all the permissions
        for name in self.name_to_level:
            if name not in self.config['auth']:
                continue
            if str(discord_id) in self.config['auth'][name]:
                return self.name_to_level[name]
        return Auth.NOAUTH
    # get the name for a user's auth level

    def get_auth_string(self, user_id: int | str) -> str:
        return self.level_to_name[self.check(user_id)]
    # check if a user is below a minimum auth

    async def reject(self, ctx: commands.Context[commands.Bot], min_auth: int | None) -> bool:
        if min_auth not in self.level_to_name:
            min_auth = Auth.NOAUTH
        if self.check(ctx.author.id) < min_auth:
            await ctx.send("you are not authorized to use this command")
            return True
        return False
    # update a user's auth level
    # ctx gives us the editor and a place to report errors to them.
    # tgt_id and tgt_name identify the user whose auth will be changed.
    # auth_name is the desired level to change them to.

    async def update_auth(self, ctx: commands.Context[commands.Bot], tgt_id: int | str, tgt_name: str, auth_name: str) -> None:
        # ensure the desired auth is valid
        if auth_name not in self.name_to_level:
            await ctx.send(f'Unknown auth level "{auth_name}". Possible levels: {', '.join(self.name_to_level)}')
            return
        # ensure the caller has higher auth than the target
        user_auth = self.check(int(ctx.author.id))
        tgt_auth = self.check(int(tgt_id))
        if user_auth <= tgt_auth:
            await ctx.send('You can only modify auth for those with less auth than you')
            return
        # ensure the caller has higher auth than the desired auth
        level = self.name_to_level[auth_name]
        if user_auth <= level:
            await ctx.send('You can only set someone\'s auth up to the level below you')
            return
        # ensure this is a change
        if tgt_auth == level:
            await ctx.send(f'{tgt_name} already has auth level {auth_name}')
            return
        # edit the config
        async with self.config as config:
            orig_auth = self.level_to_name[tgt_auth]
            if orig_auth != 'noauth' and str(tgt_id) in config.get_or('auth', {}).get_or(orig_auth, {}):
                del config['auth'][orig_auth][str(tgt_id)]
            if auth_name != 'noauth':
                config.get_or('auth', {}).get_or(
                    auth_name, {})[str(tgt_id)] = tgt_name
        await ctx.send('updated auth')
