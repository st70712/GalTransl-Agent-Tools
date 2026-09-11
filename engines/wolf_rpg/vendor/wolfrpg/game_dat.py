"""``Game.dat`` parsing — the game's title, fonts and startup settings.

Ported from wolftrans's ``lib/wolfrpg/game_dat.rb``.
"""

from __future__ import annotations

from .filecoder import FileCoder, WolfFormatError

__all__ = ["GameDat"]

SEED_INDICES = (0, 8, 6)
MAGIC_NUMBER = bytes([0x57, 0x00, 0x00, 0x4F, 0x4C, 0x00, 0x46, 0x4D, 0x00])
# The last byte is 0x00 in Wolf 2.x and 0x55 in Wolf 3.x.
MAGIC_VARIABLE = {8: frozenset({0x00, 0x55})}
MAGIC_STRING = b"0000-0000"


class GameDat:
    """``Data/BasicData/Game.dat``."""

    def __init__(self, path: str):
        self.path = path
        coder = FileCoder.for_read(path, SEED_INDICES)
        self.crypt_header = coder.crypt_header
        self.magic = MAGIC_NUMBER
        if not coder.encrypted:
            self.magic = coder.verify_variant(MAGIC_NUMBER, MAGIC_VARIABLE)

        self.unknown1 = coder.read_byte_array()
        self.file_version = coder.read_int()
        self.title = coder.read_string()

        magic = coder.read_string()
        if magic != MAGIC_STRING:
            raise WolfFormatError(
                f"{path}: magic string invalid (got {magic!r})"
            )

        self.unknown2 = coder.read_byte_array()
        self.font = coder.read_string()
        self.subfonts = [coder.read_string() for _ in range(3)]
        self.default_pc_graphic = coder.read_string()
        self.version = coder.read_string() if self.file_version >= 9 else b""

        # In Wolf 2.x this int is the file size minus one, so it has to be
        # recomputed if anything above it changes length.  Wolf 3.x puts an
        # unrelated small value here (0x14 in the games seen so far), so only
        # recompute when the value really does describe this file.
        self.size_field = coder.read_int()
        self.size_field_is_length = (
            self.size_field == len(coder.data) + coder.prefix_size - 1
        )
        self.trailer = coder.read()

    def dump(self, path: str) -> None:
        coder = FileCoder(crypt_header=self.crypt_header, encryptable=True)
        if self.crypt_header is None:
            coder.write(self.magic)

        coder.write_byte_array(self.unknown1)
        coder.write_int(self.file_version)
        coder.write_string(self.title)
        coder.write_string(MAGIC_STRING)
        coder.write_byte_array(self.unknown2)
        coder.write_string(self.font)
        for subfont in self.subfonts:
            coder.write_string(subfont)
        coder.write_string(self.default_pc_graphic)
        if self.file_version >= 9:
            coder.write_string(self.version)
        if self.size_field_is_length:
            coder.write_int(coder.write_tell() + 4 + len(self.trailer) - 1)
        else:
            coder.write_int(self.size_field)
        coder.write(self.trailer)
        coder.save(path, SEED_INDICES)
