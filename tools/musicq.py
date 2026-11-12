import os
import asyncio
import discord
from .mixer import Mixer


class QueueItem:
    def __init__(self, path: str, dir_to_rm: str | None) -> None:
        self.path = path
        self.dir_to_rm = dir_to_rm

    def __str__(self) -> str:
        return f"{self.path}"

    def __repr__(self) -> str:
        return str(self)


class Queue:
    def __init__(self) -> None:
        self.qs: dict[int, list[QueueItem]] = {}
        self.mixer: Mixer | None = None
        self.active: set[int] = set()
        self.lock = asyncio.Lock()

    def is_empty(self, track: int = 0) -> bool:
        return track not in self.qs or len(self.qs[track]) == 0

    def all_empty(self) -> bool:
        return all(map(lambda k: len(self.qs[k]) == 0, self.qs))

    def length(self, track: int = 0) -> int:
        if track in self.qs:
            return len(self.qs[track])
        return 0

    def is_playing(self, track: int = 0) -> bool:
        return track in self.active

    def set_playing_to(self, active: bool, track: int = 0) -> None:
        if active:
            self.active.add(track)
        else:
            self.active.discard(track)

    def set_playing(self, track: int = 0) -> None:
        self.set_playing_to(True, track)

    def set_not_playing(self, track: int = 0) -> None:
        self.set_playing_to(False, track)

    def enqueue(self, path: QueueItem, track: int = 0) -> None:
        if track not in self.qs:
            self.qs[track] = []
        self.qs[track].append(path)

    def dequeue(self, track: int = 0) -> QueueItem | None:
        if self.is_empty(track):
            return None
        item = self.qs[track][0]
        self.qs[track] = self.qs[track][1:]
        if item.dir_to_rm:
            to_rm = item.dir_to_rm.replace('"', '\\"')
            os.system(f"rm -r \"{to_rm}\"")
        return item

    def peek(self, track: int = 0) -> QueueItem | None:
        if self.is_empty(track):
            return None
        return self.qs[track][0]

    def clear(self, track: int = 0) -> None:
        while self.length(track) > 1:
            self.dequeue(track)

    def stop(self, vc: discord.VoiceClient | None, track: int | None = None) -> None:
        # if vc and vc.is_playing: vc.stop()
        if self.mixer:
            i = 0
            while i < len(self.mixer.sources):
                source = self.mixer.sources[i]
                if track is None or source.track == track:
                    if source.after:
                        source.after()
                    source.close()
                    del self.mixer.sources[i]
                else:
                    i += 1
            if len(self.mixer.sources) == 0:
                if vc and vc.is_playing():
                    vc.stop()
                self.mixer = None

    def add(self, path: str, dir_to_rm: str | None = None, vc: discord.VoiceClient | None = None, track: int = 0) -> None:
        print(f"Adding {path}")
        item = QueueItem(path, dir_to_rm)
        self.enqueue(item, track)
        # if not self.peek(track).playing:
        #     print("Playing it...")
        #     self.play_next(vc, track)
        # else: print("A sound is already playing on this track")
        if self.mixer is None or not self.is_playing(track) or vc is None or not vc.is_playing():
            print("Playing it...")
            self.play_next(vc, track)
        else:
            print("Added it to the queue...")
            print(self.qs[track])

    def _after_impl(self, track: int, vc: discord.VoiceClient) -> None:
        self.dequeue(track)
        if self.all_empty():
            if vc.is_playing():
                vc.stop()
            self.active.clear()
            self.mixer = None
        if self.is_empty(track):
            self.set_not_playing(track)
        else:
            self.play_next(vc, track)

    def play_next(self, vc: discord.VoiceClient | None, track: int = 0) -> None:
        item = self.peek(track)
        if vc is None or item is None:
            self.set_not_playing(track)
            return

        def after() -> None:
            vc.loop.call_soon_threadsafe(self._after_impl, track, vc)
        self.set_playing(track)
        if self.mixer is None or not vc.is_playing():
            self.mixer = Mixer(item.path, after, track)
            vc.play(self.mixer)
        else:
            self.mixer.mix_in(item.path, after, track)
