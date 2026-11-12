from discord.ext import commands
import json
import os
from pathlib import Path

from app import App, Auth, command


class Sounds(commands.Cog):
    def __init__(self, app: App):
        self.app: App = app

    @command(help='Clear the sound queue')
    async def clear(self, ctx):
        self.app.musicq.clear()
        await ctx.send("cleared the queue")

    def get_sound(self, sound, root=None):
        sounds = self.app.config['sounds']['prefix'].value(str)
        if root is None:
            root = str(sounds)
        parts = sound.split('/')
        subdirs = []
        for f in sorted(os.listdir(root)):
            subpath = os.path.join(root, f)
            if Path(subpath).is_dir():
                if len(parts) > 1 and parts[0].lower() in f.lower():
                    sub = self.get_sound('/'.join(parts[1:]), subpath)
                    if sub is not None:
                        return sub
                subdirs.append(subpath)
                continue
            if sound.lower() in f.lower():
                return subpath
        for subdir in subdirs:
            sub = self.get_sound(sound, subdir)
            if sub is not None:
                return sub
        return None

    @command(help='Play a sound by its name/path')
    async def sound(self, ctx, *sound):
        sound = ' '.join(sound).strip()
        vc = await self.app.connect_to_vc(ctx)
        file = self.get_sound(sound)
        if file is None:
            await ctx.send('no such sound')
            return
        self.app.musicq.add(file, vc=vc)

    @command(help='Connect the bot to the VC you\'re in')
    async def join(self, ctx):
        await self.app.connect_to_vc(ctx)

    @command(help='Disconnect the bot from VC')
    async def leave(self, ctx):
        await ctx.voice_client.disconnect()

    @command(help='Stop the currently playing sound')
    async def stop(self, ctx, track: str | None = None):
        try:
            assert isinstance(track, str)
            track_no = int(track)
        except:
            track_no = None
        try:
            vc = ctx.guild.voice_client
            self.app.musicq.stop(vc, track_no)
        except Exception as e:
            await ctx.send(f'sounds.stop: {e}')

    def get_list(self, query, path: str | None = None):
        root = self.app.config["sounds"]["prefix"].value(str)
        if path is None:
            path = root
        parts = query.split('/')
        subdirs = []
        for f in sorted(os.listdir(path)):
            subpath = os.path.join(path, f)
            if not Path(subpath).is_dir():
                continue
            subdirs.append(subpath)
            if parts[0].lower() not in f.lower():
                continue
            if len(parts) > 1:
                sub = self.get_list("/".join(parts[1:]), subpath)
                if sub is not None:
                    return sub
                continue
            files = []
            dirs = []
            for f1 in sorted(os.listdir(subpath)):
                subsubpath = os.path.join(subpath, f1)
                name = subsubpath[(len(root) + 1):]
                if Path(subsubpath).is_dir():
                    dirs.append(name + "/")
                else:
                    files.append(name)
            return "\n".join(files + dirs)
        for subdir in subdirs:
            sub = self.get_list(query, subdir)
            if sub is not None:
                return sub
        return None

    @command(help='Get a list of sounds, optionally under a particular directory')
    async def sounds(self, ctx, query=None):
        if query is None:
            await ctx.send('sounds:')
            files = []
            dirs = []
            root = self.app.config['sounds']['prefix'].value(str)
            for path in sorted(os.listdir(root)):
                if Path(os.path.join(root, path)).is_dir():
                    dirs.append(path + '/')
                else:
                    files.append(path)
            await ctx.send('\n'.join(files + dirs))
            return
        res = self.get_list(query)
        if res is None:
            await ctx.send('No sounds found. Try with no arguments for root list')
        else:
            await ctx.send(f'{query} sounds:\n{res}')
