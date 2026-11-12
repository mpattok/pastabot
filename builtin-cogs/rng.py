from discord.ext import commands
import random

from app import App, command


class RNG(commands.Cog):
    def __init__(self, app: App):
        self.app: App = app

    @command(help='Pick a random number from 1 to n')
    async def rng(self, ctx, n):
        try:
            n = int(n)
            assert n > 1
        except:
            n = 10
        await ctx.send(f'Picking a random number from 1 to {n}...')
        random.seed()
        x = random.randint(1, n)
        await ctx.send(f'Chose {x}')

    @command(help='Randomly decide between a comma-separated list of options')
    async def choose(self, ctx, *choices):
        try:
            random.seed()
            choices = ' '.join(choices).split(',')
            x = random.choice(choices)
            await ctx.send(f'Chose {x.strip()}')
        except Exception as e:
            await ctx.send(f'rng.choose: {e}')
