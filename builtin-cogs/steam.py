import datetime
import discord
from discord.ext import commands, tasks
import httpx
import requests
import time

from app import Auth, command

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
        if res.status_code != 200: raise ValueError(f"Could not fetch game {app_id}")
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
    def __init__(self, app):
        self.app = app
    def get_record(self, author_id):
        try: return self.app.config['steam'][author_id]
        except: return None
    async def send_list(self, ctx):
        record = self.get_record(str(ctx.author.id))
        if record is None:
            await ctx.send('Not watching any games for you')
            return
        games = "\n".join(map(lambda app_id: f'[{app_id}] {record[app_id]['name']}', record))
        await self.app.buffer_send(ctx, f'Watching these games for you:\n{games}')
    @command(help='Add/remove a steam app to be notified of sales')
    async def steam(self, ctx, app_id=None):
        if app_id is None:
            await self.send_list(ctx)
            return
        async with self.app.config as config:
            user_id = str(ctx.author.id)
            if app_id in config.get_or('steam', {}).get_or(user_id, {}):
                name = config['steam'][user_id][app_id]['name']
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
            except Exception as e: await ctx.send(f'steam: {e}')
    @tasks.loop(hours=4)
    async def check_sales(self):
        print(f'[{time.asctime()}] Checking steam sales')
        messages = {}
        if 'steam' not in self.app.config: return
        async with self.app.config as config:
            for user_id in config["steam"]:
                messages[user_id] = {'sale': '', 'nosale': []}
                sales = {}
                for app_id in config["steam"][user_id]:
                    try:
                        info = await GameInfo.fetch_async(int(app_id))
                        if int(info.final) < int(config["steam"][user_id][app_id]["prev"]):
                            notif_channel = int(config["steam"][user_id][app_id]["channel"])
                            if notif_channel in sales: sales[notif_channel].append(info)
                            else: sales[notif_channel] = [info]
                        else: messages[user_id]['nosale'].append(info)
                        config["steam"][user_id][app_id]["time"] = str(datetime.datetime.now())
                        config["steam"][user_id][app_id]["prev"] = info.final
                    except: pass
                messages[user_id]['nosale'] = '\n'.join(map(str, messages[user_id]['nosale']))
                if len(sales) == 0: continue
                async def ping_user(channel_id):
                    msg = "\n".join(map(str, sales[channel_id]))
                    channel = await self.app.bot.fetch_channel(channel_id)
                    if channel is None or channel.type == discord.ChannelType.private:
                        return msg
                    await channel.send(f"<@{user_id}>\n{msg}")
                    return msg
                user = await self.app.bot.fetch_user(int(user_id))
                channel = user.dm_channel
                if channel is None: channel = await self.app.bot.create_dm(user)
                msg = "\n".join([await ping_user(channel_id) for channel_id in sales])
                await channel.send(msg)
                messages[user_id]['sale'] = msg
                # await channel.send("\n".join(map(str, sales)))
        print(messages)
        return messages
    @commands.Cog.listener()
    async def on_ready(self):
        self.check_sales.start()
    @command(help='Manually check Steam sales', auth=Auth.MODERATOR)
    async def steamdebug(self, ctx):
        messages = await self.check_sales()
        for user_id in messages:
            await ctx.send(f'To <@{user_id}>:\nSales:\n{messages[user_id]["sale"]}\nNo sales:\n{messages[user_id]["nosale"]}')
