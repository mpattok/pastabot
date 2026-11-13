import datetime
import discord
from discord.ext import commands, tasks
import httpx
import requests
import time

from app import App, Auth, command


class GameInfo:
    def __init__(self, name, initial, final):
        self.name = name
        self.initial = initial
        self.final = final
        self.on_sale = final < initial
        self.percent = round(100 * (initial - final) / initial)

    def __str__(self):
        if self.on_sale:
            return f"{self.name} is {self.percent}% off (${self.initial/100} -> ${self.final/100})"
        return f"{self.name} is not on sale (${self.initial/100})"

    def __repr__(self):
        return f"GameInfo {{name={self.name}, initial={self.initial}, final={self.final}}}"

    @staticmethod
    def from_response(res, app_id):
        if res.status_code != 200:
            raise ValueError(f"Could not fetch game {app_id}")
        data = res.json()[str(app_id)]["data"]
        try:
            return GameInfo(
                data["name"],
                data["price_overview"]["initial"],
                data["price_overview"]["final"]
            )
        except Exception as e:
            raise ValueError(f"Couldn't get data for {app_id}: {e}")
    STEAM_URL = "https://store.steampowered.com/api/appdetails"

    @staticmethod
    def params(app_id):
        return {"appids": app_id, "cc": "us"}

    @staticmethod
    def fetch(app_id):
        res = requests.get(GameInfo.STEAM_URL, params=GameInfo.params(app_id))
        return GameInfo.from_response(res, app_id)

    @staticmethod
    async def fetch_async(app_id):
        async with httpx.AsyncClient() as client:
            res = await client.get(GameInfo.STEAM_URL, params=GameInfo.params(app_id))
        return GameInfo.from_response(res, app_id)


class Steam(commands.Cog):
    def __init__(self, app: App):
        self.app: App = app

    def get_record(self, author_id):
        try:
            return self.app.config['steam'][author_id]
        except:
            return None

    async def send_list(self, ctx) -> None:
        record = self.get_record(str(ctx.author.id))
        if record is None:
            await ctx.send('Not watching any games for you')
            return
        games = "\n".join(map(lambda app_id: f'- [{app_id}] {record[str(app_id)]['name'].value(str)}',
                              record.iter_value(str)))
        await self.app.buffer_send(ctx, f'Watching these games for you:\n{games}')

    @command(help='Add/remove a steam app to be notified of sales')
    async def steam(self, ctx, app_id=None) -> None:
        if app_id is None:
            await self.send_list(ctx)
            return
        async with self.app.config as config:
            user_id = str(ctx.author.id)
            if app_id in config.get_or('steam', {}).get_or(user_id, {}):
                name = config['steam'][user_id][app_id]['name'].value(str)
                await ctx.send(f'Will no longer watch {name} for you')
                del config['steam'][user_id][app_id]
                return
            try:
                info = await GameInfo.fetch_async(int(app_id))
                config['steam'][user_id][app_id] = {
                    'name': info.name,
                    'prev': info.final,
                    'channel': str(ctx.channel.id)
                }
                await ctx.send(f'Will watch {info.name} for you. Currently, {info}')
            except Exception as e:
                await ctx.send(f'steam: {e}')

    @tasks.loop(hours=4)
    async def check_sales(self, log: bool = True):
        if log:
            print(f'[{time.asctime()}] Checking steam sales')
        messages = {}
        if 'steam' not in self.app.config:
            return
        async with self.app.config as config:
            for user_id in config['steam'].iter_value(str):
                messages[user_id] = {'sale': {}, 'nosale': []}
                for app_id in config['steam'][user_id].iter_value(str):
                    info = await GameInfo.fetch_async(int(app_id))
                    prev = config['steam'][user_id][app_id]['prev'].value(int)
                    assert isinstance(prev, int)
                    if int(info.final) < prev:
                        notif_channel = config['steam'][user_id][app_id]['channel'].value(
                            str)
                        assert isinstance(notif_channel, str)
                        notif_channel = int(notif_channel)
                        if notif_channel in messages[user_id]['sale']:
                            messages[user_id]['sale'][notif_channel].append(
                                info)
                        else:
                            messages[user_id]['sale'][notif_channel] = [info]
                    else:
                        messages[user_id]['nosale'].append(str(info))
                    config['steam'][user_id][app_id]['time'] = str(
                        datetime.datetime.now())
                    config['steam'][user_id][app_id]['prev'] = info.final
                messages[user_id]['nosale'] = '\n'.join(
                    messages[user_id]['nosale'])

        async def ping_user(user_id, channel_id):
            msg = '\n'.join(map(str, messages[user_id]['sale'][channel_id]))
            channel = await self.app.bot.fetch_channel(channel_id)
            if channel is None or isinstance(channel, discord.abc.PrivateChannel):
                return msg
            assert isinstance(channel, discord.TextChannel) or isinstance(
                channel, discord.Thread)
            await channel.send(f'<@{user_id}>\n{msg}')
            return msg
        for user_id in messages:
            msg = '\n'.join([await ping_user(user_id, channel_id) for channel_id in messages[user_id]['sale']])
            messages[user_id]['sale'] = msg
            if msg != '':
                await self.app.send_dm(user_id, msg)
        if log:
            print(messages)
        return messages

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        self.check_sales.start()

    @command(help='Manually check Steam sales', auth=Auth.MODERATOR)
    async def steamdebug(self, ctx) -> None:
        messages = await self.check_sales()
        for user_id in messages:
            await ctx.send(f'To <@{user_id}>:\nSales:\n{messages[user_id]["sale"]}\nNo sales:\n{messages[user_id]["nosale"]}')
