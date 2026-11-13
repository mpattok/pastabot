from discord.ext import commands

from app import App, Auth, command
from tools.config import Config


class Watchlist(commands.Cog):
    def __init__(self, app: App):
        self.app: App = app

    async def add(self, item) -> None:
        async with self.app.config as config:
            config.get_or('watchlist', []).append(item)

    async def remove_item(self, item):
        async with self.app.config as config:
            if config.get_or('watchlist', []).remove(item):
                return item
            return None

    async def remove_index(self, i):
        async with self.app.config as config:
            watchlist = config.get_or('watchlist', [])
            if i < 1 or i > len(watchlist):
                return None
            item = watchlist[i - 1].value(str)
            del watchlist[i - 1]
            return item

    async def ls(self, ctx) -> None:
        lines = self.app.config['watchlist'] if 'watchlist' in self.app.config else [
        ]
        if len(lines) == 0:
            await ctx.send('The watchlist is empty')
            return
        i = 1
        buf = ''
        assert isinstance(lines, Config)
        for item in lines.iter_value(str):
            new_buf = buf + f'\n{i}. {item}' if i > 1 else f'{i}. {item}'
            if len(new_buf) > 2000:
                await ctx.send(buf)
                buf = f'{i}. {item}'
            else:
                buf = new_buf
            i += 1
        await ctx.send(buf)

    @command(help='Show watch list, or provide an item to add')
    async def watch(self, ctx, *item):
        item = ' '.join(item).strip()
        if item == '':
            return await self.ls(ctx)
        if await self.app.auth.reject(ctx, Auth.TRUSTED):
            return
        await self.add(item)
        await ctx.send(f'Added {item} to watchlist')

    @command(help='Remove an item from the watch list by its name or index', auth=Auth.TRUSTED)
    async def watched(self, ctx, *item) -> None:
        item = ' '.join(item).strip()
        by_item = await self.remove_item(item)
        if by_item is not None:
            await ctx.send(f'Removed {by_item} from watchlist')
            return
        try:
            by_index = await self.remove_index(int(item))
            if by_index is not None:
                await ctx.send(f'Removed {by_index} from watchlist')
                return
        except:
            pass
        await ctx.send(f'Could not find {item} on watchlist. Try !watch to see the list')
