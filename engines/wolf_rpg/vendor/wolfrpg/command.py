"""Event command and move-route parsing for Wolf RPG Editor.

Ported from wolftrans's ``lib/wolfrpg/command.rb`` and ``route.rb``.
Command ID names come from vgperson's reverse-engineering notes.
"""

from __future__ import annotations

from .filecoder import FileCoder, WolfFormatError

__all__ = ["Command", "MoveCommand", "RouteCommand", "CID_NAMES", "read_command"]

ROUTE_TERMINATOR = b"\x01\x00"


class RouteCommand:
    """One step of a character move route.  Never contains text."""

    __slots__ = ("cid", "args")

    def __init__(self, cid: int, args: list[int]):
        self.cid = cid
        self.args = args

    @classmethod
    def read(cls, coder: FileCoder) -> "RouteCommand":
        cid = coder.read_byte()
        args = [coder.read_int() for _ in range(coder.read_byte())]
        coder.verify(ROUTE_TERMINATOR)
        return cls(cid, args)

    def dump(self, coder: FileCoder) -> None:
        coder.write_byte(self.cid)
        coder.write_byte(len(self.args))
        for arg in self.args:
            coder.write_int(arg)
        coder.write(ROUTE_TERMINATOR)


# Command IDs.  Only the ones that can hold player-visible text really matter
# for translation, but the full map makes exported entries readable.
CID_NAMES: dict[int, str] = {
    0: "Blank", 99: "Checkpoint",
    101: "Message", 102: "Choices", 103: "Comment",
    105: "ForceStopMessage", 106: "DebugMessage", 107: "ClearDebugText",
    111: "VariableCondition", 112: "StringCondition",
    121: "SetVariable", 122: "SetString", 123: "InputKey",
    124: "SetVariableEx", 125: "AutoInput", 126: "BanInput",
    130: "Teleport", 140: "Sound", 150: "Picture", 151: "ChangeColor",
    160: "SetTransition", 161: "PrepareTransition", 162: "ExecuteTransition",
    170: "StartLoop", 171: "BreakLoop", 172: "BreakEvent", 173: "EraseEvent",
    174: "ReturnToTitle", 175: "EndGame", 176: "LoopToStart",
    177: "StopNonPic", 178: "ResumeNonPic", 179: "LoopTimes", 180: "Wait",
    201: "Move", 202: "WaitForMove",
    210: "CommonEvent", 211: "CommonEventReserve",
    212: "SetLabel", 213: "JumpLabel",
    220: "SaveLoad", 221: "LoadGame", 222: "SaveGame",
    230: "MoveDuringEventOn", 231: "MoveDuringEventOff",
    240: "Chip", 241: "ChipSet", 242: "ChipOverwrite",
    250: "Database", 251: "ImportDatabase",
    270: "Party", 280: "MapEffect", 281: "ScrollScreen", 290: "Effect",
    300: "CommonEventByName",
    401: "ChoiceCase", 402: "SpecialChoiceCase",
    420: "ElseCase", 421: "CancelCase",
    498: "LoopEnd", 499: "BranchEnd",
}

# Picture (cid 150) subtypes, encoded in bits 4-6 of args[0].
PICTURE_FILE = 0
PICTURE_FILE_STRING = 1
PICTURE_TEXT = 2
PICTURE_WINDOW_FILE = 3
PICTURE_WINDOW_STRING = 4


class Command:
    """A single event command: an int arg list plus a string arg list."""

    __slots__ = ("cid", "args", "string_args", "indent")

    def __init__(self, cid: int, args: list[int], string_args: list[bytes], indent: int):
        self.cid = cid
        self.args = args
        self.string_args = string_args
        self.indent = indent

    # -- identity ----------------------------------------------------------

    @property
    def name(self) -> str:
        return CID_NAMES.get(self.cid, f"Unknown{self.cid}")

    @property
    def picture_type(self) -> int | None:
        """For cid 150, which flavour of Show Picture this is."""
        if self.cid != 150 or not self.args:
            return None
        return (self.args[0] >> 4) & 0x07

    # -- serialisation -----------------------------------------------------

    def dump(self, coder: FileCoder) -> None:
        coder.write_byte(len(self.args) + 1)
        coder.write_int(self.cid)
        for arg in self.args:
            coder.write_int(arg)
        coder.write_byte(self.indent)
        coder.write_byte(len(self.string_args))
        for arg in self.string_args:
            coder.write_string(arg)
        self.dump_terminator(coder)

    def dump_terminator(self, coder: FileCoder) -> None:
        coder.write_byte(0)


class MoveCommand(Command):
    """cid 201 — carries an inline move route after the string args."""

    __slots__ = ("unknown", "flags", "route")

    def __init__(self, cid, args, string_args, indent, coder: FileCoder):
        super().__init__(cid, args, string_args, indent)
        self.unknown = [coder.read_byte() for _ in range(5)]
        self.flags = coder.read_byte()
        self.route = [RouteCommand.read(coder) for _ in range(coder.read_int())]

    def dump_terminator(self, coder: FileCoder) -> None:
        coder.write_byte(1)
        for byte in self.unknown:
            coder.write_byte(byte)
        coder.write_byte(self.flags)
        coder.write_int(len(self.route))
        for cmd in self.route:
            cmd.dump(coder)


def read_command(coder: FileCoder) -> Command:
    """Read one command, returning a MoveCommand when a route follows."""
    arg_count = coder.read_byte() - 1
    cid = coder.read_int()
    args = [coder.read_int() for _ in range(arg_count)]
    indent = coder.read_byte()
    string_args = [coder.read_string() for _ in range(coder.read_byte())]

    terminator = coder.read_byte()
    if terminator == 0x01:
        return MoveCommand(cid, args, string_args, indent, coder)
    if terminator != 0x00:
        raise WolfFormatError(
            f"unexpected command terminator {terminator:#04x} "
            f"(cid {cid}) at offset {coder.offset - 1}"
        )
    return Command(cid, args, string_args, indent)
