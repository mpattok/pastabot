import asyncio
import copy
import json as mod_json
import os
import tempfile
import threading

class Config:
    def __init__(self, path=None, parent=None, key=None, json=None, is_async=False):
        self.path = path
        self.parent = parent
        self.key = key
        self.json = json
        self.is_async = is_async if parent is None else parent.is_async
        # the whole tree shares the root's mutex
        if parent is not None: self.mutex = parent.mutex
        else: self.mutex = asyncio.Lock() if self.is_async else threading.Lock()
        self.owner = None
        self.writable = None
        if path is not None:
            try:
                with open(path, 'r') as f:
                    self.json = mod_json.loads(f.read())
            except FileNotFoundError:
                self.json = {}
    @staticmethod
    def is_json(val):
        if True in map(lambda t: isinstance(val, t),
                       [int, float, str, bool, type(None)]):
            return True
        if isinstance(val, dict):
            for key in val:
                if not isinstance(key, str): return False
                if not Config.is_json(val[key]): return False
            return True
        if isinstance(val, list):
            return False not in map(Config.is_json, val)
        return False
    @staticmethod
    def clone_json(val):
        assert Config.is_json(val), f'invalid JSON: {val}'
        if True in map(lambda t: isinstance(val, t),
                               [int, float, str, bool, type(None)]):
            return val
        if isinstance(val, dict):
            return {key: Config.clone_json(val[key]) for key in val}
        if isinstance(val, list):
            return [Config.clone_json(item) for item in val]
        assert False, 'Config.clone_json: this should be unreachable'
    @staticmethod
    def json_eq(x, y):
        assert Config.is_json(x), f'invalid JSON: {x}'
        assert Config.is_json(y), f'invalid JSON: {y}'
        if isinstance(x, dict):
            if not isinstance(y, dict): return False
            if len(x) != len(y): return False
            for key in x:
                if key not in y: return False
                if not Config.json_eq(x[key], y[key]): return False
            return True
        if isinstance(x, list):
            if not isinstance(y, list): return False
            if len(x) != len(y): return False
            for x, y in zip(x, y):
                if not Config.json_eq(x, y): return False
            return True
        return type(x) is type(y) and x == y
    def clone(self):
        return Config(json=Config.clone_json(self.json), is_async=self.is_async)
    def root(self):
        config = self
        while config.parent is not None: config = config.parent
        return config
    @staticmethod
    def write_atomic(path, json):
        # dump to a temp file in the same directory (so os.replace stays on one
        # filesystem), then atomically swap it into place
        dirname = os.path.dirname(os.path.abspath(path))
        fd, tmp_path = tempfile.mkstemp(dir=dirname, prefix='.config-', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w') as f:
                mod_json.dump(json, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except BaseException:
            try: os.remove(tmp_path)
            except FileNotFoundError: pass
            raise
    def save(self, force=False):
        if force:
            new_json = self.json
        else:
            if self.writable is None: return False
            new_json = self.writable.config.json
            if Config.json_eq(new_json, self.json): return False
        # splice new_json into a copy of the root tree, copying only the path to self
        node, new_root = self, new_json
        while node.parent is not None:
            container = copy.copy(node.parent.json)
            container[node.key] = new_root
            new_root, node = container, node.parent
        Config.write_atomic(node.path, new_root)
        # disk write succeeded; now commit in memory. update in place so that
        # existing child Configs pointing into this subtree stay current
        if new_json is not self.json:
            if isinstance(self.json, dict):
                self.json.clear()
                self.json.update(new_json)
            else:
                self.json[:] = new_json
        return True
    def __getitem__(self, key):
        if isinstance(self.json[key], list) or isinstance(self.json[key], dict):
            return Config(parent=self, key=key, json=self.json[key])
        return self.json[key]
    def __contains__(self, key): return key in self.json
    def __len__(self): return len(self.json)
    def __iter__(self):
        if isinstance(self.json, dict): return iter(self.json)
        if isinstance(self.json, list):
            class ConfigListIterator:
                def __init__(self, config):
                    self.config = config
                    self.i = 0
                def __next__(self):
                    if self.i < len(self.config):
                        self.i += 1
                        return self.config[self.i - 1]
                    raise StopIteration
            return ConfigListIterator(self)
        raise ValueError(f'cannot iterate over this: {self.json}')
    class WritableConfig:
        def __init__(self, config, _clone=True):
            if _clone:
                assert config.writable is None, f'Config.WritableConfig: multiple writable references'
                self.config = config.clone()
                self.original = config
                config.writable = self
            else:
                self.config = config
                self.original = None
        def __getitem__(self, key): 
            res = self.config[key]
            if isinstance(res, Config): return Config.WritableConfig(res, _clone=False)
            return res
        def __contains__(self, key): return key in self.config
        def __len__(self): return len(self.config)
        def __iter__(self): 
            writable = lambda x: Config.WritableConfig(x, _clone=False) if isinstance(x, Config) else x
            return map(writable, iter(self.config))
        def __setitem__(self, key, val):
            assert Config.is_json(val), f'invalid JSON: {val}'
            self.config.json[key] = val
        def __delitem__(self, key):
            del self.config.json[key]
        def append(self, val):
            assert isinstance(self.config.json, list), 'Config.append: can only append to lists'
            assert Config.is_json(val), f'invalid JSON: {val}'
            self.config.json.append(val)
        def remove(self, val):
            if isinstance(self.config.json, list):
                removed = False
                i = 0
                while i < len(self.config.json):
                    if self.config.json[i] == val: 
                        del self.config.json[i]
                        removed = True
                    else: i += 1
                return removed
            else: raise ValueError('Config.remove: called on non-list')
        def get_or(self, key, default):
            assert Config.is_json(default), f'invalid JSON: {default}'
            if key not in self: self[key] = default
            return self[key]
    def _current_owner(self):
        return asyncio.current_task() if self.is_async else threading.get_ident()
    def _check_reentry(self):
        # the root's owner is only ever set to this thread/task by this thread/task,
        # so checking it before acquiring is race-free
        if self.root().owner == self._current_owner():
            raise RuntimeError('Config: nested `with` on the same config tree would deadlock')
    def _acquired(self):
        self.root().owner = self._current_owner()
        return Config.WritableConfig(self)
    def _release(self, exc_type):
        try:
            if exc_type is None: self.save()
        finally:
            self.writable = None
            self.root().owner = None
            self.mutex.release()
    def __enter__(self):
        assert not self.is_async, 'this is an async config. use `async with` instead'
        self._check_reentry()
        self.mutex.acquire()
        return self._acquired()
    def __exit__(self, exc_type, exc_value, traceback):
        self._release(exc_type)
        return False
    async def __aenter__(self):
        assert self.is_async, 'this is not an async config. use normal `with` instead'
        self._check_reentry()
        await self.mutex.acquire()
        return self._acquired()
    async def __aexit__(self, exc_type, exc_value, traceback):
        self._release(exc_type)
        return False

