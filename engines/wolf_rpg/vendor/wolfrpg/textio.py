"""Locating translatable text inside a Wolf RPG ``Data/`` tree.

Export and import both walk the project through :func:`collect_slots`, so the
address written into ``script.json`` is by construction the address the importer
will resolve.  A slot is a *cursor* onto one string inside a loaded file: reading
and writing go straight through to the parsed object.

What is and is not offered for translation is decided here.  The rule is that a
string is exported only if a player can see it, and only if changing it cannot
break control flow.  Labels (``SetLabel``/``JumpLabel``), common-event names
referenced by ``CommonEventByName``, and every kind of asset path are therefore
withheld — translating those silently breaks the game rather than the text.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Iterator

from .common_events import CommonEvents
from .database import Database
from .filecoder import WolfFormatError
from .game_dat import GameDat
from .map import Map

__all__ = ["Slot", "WolfProject", "CONTEXTS", "RISKY_CONTEXTS", "looks_like_path"]

# Context labels used in the exported JSON.
CONTEXTS = (
    "dialog",          # Show Message
    "choice",          # Show Choices
    "picture_text",    # Show Picture, text flavour
    "call_arg",        # String arguments passed into a common event call
    "string_var",      # Set String, when the value is not an asset path
    "condition",       # String comparison operands
    "debug",           # Debug-only messages
    "database",        # Database string columns
    "game_title",      # Game.dat window title
)

# Contexts where a translation can change behaviour, not just presentation.
RISKY_CONTEXTS = ("condition", "string_var")

_PATH_EXTS = (
    ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".ogg", ".mp3", ".wav", ".mid",
    ".midi", ".ttf", ".ttc", ".sav", ".txt", ".dat", ".mps", ".avi", ".wmv",
)

# Wolf's own placeholder for "no picture window file".
_PICTURE_TOKENS = ("<SQUARE>",)


def looks_like_path(text: str) -> bool:
    """True if this string is an asset path rather than player-facing text."""
    if not text:
        return True
    lowered = text.lower()
    if lowered.endswith(_PATH_EXTS):
        return True
    if ("/" in text or "\\" in text) and "." in text.rsplit("/", 1)[-1]:
        return True
    return text in _PICTURE_TOKENS


@dataclass
class Slot:
    """A cursor onto one translatable string."""

    source_file: str
    location: str
    context: str
    code: int
    _get: Callable[[], bytes] = field(repr=False)
    _set: Callable[[bytes], None] = field(repr=False)

    @property
    def raw(self) -> bytes:
        return self._get()

    def write(self, value: bytes) -> None:
        self._set(value)


def _list_slot(container: list, index: int, **kw) -> Slot:
    return Slot(
        _get=lambda: container[index],
        _set=lambda v: container.__setitem__(index, v),
        **kw,
    )


class WolfProject:
    """All translatable files under a ``Data/`` directory, loaded together."""

    DATABASES = ("DataBase", "CDataBase", "SysDatabase")
    # SysDataBaseBasic.project uses a reduced per-type layout with no field
    # metadata block, and holds only editor scaffolding (map/BGM/SE lists).
    # WolfTL skips it for the same reason.
    SKIPPED_DATABASES = ("SysDataBaseBasic",)

    def __init__(self, data_dir: str, encoding: str = "cp932"):
        self.data_dir = data_dir
        self.encoding = encoding
        self.maps: dict[str, Map] = {}
        self.common_events: CommonEvents | None = None
        self.databases: dict[str, Database] = {}
        self.game_dat: GameDat | None = None
        self.errors: list[str] = []

        map_dir = os.path.join(data_dir, "MapData")
        if os.path.isdir(map_dir):
            for name in sorted(os.listdir(map_dir)):
                if not name.lower().endswith(".mps"):
                    continue
                path = os.path.join(map_dir, name)
                try:
                    self.maps[f"MapData/{name}"] = Map(path)
                except WolfFormatError as exc:
                    self.errors.append(f"MapData/{name}: {exc}")

        basic = os.path.join(data_dir, "BasicData")
        ce_path = os.path.join(basic, "CommonEvent.dat")
        if os.path.isfile(ce_path):
            try:
                self.common_events = CommonEvents(ce_path)
            except WolfFormatError as exc:
                self.errors.append(f"BasicData/CommonEvent.dat: {exc}")

        for name in self.DATABASES:
            project = os.path.join(basic, f"{name}.project")
            dat = os.path.join(basic, f"{name}.dat")
            if not (os.path.isfile(project) and os.path.isfile(dat)):
                continue
            try:
                self.databases[name] = Database(project, dat)
            except WolfFormatError as exc:
                self.errors.append(f"BasicData/{name}: {exc}")

        game_path = os.path.join(basic, "Game.dat")
        if os.path.isfile(game_path):
            try:
                self.game_dat = GameDat(game_path)
            except WolfFormatError as exc:
                self.errors.append(f"BasicData/Game.dat: {exc}")

    # -- text discovery ----------------------------------------------------

    def slots(self) -> Iterator[Slot]:
        yield from self._map_slots()
        yield from self._common_event_slots()
        yield from self._database_slots()
        yield from self._game_dat_slots()

    def _command_slots(self, command, source_file: str, prefix: str) -> Iterator[Slot]:
        """Yield the translatable string args of one event command."""
        cid = command.cid
        args = command.string_args
        if not args:
            return

        def make(index: int, context: str) -> Slot:
            return _list_slot(
                args, index,
                source_file=source_file,
                location=f"{prefix}/Str{index}",
                context=context,
                code=cid,
            )

        if cid == 101:                      # Show Message
            yield make(0, "dialog")
        elif cid == 102:                    # Show Choices
            for i in range(len(args)):
                yield make(i, "choice")
        elif cid == 106:                    # Debug Message
            yield make(0, "debug")
        elif cid == 150:                    # Show Picture
            # Only the "text" flavour holds words; every other flavour holds a
            # filename or a string-variable reference.
            if command.picture_type == 2:
                yield make(0, "picture_text")
        elif cid == 122:                    # Set String
            for i, raw in enumerate(args):
                if not looks_like_path(raw.decode(self.encoding, errors="replace")):
                    yield make(i, "string_var")
        elif cid == 112:                    # String comparison
            for i, raw in enumerate(args):
                if raw:
                    yield make(i, "condition")
        elif cid in (210, 300):
            # Arguments handed to a common event. These carry real on-screen
            # text -- the speaker name plate above the message box is one of
            # them -- so they must be translated even though the command itself
            # is a call. For CommonEventByName (300) the first string is the
            # event's *name*, which resolves the call and must stay untouched.
            first = 1 if cid == 300 else 0
            for i in range(first, len(args)):
                raw = args[i]
                if not raw:
                    continue
                if looks_like_path(raw.decode(self.encoding, errors="replace")):
                    continue
                yield make(i, "call_arg")

    def _map_slots(self) -> Iterator[Slot]:
        for source_file, wolf_map in self.maps.items():
            for ei, event in enumerate(wolf_map.events):
                for pi, page in enumerate(event.pages):
                    for ci, command in enumerate(page.commands):
                        yield from self._command_slots(
                            command, source_file, f"Ev{ei}/Pg{pi}/Cmd{ci}"
                        )

    def _common_event_slots(self) -> Iterator[Slot]:
        if self.common_events is None:
            return
        for ei, event in enumerate(self.common_events.events):
            for ci, command in enumerate(event.commands):
                yield from self._command_slots(
                    command, "BasicData/CommonEvent.dat", f"CEv{ei}/Cmd{ci}"
                )

    def _database_slots(self) -> Iterator[Slot]:
        for name, db in self.databases.items():
            source_file = f"BasicData/{name}.dat"
            for ti, db_type in enumerate(db.types):
                for di, row in enumerate(db_type.dat_data):
                    for db_field, raw in row.translatable_fields():
                        text = raw.decode(self.encoding, errors="replace")
                        if looks_like_path(text):
                            continue
                        yield _list_slot(
                            row.string_values, db_field.index,
                            source_file=source_file,
                            location=f"Type{ti}/Data{di}/Field{db_field.index}",
                            context="database",
                            code=-1,
                        )

    def _game_dat_slots(self) -> Iterator[Slot]:
        if self.game_dat is None:
            return
        game_dat = self.game_dat

        def set_title(value: bytes) -> None:
            game_dat.title = value

        yield Slot(
            source_file="BasicData/Game.dat",
            location="title",
            context="game_title",
            code=-1,
            _get=lambda: game_dat.title,
            _set=set_title,
        )

    # -- output ------------------------------------------------------------

    def save(self, out_dir: str) -> list[str]:
        """Write every loaded file into ``out_dir``.  Returns written paths."""
        written = []
        for rel, wolf_map in self.maps.items():
            path = os.path.join(out_dir, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            wolf_map.dump(path)
            written.append(rel)

        basic = os.path.join(out_dir, "BasicData")
        os.makedirs(basic, exist_ok=True)

        if self.common_events is not None:
            self.common_events.dump(os.path.join(basic, "CommonEvent.dat"))
            written.append("BasicData/CommonEvent.dat")

        for name, db in self.databases.items():
            db.dump(
                os.path.join(basic, f"{name}.project"),
                os.path.join(basic, f"{name}.dat"),
            )
            written.append(f"BasicData/{name}.project")
            written.append(f"BasicData/{name}.dat")

        if self.game_dat is not None:
            self.game_dat.dump(os.path.join(basic, "Game.dat"))
            written.append("BasicData/Game.dat")

        return written
