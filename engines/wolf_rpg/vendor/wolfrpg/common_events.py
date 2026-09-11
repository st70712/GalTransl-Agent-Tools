"""``CommonEvent.dat`` parsing for Wolf RPG Editor.

Ported from wolftrans's ``lib/wolfrpg/common_events.rb``.  Most of the per-event
trailer is still undocumented; it is preserved verbatim so the file round-trips.
"""

from __future__ import annotations

from .command import read_command
from .filecoder import FileCoder, WolfFormatError

__all__ = ["CommonEvents", "CommonEvent"]

MAGIC_NUMBER = bytes([0x00, 0x57, 0x00, 0x00, 0x4F, 0x4C, 0x00, 0x46, 0x43, 0x00])
# Byte 6 is 0x00 in Wolf 2.x and 0x55 in Wolf 3.x.
MAGIC_VARIABLE = {6: frozenset({0x00, 0x55})}
EVENT_INDICATOR = 0x8E
EVENT_TERMINATOR = 0x8F
# Each of the four per-event argument blocks is prefixed with its own length.
# It was always 10 in Wolf 2.x (which is why wolftrans treated it as a magic
# number); Wolf 3.x grew the argument-name block to 11.
MAX_ARG_SLOTS = 64


def _slots(coder: FileCoder) -> int:
    """Read the length prefix of one argument block, with a sanity bound."""
    count = coder.read_int()
    if not 0 <= count <= MAX_ARG_SLOTS:
        raise WolfFormatError(
            f"argument block length {count} at offset {coder.offset - 4} "
            f"is out of range"
        )
    return count


class CommonEvent:
    """One common event: a name, a command list and a large opaque trailer."""

    def __init__(self, coder: FileCoder):
        indicator = coder.read_byte()
        if indicator != EVENT_INDICATOR:
            raise WolfFormatError(
                f"common event header indicator not {EVENT_INDICATOR:#04x} "
                f"(got {indicator:#04x})"
            )
        self.id = coder.read_int()
        self.unknown1 = coder.read_int()
        self.unknown2 = coder.read(7)
        self.name = coder.read_string()
        self.commands = [read_command(coder) for _ in range(coder.read_int())]
        self.unknown11 = coder.read_string()
        self.description = coder.read_string()

        indicator = coder.read_byte()
        if indicator != EVENT_TERMINATOR:
            raise WolfFormatError(
                f"common event data indicator not {EVENT_TERMINATOR:#04x} "
                f"(got {indicator:#04x})"
            )

        # Argument names shown in the editor's call dialog.
        self.arg_names = [coder.read_string() for _ in range(_slots(coder))]
        self.unknown4 = [coder.read_byte() for _ in range(_slots(coder))]
        # Per-argument dropdown labels: these are player-visible in some games.
        self.arg_choices = [
            [coder.read_string() for _ in range(coder.read_int())]
            for _ in range(_slots(coder))
        ]
        self.unknown6 = [
            [coder.read_int() for _ in range(coder.read_int())]
            for _ in range(_slots(coder))
        ]
        self.unknown7 = coder.read(0x1D)
        self.unknown8 = [coder.read_string() for _ in range(100)]

        indicator = coder.read_byte()
        if indicator != 0x91:
            raise WolfFormatError(f"expected 0x91, got {indicator:#04x}")
        self.unknown9 = coder.read_string()

        indicator = coder.read_byte()
        if indicator == 0x91:
            self.unknown10 = None
            self.unknown12 = None
            return
        if indicator != 0x92:
            raise WolfFormatError(f"expected 0x92, got {indicator:#04x}")
        self.unknown10 = coder.read_string()
        self.unknown12 = coder.read_int()
        indicator = coder.read_byte()
        if indicator != 0x92:
            raise WolfFormatError(f"expected trailing 0x92, got {indicator:#04x}")

    def dump(self, coder: FileCoder) -> None:
        coder.write_byte(EVENT_INDICATOR)
        coder.write_int(self.id)
        coder.write_int(self.unknown1)
        coder.write(self.unknown2)
        coder.write_string(self.name)
        coder.write_int(len(self.commands))
        for command in self.commands:
            command.dump(coder)
        coder.write_string(self.unknown11)
        coder.write_string(self.description)
        coder.write_byte(EVENT_TERMINATOR)

        coder.write_int(len(self.arg_names))
        for value in self.arg_names:
            coder.write_string(value)
        coder.write_int(len(self.unknown4))
        for value in self.unknown4:
            coder.write_byte(value)
        coder.write_int(len(self.arg_choices))
        for choices in self.arg_choices:
            coder.write_int(len(choices))
            for choice in choices:
                coder.write_string(choice)
        coder.write_int(len(self.unknown6))
        for values in self.unknown6:
            coder.write_int(len(values))
            for value in values:
                coder.write_int(value)
        coder.write(self.unknown7)
        for value in self.unknown8:
            coder.write_string(value)

        coder.write_byte(0x91)
        coder.write_string(self.unknown9)
        if self.unknown10 is None:
            coder.write_byte(0x91)
        else:
            coder.write_byte(0x92)
            coder.write_string(self.unknown10)
            coder.write_int(self.unknown12)
            coder.write_byte(0x92)


class CommonEvents:
    """The whole ``CommonEvent.dat`` file."""

    def __init__(self, path: str):
        self.path = path
        coder = FileCoder.for_read(path)
        self.magic = coder.verify_variant(MAGIC_NUMBER, MAGIC_VARIABLE)
        self.version = coder.read_byte()
        if self.version in (0x93, 0xCC):
            raise WolfFormatError(
                f"{path}: Wolf 3.5 packed CommonEvent.dat is not supported"
            )

        count = coder.read_int()
        self.events = [CommonEvent(coder) for _ in range(count)]

        self.terminator = coder.read_byte()
        if self.terminator < 0x89:
            raise WolfFormatError(
                f"{path}: terminator {self.terminator:#04x} is below 0x89"
            )
        if not coder.eof:
            raise WolfFormatError(
                f"{path}: {len(coder.data) - coder.offset} trailing bytes"
            )

    def dump(self, path: str) -> None:
        coder = FileCoder()
        coder.write(self.magic)
        coder.write_byte(self.version)
        coder.write_int(len(self.events))
        for event in self.events:
            event.dump(coder)
        coder.write_byte(self.terminator)
        coder.save(path)

    def iter_commands(self):
        """Yield ``(event, line_index, command)`` for every command."""
        for event in self.events:
            for line, command in enumerate(event.commands):
                yield event, line, command
