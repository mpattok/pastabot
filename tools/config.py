from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from dataclasses import dataclass
import json as mod_json
import os
import tempfile
import threading
from types import TracebackType
from typing import Any, Literal

type Value = int | float | str | bool | None
type JSON = Value | list[JSON] | dict[str, JSON]
type Key = str | int


class Config:
    @dataclass
    class Root:
        path: str
        json: JSON
        is_async: bool
        writable: Config.Writable | None
        mutex: asyncio.Lock | threading.Lock
        owner: asyncio.Task[Any] | int | None

    @dataclass
    class Child:
        root: Config.Root
        keys: list[Key]

    @dataclass
    class DictKey:
        key: str
    
    type Data = Config.Root | Config.Child | Config.DictKey

    def __init__(self, data: Config.Data) -> None:
        self.data: Config.Data = data

    @staticmethod
    def open(path: str, is_async: bool = False) -> Config:
        mutex = asyncio.Lock() if is_async else threading.Lock()
        try:
            with open(path, 'r') as f:
                json = mod_json.loads(f.read())
        except FileNotFoundError:
            json = {}
        return Config(Config.Root(path, json, is_async, None, mutex, None))

    def clone(self) -> Config:
        match self.data:
            case Config.Root(path, json, is_async, writable, mutex, owner):
                return Config(Config.Root(path, clone_json(json), is_async, writable, mutex, owner))
            case Config.Child(root, keys):
                cfg, _ = Config(root).clone().follow_keys(keys)
                return cfg
            case Config.DictKey(key):
                return Config(Config.DictKey(key))

    def root(self) -> Config.Root:
        match self.data:
            case Config.Root(_, _, _, _, _, _):
                return self.data
            case Config.Child(root, _):
                return root
            case Config.DictKey(_):
                raise TypeError('Config.DictKey has no root')

    def key_path(self) -> list[Key]:
        match self.data:
            case Config.Root(_, _, _, _, _, _):
                return []
            case Config.Child(_, keys):
                return [key for key in keys]
            case Config.DictKey(_):
                raise TypeError('Config.DictKey has no path from root')

    def follow_keys(self, keys: list[Key]) -> tuple[Config, JSON]:
        def json_follow_one(json: JSON, key: Key) -> JSON:
            if isinstance(json, list):
                return json[verify_type(key, int)]
            if isinstance(json, dict):
                return json[verify_type(key, str)]
            raise TypeError(
                'Config.follow_keys: only list and dict can be indexed')

        def follow_one(cfg: Config, json: JSON, key: Key) -> tuple[Config, JSON]:
            match cfg.data:
                case Config.Root(_, _, _, _, _, _):
                    return (Config(Config.Child(cfg.data, [key])), json_follow_one(json, key))
                case Config.Child(root, keys):
                    return (Config(Config.Child(root, keys + [key])), json_follow_one(json, key))
                case _:
                    assert False
        match self.data:
            case Config.Root(_, json, _, _, _, _):
                cfg = self
                for key in keys:
                    cfg, json = follow_one(cfg, json, key)
                return (cfg, json)
            case Config.Child(root, child_keys):
                return Config(root).follow_keys(child_keys + keys)
            case Config.DictKey(_):
                raise TypeError('Config.DictKey cannot follow keys')

    def json_ref(self) -> JSON:
        match self.data:
            case Config.DictKey(key):
                return key
        _, json = self.follow_keys([])
        return json

    def __getitem__(self, key: Key) -> Config:
        cfg, _ = self.follow_keys([key])
        return cfg

    def __contains__(self, key: JSON) -> bool:
        json = self.json_ref()
        if isinstance(json, dict):
            return verify_type(key, str) in json
        if isinstance(json, list):
            return key in json
        raise TypeError(
            'Config.__contains__: only list or dict can contain anything')

    def __len__(self) -> int:
        json = self.json_ref()
        if isinstance(json, list):
            return len(json)
        if isinstance(json, dict):
            return len(json)
        raise TypeError('Config.__len__: only list or dict have a length')
    
    # TODO: iterating can be a data race, but ostrich algorithm may suffice

    def __iter__(self) -> Iterator[Config]:
        cfg, json = self.follow_keys([])
        if isinstance(json, list):
            class ConfigListIter:
                def __init__(self, cfg: Config):
                    self.cfg = cfg
                    self.i = 0

                def __iter__(self) -> Iterator[Config]:
                    return self

                def __next__(self) -> Config:
                    if self.i >= len(self.cfg):
                        raise StopIteration
                    item = self.cfg[self.i]
                    self.i += 1
                    return item
            return ConfigListIter(self)
        if isinstance(json, dict):
            return map(lambda key: Config(Config.DictKey(key)), iter(list(json)))
        raise TypeError(
            'Config.__iter__: only list or dict can be iterated over')

    def value[T](self, t: type[T], coerce: bool = True) -> T:
        json = self.json_ref()
        if isinstance(json, list) or isinstance(json, dict):
            raise TypeError(
                'Config.value: this instance does not hold a primitive value')
        return verify_type(json, t, coerce=coerce)

    def iter_map[T](self, f: Callable[[Config], T]) -> Iterator[T]:
        return map(f, iter(self))

    def iter_json(self) -> Iterator[JSON]:
        return self.iter_map(Config.json_ref)

    def iter_value[T](self, t: type[T]) -> Iterator[T]:
        return self.iter_map(lambda cfg: cfg.value(t))

    class Writable:
        def __init__(self, config: Config, opener: Config.Writable | None = None):
            self.config: Config = config
            self.opener: Config.Writable = self if opener is None else opener
            self.open = True
            if opener is None:
                if config.root().writable is not None:
                    raise RuntimeError(
                        f'Config.Writable: multiple writable references')
                self.config = config.clone()
                config.root().writable = self

        
        # reuse read-only interface

        def root(self) -> Config.Root: return self.config.root()

        def key_path(self) -> list[Key]: return self.config.key_path()

        def follow_keys(self, keys: list[Key]) -> tuple[Config.Writable, JSON]:
            cfg, json = self.config.follow_keys(keys)
            return Config.Writable(cfg, opener=self.opener), json

        def json_ref(self) -> JSON: return self.config.json_ref()

        def __getitem__(self, key: Key) -> Config.Writable:
            return Config.Writable(self.config[key], opener=self.opener)

        def __contains__(self, key: Key) -> bool: return key in self.config

        def __len__(self) -> int: return len(self.config)

        def __iter__(self) -> Iterator[Config.Writable]:
            return self.config.iter_map(lambda cfg: Config.Writable(cfg, opener=self.opener))

        def value[T](self, t: type[T], coerce: bool = True) -> T:
            return self.config.value(t, coerce=coerce)

        def iter_map[T](self, f: Callable[[Config.Writable], T]) -> Iterator[T]:
            return map(f, iter(self))

        def iter_json(self) -> Iterator[JSON]:
            return self.config.iter_json()

        def iter_value[T](self, t: type[T]) -> Iterator[T]:
            return self.config.iter_value(t)

        
        # new methods in writable context

        def check_open(self):
            if not self.opener.open:
                raise RuntimeError(
                    'Attempting to write with closed Config.Writable')

        def __setitem__(self, key: Key, val: JSON):
            self.check_open()
            json = self.json_ref()
            if isinstance(json, list):
                json[verify_type(key, int)] = val
                return
            if isinstance(json, dict):
                json[verify_type(key, str)] = val
                return
            raise TypeError(
                'Config.Writable.__setitem__: can only set on list or dict')

        def __delitem__(self, key: Key):
            self.check_open()
            json = self.json_ref()
            if isinstance(json, list):
                del json[verify_type(key, int)]
                return
            if isinstance(json, dict):
                del json[verify_type(key, str)]
                return
            raise TypeError(
                'Config.Writable.__delitem__: can only delete from list or dict')

        def append(self, val: JSON):
            self.check_open()
            verify_type(self.json_ref(), list).append(val)

        def remove(self, val: JSON, all: bool = False) -> bool:
            self.check_open()
            json = verify_type(self.json_ref(), list)
            i = 0
            removed = False
            while i < len(json):
                if json[i] != val:
                    i += 1
                    continue
                del json[i]
                if not all:
                    return True
                removed = True
            return removed

        def get_or(self, key: Key, default: JSON) -> Config.Writable:
            self.check_open()
            if key not in self:
                self[key] = default
            return self[key]

    def __enter__(self) -> Config.Writable:
        root = self.root()
        if root.is_async:
            raise TypeError(
                'Cannot use `with` on async Config. Use `async with` instead')
        pid = threading.get_ident()
        if root.owner == pid:
            raise RuntimeError(
                'Config.__enter__: nested `with` on same tree would deadlock')
        root.mutex.acquire()
        root.owner = pid
        try:
            return Config.Writable(self)
        except:
            self._release(False)
            raise

    async def __aenter__(self) -> Config.Writable:
        root = self.root()
        if not root.is_async:
            raise TypeError(
                'Cannot use `async with` on non-async Config. Use `with` instead')
        task = asyncio.current_task()
        if root.owner == task:
            raise RuntimeError(
                'Config.__aenter__: nested `async with` on same tree would deadlock')
        assert isinstance(root.mutex, asyncio.Lock)
        await root.mutex.acquire()
        root.owner = task
        try:
            return Config.Writable(self)
        except:
            self._release(False)
            raise

    def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None) -> Literal[False]:
        self._release(exc_type is None)
        return False

    async def __aexit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None) -> Literal[False]:
        self._release(exc_type is None)
        return False

    def _release(self, do_save: bool):
        try:
            if do_save:
                self.save()
        finally:
            root = self.root()
            if root.writable is not None:
                root.writable.opener.open = False
            root.writable = None
            root.owner = None
            root.mutex.release()

    def save(self, force: bool = False) -> bool:
        # don't write if there is no change to make, unless writing is forced
        root = self.root()
        if root.writable is None:
            if not force:
                return False
            write_atomic(root.path, root.json)
            return True
        if json_eq(root.writable.config.root().json, root.json):
            if not force:
                return False
            write_atomic(root.path, root.json)
            return True
        # write to disk & update memory
        new_json = root.writable.config.root().json
        write_atomic(root.path, new_json)
        root.json = new_json
        return True


def is_json(val: object) -> bool:
    if True in map(lambda t: isinstance(val, t),
                   [int, float, str, bool, type(None)]):
        return True
    if isinstance(val, dict):
        for key in val:
            if not isinstance(key, str):
                return False
            if not is_json(val[key]):
                return False
        return True
    if isinstance(val, list):
        return False not in map(is_json, val)
    return False


def clone_json(val: JSON, check_first: bool = True) -> JSON:
    if check_first and not is_json(val):
        raise TypeError(f'invalid JSON: {val}')
    if isinstance(val, dict):
        return {key: clone_json(val[key], check_first=False) for key in val}
    if isinstance(val, list):
        return [clone_json(item, check_first=False) for item in val]
    return val


def json_eq(x: JSON, y: JSON, check_first: bool = True) -> bool:
    if check_first:
        if not is_json(x):
            raise TypeError(f'invalid JSON: {x}')
        if not is_json(y):
            raise TypeError(f'invalid JSON: {y}')
    if isinstance(x, dict):
        if not isinstance(y, dict):
            return False
        if len(x) != len(y):
            return False
        for key in x:
            if key not in y:
                return False
            if not json_eq(x[key], y[key], check_first=False):
                return False
        return True
    if isinstance(x, list):
        if not isinstance(y, list):
            return False
        if len(x) != len(y):
            return False
        for x, y in zip(x, y):
            if not json_eq(x, y, check_first=False):
                return False
        return True
    return type(x) is type(y) and x == y


def verify_type[T](x: Any, t: type[T], coerce: bool = False) -> T:
    if isinstance(x, t) and (t is not int or not isinstance(x, bool)):
        return x
    if coerce and t in (int, float, str, bool):
        return t(x)
    raise TypeError(f'verify_type: expected {t}')


def write_atomic(path: str, json: JSON) -> None:
    # write to tmp, move to save path
    dirname = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(
        dir=dirname, prefix='.config-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            mod_json.dump(json, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass
        raise
