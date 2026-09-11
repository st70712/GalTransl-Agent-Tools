"""``*.mps`` map file parsing for Wolf RPG Editor.

Ported from wolftrans's ``lib/wolfrpg/map.rb``, with the fixed header split into
real fields (version / unknown byte / tileset label) the way WolfTL does it, so
maps saved by different editor versions still round-trip.
"""

from __future__ import annotations

import os

from .command import RouteCommand, read_command
from .filecoder import FileCoder, WolfFormatError

__all__ = ["Map", "Event", "Page"]

MAGIC_NUMBER = bytes(
    [0x00] * 10 + [0x57, 0x4F, 0x4C, 0x46, 0x4D, 0x00] + [0x00, 0x00, 0x00, 0x00]
)
# Byte 16 is 0x00 in Wolf 2.x and 0x55 in Wolf 3.x.
MAGIC_VARIABLE = {16: frozenset({0x00, 0x55})}
# Wolf 3.x maps may omit the tile layers entirely and store this instead.
NO_TILES = bytes([0xFF, 0xFF, 0xFF, 0xFF])
EVENT_INDICATOR = 0x6F
MAP_TERMINATOR = 0x66

EVENT_MAGIC1 = bytes([0x39, 0x30, 0x00, 0x00])
EVENT_MAGIC2 = bytes([0x00, 0x00, 0x00, 0x00])
PAGE_INDICATOR = 0x79
EVENT_TERMINATOR = 0x70
PAGE_TERMINATOR = 0x7A
COMMANDS_TERMINATOR = bytes([0x03, 0x00, 0x00, 0x00])


class Page:
    """One page of an event: conditions, a move route and a command list."""

    __slots__ = (
        "id", "unknown1", "graphic_name", "graphic_direction", "graphic_frame",
        "graphic_opacity", "graphic_render_mode", "conditions", "movement",
        "flags", "route_flags", "route", "commands", "shadow_graphic_num",
        "collision_width", "collision_height",
    )

    def __init__(self, coder: FileCoder, page_id: int):
        self.id = page_id
        self.unknown1 = coder.read_int()
        self.graphic_name = coder.read_string()
        self.graphic_direction = coder.read_byte()
        self.graphic_frame = coder.read_byte()
        self.graphic_opacity = coder.read_byte()
        self.graphic_render_mode = coder.read_byte()
        self.conditions = coder.read(1 + 4 + 4 * 4 + 4 * 4)
        self.movement = coder.read(4)
        self.flags = coder.read_byte()
        self.route_flags = coder.read_byte()
        self.route = [RouteCommand.read(coder) for _ in range(coder.read_int())]
        self.commands = [read_command(coder) for _ in range(coder.read_int())]
        coder.verify(COMMANDS_TERMINATOR)
        self.shadow_graphic_num = coder.read_byte()
        self.collision_width = coder.read_byte()
        self.collision_height = coder.read_byte()
        terminator = coder.read_byte()
        if terminator != PAGE_TERMINATOR:
            raise WolfFormatError(
                f"page terminator not {PAGE_TERMINATOR:#04x} (got {terminator:#04x})"
            )

    def dump(self, coder: FileCoder) -> None:
        coder.write_int(self.unknown1)
        coder.write_string(self.graphic_name)
        coder.write_byte(self.graphic_direction)
        coder.write_byte(self.graphic_frame)
        coder.write_byte(self.graphic_opacity)
        coder.write_byte(self.graphic_render_mode)
        coder.write(self.conditions)
        coder.write(self.movement)
        coder.write_byte(self.flags)
        coder.write_byte(self.route_flags)
        coder.write_int(len(self.route))
        for cmd in self.route:
            cmd.dump(coder)
        coder.write_int(len(self.commands))
        for cmd in self.commands:
            cmd.dump(coder)
        coder.write(COMMANDS_TERMINATOR)
        coder.write_byte(self.shadow_graphic_num)
        coder.write_byte(self.collision_width)
        coder.write_byte(self.collision_height)
        coder.write_byte(PAGE_TERMINATOR)


class Event:
    """A map event: a named object at a tile position with one or more pages."""

    __slots__ = ("id", "name", "x", "y", "pages")

    def __init__(self, coder: FileCoder):
        coder.verify(EVENT_MAGIC1)
        self.id = coder.read_int()
        self.name = coder.read_string()
        self.x = coder.read_int()
        self.y = coder.read_int()
        page_count = coder.read_int()
        coder.verify(EVENT_MAGIC2)

        self.pages: list[Page] = []
        while (indicator := coder.read_byte()) == PAGE_INDICATOR:
            self.pages.append(Page(coder, len(self.pages)))
        if indicator != EVENT_TERMINATOR:
            raise WolfFormatError(
                f"unexpected event page indicator {indicator:#04x}"
            )
        if len(self.pages) != page_count:
            raise WolfFormatError(
                f"event {self.id}: expected {page_count} pages, read {len(self.pages)}"
            )

    def dump(self, coder: FileCoder) -> None:
        coder.write(EVENT_MAGIC1)
        coder.write_int(self.id)
        coder.write_string(self.name)
        coder.write_int(self.x)
        coder.write_int(self.y)
        coder.write_int(len(self.pages))
        coder.write(EVENT_MAGIC2)
        for page in self.pages:
            coder.write_byte(PAGE_INDICATOR)
            page.dump(coder)
        coder.write_byte(EVENT_TERMINATOR)


class Map:
    """A ``.mps`` map file."""

    LAYER_COUNT = 3

    def __init__(self, path: str):
        self.path = path
        self.name = os.path.splitext(os.path.basename(path))[0]

        coder = FileCoder.for_read(path)
        self.magic = coder.verify_variant(MAGIC_NUMBER, MAGIC_VARIABLE)
        self.version = coder.read_int()
        self.unknown2 = coder.read_byte()
        self.tileset_label = coder.read_string()

        if self.version >= 0x67:
            raise WolfFormatError(
                f"{path}: map version {self.version:#x} (Wolf 3.5+) is not supported"
            )

        self.tileset_id = coder.read_int()
        self.width = coder.read_int()
        self.height = coder.read_int()
        event_count = coder.read_int()
        # Wolf 3.x writes a 0xFFFFFFFF placeholder instead of the tile layers on
        # maps that carry no tile data.  A real tile array would be far larger
        # than what is left in the file, so the two cases cannot be confused.
        tile_size = self.width * self.height * self.LAYER_COUNT * 4
        if coder.peek(4) == NO_TILES and coder.remaining < tile_size:
            coder.skip(4)
            self.tiles = None
        else:
            self.tiles = coder.read(tile_size)

        self.events: list[Event] = []
        while (indicator := coder.read_byte()) == EVENT_INDICATOR:
            self.events.append(Event(coder))
        if indicator != MAP_TERMINATOR:
            raise WolfFormatError(f"unexpected event indicator {indicator:#04x}")
        if len(self.events) != event_count:
            raise WolfFormatError(
                f"{path}: expected {event_count} events, read {len(self.events)}"
            )
        if not coder.eof:
            raise WolfFormatError(
                f"{path}: {len(coder.data) - coder.offset} trailing bytes"
            )

    def dump(self, path: str) -> None:
        coder = FileCoder()
        coder.write(self.magic)
        coder.write_int(self.version)
        coder.write_byte(self.unknown2)
        coder.write_string(self.tileset_label)
        coder.write_int(self.tileset_id)
        coder.write_int(self.width)
        coder.write_int(self.height)
        coder.write_int(len(self.events))
        coder.write(NO_TILES if self.tiles is None else self.tiles)
        for event in self.events:
            coder.write_byte(EVENT_INDICATOR)
            event.dump(coder)
        coder.write_byte(MAP_TERMINATOR)
        coder.save(path)

    def iter_commands(self):
        """Yield ``(event, page, line_index, command)`` for every command."""
        for event in self.events:
            for page in event.pages:
                for line, command in enumerate(page.commands):
                    yield event, page, line, command
