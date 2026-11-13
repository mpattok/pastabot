# Pastabot

Pastabot is an easily extensible Discord bot made with discord.py. 
The basic framework provides dynamic cog loading and utilities for cogs through
the `App`, `Auth`, `Config`, and `MusicQueue` classes. The `command`
decorator serves as a drop-in replacement for `discord.ext.commands.command`,
with built-in auth checking.

## Quickstart

Python 3.12+ is required. For voice, ffmpeg must be installed on the system.

To use Pastabot as-is, clone the repo 
(`git clone https://github.com/mpattok/pastabot && cd pastabot`) and create a
`config.json` or `.env` to provide the bot's Discord token. A minimal 
`config.json` might look like this:

```json
{
  "token": "YOUR_DISCORD_TOKEN",
  "auth": {
    "admin": {
      "your_discord_user_id": "your_discord_username"
    }
  },
  "sounds": {
    "prefix": "/path/to/sounds/"
  }
}
```

You can alternatively provide the token as `DISCORD_TOKEN` in `.env` or as an
environment variable.

You can then install the dependencies (`pip install -r requirements.txt`) and
run the bot `python main.py`

To add a cog, create the `custom-cogs` directory and create a `.py` file with
a class that subclasses `discord.ext.commands.Cog`. Its constructor should take
a single `App` argument which it saves as `self.app`. The cog will be 
automatically loaded when running the app, without changing any other files. The 
cog file can freely import from `app` and `tools`, since the project's root is 
added to its path when it is loaded. Example cogs can be found in the 
`builtin-cogs` directory.

## Utilities for Cogs

Pastabot provides tools for cogs through the `app` and `tools` modules, which
can be imported by any cog. 

### `App` class

The `App` class is what loads cogs and runs the bot. `main.py` gives a usage
example.

- `def __init__(self, *cog_dirs: str, enable_ip: bool = True, allow_cog_load_fail: bool = False)`:
  this is the `App` constructor. Unnamed parameters are treated as directories
  from which to load cogs. For each directory, every `.py` file (except those
  with a name prefixed by `_`) is loaded, and each class in the file that
  subclasses `discord.ext.commands.Cog` is instantiated with `CogClass(app)` 
  and added to the bot. The `App` has the attributes `auth: Auth`, 
  `config: Config`, and `musicq: MusicQueue`.

    + If `enable_ip` is `True`, `App.get_ip` will provide the bot's IP address.
      This is used by `builtin-cogs/basics.py` with the `on_ready` event
      reporting the IP to bot admins and the `!ip` command replying with the IP
      to any user.

    + If `allow_cog_load_fail` is `True`, cogs that fail to be loaded will not
      crash the application. The error will be reported on stdout and the app
      will continue with cog loading.

- `def run(self)`: retrieves the bot token from `config.json` (with
  the key `token`), `.env`, or the environment (in the latter cases with the key
  `DISCORD_TOKEN`), checking in that order, then runs the bot with that token.
  If no token is found, a message is printed and the function returns.

Since the cogs are given the `App` instance in their constructors, they can use
the `auth`, `config`, and `musicq` instances, as well as these `App` methods:

- `async def connect_to_vc(self, ctx: discord.ext.commands.Context[commands.Bot]) -> discord.VoiceClient`: 
  attempts to connect to the voice channel the context author is
  connected to and return that client to the caller.

- `def get_ip(self) -> str`: returns the IP address running the
  bot, unless this was disabled when the app was constructed. This exposes the
  bot's IP address unless disabled.

- `async def send_dm(self, user_id: int | str, *args, **kwargs)`:
  sends a DM from the bot to the user identified by `user_id`, which should
  be their Discord ID. If the remaining arguments are a single string, the DM
  will be sent buffered (see `buffer_send` below), and otherwise all trailing
  and keyword arguments will be passed to `discord.User.send`

- `async def buffer_send(self, tgt: discord.abc.Messageable, msg: str, max_len: int = 2000)`:
  sends the provided message to the target, possibly as
  multiple messages if the message length exceeds `max_len`, which defaults to
  2000 characters, the maximum allowed message length on Discord. The message
  is first split on line breaks, then spaces, then in the middle of words as a
  fallback.

A cog which correctly stores `self.app` can access these attributes and methods 
with `self.app.auth`, `self.app.config`,  `self.app.musicq`, 
`self.app.connect_to_vc(ctx)`, etc.

### `command` decorator

Also in the `app` module is the `command` function, which should be a drop-in
replacement for `discord.ext.commands.command`. It wraps the latter, adding the 
keyword-only arguments `auth` and `catch`. When used to decorate a cog method, 
it registers it as a command using `discord.ext.commands.command`, while also 
adding authentication and error catching depending on those arguments: `auth`, 
if provided, specifies the minimum auth level a user must have to invoke the
command. `catch`, if set to `True` (defaults to `False`), wraps the command
invocation in a blanket try-catch which reports any exceptions to the caller.
This can be useful for debugging, but it is best to catch errors within the
command and give a more useful message.

### `Config` class

The `Config` class is a manager for JSON files. While any cog might use it to
manage any JSON file, the primary purpose is to give access to the bot's
`config.json` to every cog. For the most part, a `Config` object can be
treated like a JSON `dict`, `list`, or primitive, except for two caveats:

1. All indexing returns a `Config` object, so even primitives are wrapped. To
get a primitive from a `Config` whose JSON is a primitive, use the `value`
method, which takes in the desired primitive type. 

2. There is no write access outside of an `async with` block; a normal 
`Config` does not provide `__setitem__`, `__delitem__`, or other writing 
methods. Inside a `with`/`async with` block, a `Config.Writable` provides these 
methods, and the JSON is saved when the block exits. Only one `Config.Writable` 
can exist at a time; other threads/tasks will wait for a lock when attempting to
enter an already-entered `Config`. The `Config.Writable` JSON is a copy which
is written to disk and back to the owning `Config` on `with`/`async with` block
exit. If the block raises, no changes are saved on disk or in memory.

`Config` methods:

- (static) `def open(path: str, is_async: bool = False) -> Config`: this is how
  you should create a `Config`. The class constructor takes in a `Config.Data`,
  which you should not create. In the context of a Discord bot, you should set
  `is_async=True`

- `def value[T](self, t: type[T], coerce: bool = True) -> T`: 
  unwraps a primitive value pointed to by a `Config`. By default, this will 
  coerce the value to the desired type if it was not loaded as that type; pass 
  `coerce=False` to instead raise an error if the type is different from the 
  desired type. 

- `def json_ref(self) -> JSON`: gives you a reference to the JSON
  the `Config` object points to. This could be used to write to a returned
  `dict` or `list`, which would break the invariant that only a 
  `Config.Writable` can write the config, so don't do this. This method is
  exposed to give efficient read access to complex parts of the config.

- `def __getitem__(self, key: Key) -> Config`: indexes into a
  `dict` or `list` config. As noted above, the return value is always a
  `Config` object, so if you want to get a primitive, e.g. a `str`, you would
  need to use `config[key].value(str)`

- `def __contains__(self, key: JSON) -> bool`: provides
  `key in config` in the expected manner.

- `def __len__(self) -> int`: provides `len(config)` in the
  expected manner.

- `def __iter__(self) -> Iterator[Config]`: allows you to
  iterate over elements of a `list` config or keys of a `dict` config. In
  either case, `__next__` will always return a `Config`, so to get keys as
  strings you will need to call `value(str)` on the items. You can also use one
  of the other iterator methods below.

- `def iter_map[T](self, f: Callable[[Config], T]) -> Iterator[T]`:
  returns an iterator mapped by `f`. 

- `def iter_json(self) -> Iterator[JSON]`: returns an iterator
  over the JSON. Note that this JSON, like that returned by `json_ref`, is a
  reference into the internal memory of the config, so writing to it breaks the
  config's invariant.

- `def iter_value[T](self, t: type[T], coerce: bool = True) -> Iterator[T]`: 
  returns an iterator over primitives of the given type. It is
  particularly useful for iterating over `dict` config keys, or through `list`
  configs when you are sure of the contained type.

- `def save(self, force: bool = False) -> bool`: writes the config
  JSON to the path that was opened. Unless `force` is set, writing will only
  take place if the config has changed. This method is automatically called
  when exiting a `with`/`async with` block, but is made available in case you
  need to save at another time.

Within a `with`/`async with` block, you have a `Config.Writable`, which, in
addition to the `Config` methods above, has these methods:

- `def __setitem__(self, key: Key, val: JSON)`: allows assignment
  in the expected manner.

- `def __delitem__(self, key: Key)`: allows deletion in the expected
  manner.

- `def append(self, val: JSON)`: appends the value to the end of a
  `list` config (and raises an exception for any other type of config).

- `def remove(self, val: JSON, all: bool = False) -> bool`: removes
  the given element, by structural equality, from a `list` config (and raises
  an exception for any other type of config). If `all` is `True`, all 
  occurrences are removed. Otherwise (the default), only the first occurrence is
  removed. `remove` returns `True` if any elements are removed.

- `def get_or(self, key: Key, default: JSON) -> Config.Writable`: 
  ensures that the given key is contained in the config, then indexes into
  itself with that key. 

While the bot is running, you should not make any changes to `config.json`
manually, since these will be overwritten by the bot's in-memory version.
If you need to make manual edits, first ensure that the bot is not running.

### `Auth` class

The `Auth` class is used to verify that a user can invoke the commands with a
specified auth level. For the most part, a cog should only need it to specify
the auth level in the `command` decorator of a command, but the `reject` method
may also be useful:

- `async def reject(self, ctx: commands.Context[commands.Bot], min_auth: int | None) -> bool`:
  returns `True` if the author of the given context has a lower
  auth level than `min_auth`. If it isn't a known auth level, `min_auth` is 
  treated as `Auth.NOAUTH`. A rejection also sends a message to the context.

The auth levels can be accessed as `Auth.BLACKLIST`, `Auth.NOAUTH`, 
`Auth.TRUSTED`, `Auth.MODERATOR`, and `Auth.ADMIN`. In the config their names
are `blacklist`, `trusted`, `moderator`, and `admin` (`noauth` is used only by
the `!auth` command to remove a user's auth level designation).

Note that the auth levels used by Pastabot are specific to Pastabot; the bot
does not use or reference a user's Discord server auth level at any time. This
means that a user's Pastabot auth level is cross-server; if they have a certain
auth level in one server, they have that same level in every server. This can
effectively give a user who is not a server moderator some of the powers of a
server moderator if they are a Pastabot moderator in a server in which Pastabot
has moderation privileges.

Generally, auth levels should be managed with the `!auth` command, but its
usage requires that the caller have a higher auth than both the target and the
auth level they are setting the target to. It is thus impossible to use the
`!auth` command to give someone an auth level that is not less than the highest
level given in `config.json`, so you will need to define at least one user at
the highest auth level you intend to use.

### `MusicQueue` class

The bot provides a multi-track sound queue with `tools/musicq.py` and
`tools/mixer.py`. Cogs can add sounds to a track using `self.app.musicq.add`,
and the bot will play the sound in VC. Multiple tracks can be played
simultaneously, which is utilized by the built-in cogs `sounds.py` and `tts.py`
to allow users to use TTS while the bot is playing other sounds.

- `def add(self, path: str, dir_to_rm: str | None = None, vc: discord.VoiceClient | None = None, track: int = 0)`:
  adds a file to be played by the `MusicQueue` in the given `vc` on 
  the given `track`. If `dir_to_rm` is specified, that directory is deleted
  after the sound is played. If `vc` is not provided, nothing will actually be
  played until another sounds provides a voice client to use.

- `def stop(self, vc: discord.VoiceClient | None, track: int | None = None)`: 
  stops the currently playing sound in the specified `vc` and 
  `track`, or all tracks if no track is specified.

- `def clear(self, track: int = 0)`: this method clears the queue, but does not
  stop the currently playing sound.

## Built-in Cogs

Several cogs are provided in `builtin-cogs`:    
- `basics.py` provides an `on_ready` notifier and the commands `ping`,
  `ip`, `echo`, `dm`, `find`, `avatar`, `whoami`, `throw`, and `console`.  
- `cipher.py` provides the commands `encrypt` and `decrypt`.  
- `moderation.py` provides the commands `auth`, `delete`, `reset`, `mute`,
  and `unmute`. After the `mute` command is invoked on a user, the bot will
  start deleting any messages they send for 10 minutes. This is obviously
  inferior to Discord's built-in muting functionality, and it is mostly
  intended as a joke, since a user is still able to type and send a message
  only to see it deleted immediately. Muting is per-channel.
- `rng.py` provides the `rng` and `choose` commands.
- `shy.py` provides the `shy`, `notshy`, `allow`, and `disallow` commands.
  When a user is registered as shy, if they are unmuted in VC then everyone
  else in VC will be deafened, except those that user has registered as
  being allowed to hear them. Since this has obvious potential for abuse,
  users must have the `trusted` auth level in order to register as shy.
- `sounds.py` provides the commands `join`, `leave`, `sound`, `stop`,
  `clear`, and `sounds`. It adds sounds from the directory specified by
  `config["sounds"]["prefix"]` to the bot's sound queue.
- `steam.py` provides the commands `steam` and `steamdebug`. Every 4 hours,
  the bot will check Steam to see if any games are on sale that a user has
  asked the bot to watch for them. If there are new sales, the bot will DM
  the user and also ping them in the channel where they invoked the `steam`
  command.
- `tts.py` provides the commands `tts`, `notts`, `checktts`, `vtts`, 
  and `piper`. Users can register to have the bot say their messages using
  either the Google Translate API or a Piper model run locally by the bot.
  Note that the latter is typically much slower and uses more memory. The
  bot also only keeps up to five Piper voices loaded at a time.
- `watchlist.py` provides the commands `watch` (show the watchlist or add an
  item) and `watched` (remove an item) for managing a watchlist. The watchlist
  is global to the bot.

The built-in cogs provide usage examples for registering commands and using the
tools provided by the app, including the above functions, auth, the config, and
the sound queue.
