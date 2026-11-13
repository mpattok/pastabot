from Crypto.Util.Padding import pad, unpad
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from discord.ext import commands
import hashlib

from app import App, command


def hash(txt):
    m = hashlib.sha256()
    m.update(txt.encode())
    return m.hexdigest()


def encrypt(msg, key):
    key = hash(key).encode()[:16]
    iv = get_random_bytes(16)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    ct = cipher.encrypt(pad(msg.encode(), 16))
    return iv.hex() + ct.hex()


def decrypt(ct, key):
    key = hash(key).encode()[:16]
    iv = bytes.fromhex(ct[:32])
    ct = bytes.fromhex(ct[32:])
    cipher = AES.new(key, AES.MODE_CBC, iv)
    padded = cipher.decrypt(ct)
    return unpad(padded, 16).decode()


class Cipher(commands.Cog):
    def __init__(self, app: App):
        self.app: App = app

    @command(help='Use a key to encrypt a message (AES)')
    async def encrypt(self, ctx, key, *, chars) -> None:
        msg = ''.join(chars)
        ct = encrypt(msg, key)
        await ctx.send(ct)

    @command(help='Use a key to decrypt a message')
    async def decrypt(self, ctx, key, ciphertext) -> None:
        pt = decrypt(ciphertext, key)
        await ctx.send(pt)
