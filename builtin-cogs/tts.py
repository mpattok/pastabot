import asyncio
from discord.ext import commands
from gtts import gTTS
import os
from piper import PiperVoice
import re
import subprocess
import time
import wave

from app import Auth, command

def timeit(f, *args, **kwargs):
    t0 = time.time()
    x = f(*args, **kwargs)
    t1 = time.time()
    return x, t1 - t0

def file_exists(path):
    try: os.rename(path, path)
    except: return False
    return True

async def log_and_send(msg, ctx=None):
    print(msg)
    if ctx is not None: await ctx.send(msg)

# an LRU cache associating Piper TTS voice names to loaded voices
class PiperCache:
    class Node:
        def __init__(self, name, voice, nxt):
            self.name = name
            self.voice = voice
            self.prev = None
            self.nxt = nxt
    def __init__(self, cap=5):
        cap = max(cap, 0)
        self.cap = cap
        self.head = None
        self.tail = None
        self.map = {}
    def unlink(self, name, from_map=True):
        node = self.map[name]
        if node.prev: node.prev.nxt = node.nxt
        else: self.head = node.nxt
        if node.nxt: node.nxt.prev = node.prev
        else: self.tail = node.prev
        if from_map: del self.map[name]
        node.prev = None
        node.nxt = None
        return node
    def insert(self, name, voice):
        try:
            self.map[name].voice = voice
            self.touch(name)
            return
        except: pass
        if self.cap > 0 and len(self) >= self.cap: self.unlink(self.tail.name)
        node = PiperCache.Node(name, voice, self.head)
        self.head = node
        if node.nxt is None: self.tail = node
        self.map[name] = node
    def touch(self, name):
        node = self.unlink(name, from_map=False)
        node.nxt = self.head
        self.head = node
        if node.nxt is None: self.tail = node
    def __getitem__(self, name):
        self.touch(name)
        return self.map[name].voice
    def __setitem__(self, name, voice):
        self.insert(name, voice)
    def __len__(self):
        return len(self.map)
    def __delitem__(self, name):
        self.unlink(name)
    def __contains__(self, name):
        return name in self.map
    async def load(self, voice, ctx=None):
        if voice not in self:
            os.makedirs('piper', exist_ok=True)
            path = os.path.join('piper', f'{voice}.onxx')
            log_loading = True
            if not file_exists(path):
                log_loading = False
                await log_and_send(f'Downloading Piper voice {voice}...', ctx)
                _, t = timeit(subprocess.run, ['python3', '-m', 'piper.donwload_voices',
                                               '--download-dir', 'piper', voice])
                if not file_exists(path):
                    raise ValueError(f'Failed to download Piper voice {voice} (took {t:.2f}s)')
                await log_and_send(f'Downloading Piper voice {voice} took {t:.2f}s. Loading it...', ctx)
            if log_loading: await log_and_send(f'Loading piper voice {voice}...', ctx)
            cache[voice], t = timeit(PiperVoice.load, path)
            await log_and_send(f'Loading piper voice {voice} took {t:.2f}s', ctx)
        return self[voice]

async def generate(speech, msgid, lang='en', tld='co.uk', voices=None, ctx=None):
    os.makedirs(f'tts/{msgid}', exist_ok=True)
    def gen_with_args(use_lang, use_tld):
        try:
            if use_lang and use_tld:
                gTTS(speech, lang=lang, tld=tld).save(f"tts/{msgid}/{msgid}.mp3")
            elif use_lang:
                gTTS(speech, lang=lang, tld='co.uk').save(f"tts/{msgid}/{msgid}.mp3")
            elif use_tld:
                gTTS(speech, lang='en', tld=tld).save(f"tts/{msgid}/{msgid}.mp3")
            else:
                gTTS(speech, lang='en', tld='co.uk').save(f"tts/{msgid}/{msgid}.mp3")
            return (f"{msgid}.mp3", f"tts/{msgid}")
        except: 
            if use_lang and use_tld:
                return gen_with_args(True, False)
            elif use_lang: 
                return gen_with_args(False, True)
            elif use_tld: 
                return gen_with_args(False, False)
            else:
                try: 
                    gTTS('nonempty', lang='en', tld='co.uk').save(f'tts/{msgid}/{msgid}.mp3')
                    return None, None
                except:
                    raise ValueError(f'Cannot generate speech for "{speech}" with tld={tld}, lang={lang}')
    if tld != 'piper': return gen_with_args(True, True)
    if voices is None: raise ValueError("Can't generate Piper voice without Piper voice cache")
    voice = await voices.load(lang, ctx)
    with wave.open(f'tts/{msgid}/{msgid}.wav', 'wb') as wav_file:
        voice.synthesize_wav(speech, wav_file)
    return (f'{msgid}.wav', f'tts/{msgid}')

def clean_msg(msg):
    ignore = ["!", "http", ":", "<"]
    keep_capital = ["AI", "VR", "NHS"]
    def map_word(word):
        if True in map(lambda x: word.startswith(x), ignore): return ''
        if word == word.upper() and word not in keep_capital: return word.lower()
        return word
    return ' '.join(map(map_word, re.split('() ', msg)))

class TTS(commands.Cog):
    def __init__(self, app):
        self.app = app
        self.voices = PiperCache()
    async def speak(self, ctx, filename, filedir):
        if filename is None or filedir is None: return
        try:
            vc = await self.app.connect_to_vc(ctx)
            async with self.app.musicq.lock:
                self.app.musicq.add(f'{filedir}/{filename}', dir_to_rm=filedir, vc=vc, track=1)
        except Exception as e:
            await ctx.send(f'tts.speak: {e}')
    async def add_tts(self, ctx, user_id, tld, lang):
        async with self.app.config as config:
            config.get_or('tts', {}).get_or(str(user_id), {})[str(ctx.channel.id)] = {'tld': tld, 'lang': lang}
    async def remove_tts(self, ctx, user_id):
        async with self.app.config as config:
            if 'tts' not in config: return
            if str(user_id) not in config['tts']: return
            if str(ctx.channel.id) not in config['tts'][str(user_id)]: return
            del config['tts'][str(user_id)][str(ctx.channel.id)]
    @command(help='Activate TTS. For yourself, use !tts [tld (e.g. us or co.uk)] [lang (e.g. en)]. Default is co.uk en', auth=Auth.TRUSTED)
    async def tts(self, ctx, user_id=None, tld=None, lang=None):
        if lang is None and user_id is not None and len(user_id) < 8: lang, tld, user_id = tld, user_id, None
        if user_id is None: user_id = str(ctx.author.id)
        if tld is None: tld = "co.uk"
        if lang is None: lang = 'en'
        if user_id != str(ctx.author.id) and await self.app.auth.verify(ctx, auth.MODERATOR): return
        await self.remove_tts(ctx, user_id)
        await self.add_tts(ctx, user_id, tld, lang)
    @command(help='Deactivate TTS')
    async def notts(self, ctx, user_id=None):
        if user_id is None: user_id = str(ctx.author.id)
        if user_id != str(ctx.author.id) and await self.app.auth.verify(ctx, Auth.MODERATOR):
            return
        await self.remove_tts(ctx, user_id)
    @command(help='Get list of TLDs for TTS')
    async def vtts(self, ctx):
        await ctx.send("""Available tts accents:
Australia - com.au
United Kingdom - co.uk
United States - us
Canada - ca
India - co.in
Ireland ie
South Africa - co.za
Nigeria - com.ng""")
    @command(help='Check if you have TTS on in this channel')
    async def checktts(self, ctx):
        try:
            entry = self.app.config['tts'][str(ctx.author.id)][str(ctx.channel.id)].json
            await ctx.send(f'You have TTS on: {entry}')
        except: await ctx.send('You do not have TTS on in this channel')
    @command(help='Show info on using Piper TTS')
    async def piper(self, ctx):
        msg = '''To use a piper voice, use `!tts piper [voice code]`.
        You can get voice codes from https://rhasspy.github.io/piper-samples
        (choose parameters and copy the code, which looks like en_US-amy-medium'''
        await ctx.send(msg)
    @commands.Cog.listener()
    async def on_message(self, msg):
        ctx = await self.app.bot.get_context(msg)
        try: entry = self.app.config['tts'][str(ctx.author.id)][str(ctx.channel.id)].json
        except: return
        if msg.content.startswith("!"): return
        content = clean_msg(msg.content.replace('(', ' ').replace(')', ' ').replace('https', ' https'))
        if content.strip() == '': return
        filename, filedir = await generate(content, str(msg.id), entry['lang'], entry['tld'], self.voices, ctx)
        await self.speak(ctx, filename, filedir)
        async with self.app.config as config:
            config['tts'][str(ctx.author.id)][str(ctx.channel.id)]['time'] = str(int(time.time()))
    @commands.Cog.listener()
    async def on_ready(self):
        try: tts = self.app.config['tts']
        except: return
        to_load = {}
        for user in tts:
            entries = tts[user]
            for channel in entries:
                entry = entries[channel]
                if entry['tld'] != 'piper': continue
                if 'time' not in entry: continue
                voice = entry['lang']
                t = int(entry['time'])
                if voice in to_load: to_load[voice] = max(to_load[voice], t)
                else: to_load[voice] = t
        to_load_sorted = sorted(list(to_load), key=lambda voice: to_load[voice], reverse=True)
        if self.voices.cap > 0: to_load_sorted = to_load_sorted[:self.voices.cap]
        for voice in to_load_sorted:
            self.voices[voice] = await self.voices.load(voice)
