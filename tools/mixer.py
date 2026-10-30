# this should be a drop-in replacement for discord.FFmpegPCMAudio,
# with the added mix_in method seen below in the Mixer class

import discord
import subprocess
import numpy as np
import threading
import time

# audio = 48K, 16-bit (2 bytes), dual channel
# frame = 20ms 
FRAME_SIZE = int(48000 * 2 * 2 * 20/1000)

# utility class for a stream
class FFmpegStream:
    def __init__(self, path, after=None, track=None):
        self.after = after
        self.track = track
        # get an ffmpeg stream of the source
        af = "volume=1.5" if track == 1 else "loudnorm"
        cmd = ["ffmpeg", "-i", path,
               "-f", "s16le", # signed 16-bit little-endian
               "-ar", "48000", # bitrate
               "-ac", "2", # dual channel
               "-filter:a", af, # normalize
               "pipe:1"] # send to pipe instead of file
        self.proc = subprocess.Popen(cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )
    def read(self): 
        # get frame of data
        data = self.proc.stdout.read(FRAME_SIZE)
        # cleanup if we read nothing
        if not data and self.after is not None:
            self.after()
            self.after = None
        return data
    def close(self):
        # clean up the ffmpeg stream
        if self.proc:
            self.proc.kill()
            self.proc = None

class Mixer(discord.AudioSource):
    def __init__(self, initial_path=None, after=None, track=None):
        self.sources = []
        self.lock = threading.Lock()
        if initial_path: self.mix_in(initial_path, after, track)
    # add a sound to the mixer
    def mix_in(self, path, after=None, track=None):
        stream = FFmpegStream(path, after, track)
        time.sleep(1)
        with self.lock: self.sources.append(stream)
    # used by discord to get a frame
    def read(self):
        with self.lock:
            # play nothing if no sources (keeps stream alive)
            if not self.sources:
                return b'\x00' * FRAME_SIZE
            # get each frame's chunks and update live sources
            chunks = []
            alive_sources = []
            for s in self.sources:
                data = s.read()
                if data:
                    chunks.append(data)
                    alive_sources.append(s)
                else:
                    s.close()
            self.sources = alive_sources
        # no chunks = no live sources. play nothing as before
        if not chunks:
            return b'\x00' * FRAME_SIZE
        # get chunks that are the right size
        padded = []
        for c in chunks:
            # ensure length = frame size
            if len(c) < FRAME_SIZE:
                c += b'\x00' * (FRAME_SIZE - len(c))  # pad
            padded.append(c)
        # combine the chunks
        mixed = np.zeros(FRAME_SIZE // 2, dtype=np.int32)
        for c in padded:
            mixed += np.frombuffer(c, dtype='<i2')
        return np.clip(mixed, -32768, 32767).astype('<i2').tobytes()
