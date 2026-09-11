"""Binary reader/writer for Wolf RPG Editor data files.

Ported from wolftrans's ``lib/wolfrpg/filecoder.rb``.

Strings are kept as **raw bytes** throughout the object model rather than being
decoded on read.  That matters for patching: an entry the translator never
touched is written back byte-for-byte, so a partially translated game file is
guaranteed to differ from the original only where a translation was supplied.
Decoding happens at the export boundary, encoding at the import boundary.
"""

from __future__ import annotations

import struct


__all__ = ["FileCoder", "WolfFormatError", "decode_str", "encode_str"]

CRYPT_HEADER_SIZE = 10
DECRYPT_INTERVALS = (1, 2, 5)


class WolfFormatError(Exception):
    """Raised when a data file does not match the expected layout."""


def decode_str(raw: bytes, encoding: str = "cp932") -> str:
    """Decode a raw Wolf string for display/export."""
    return raw.decode(encoding, errors="replace")


def encode_str(text: str, encoding: str = "cp932") -> bytes:
    """Encode a translated string back to the game's codepage."""
    return text.encode(encoding)


class FileCoder:
    """Sequential reader/writer over a Wolf data file.

    Some files (``Game.dat``, ``*.dat`` databases) may be obfuscated with a
    10-byte header whose bytes seed three LCG keystreams.  ``seed_indices``
    selects which header bytes are the seeds; passing it enables the check.
    """

    def __init__(self, data: bytes = b"", crypt_header: bytes | None = None,
                 encryptable: bool = False):
        self.data = data
        self.offset = 0
        self.crypt_header = crypt_header
        self.encryptable = encryptable
        self.out = bytearray()

    # -- construction ------------------------------------------------------

    @classmethod
    def for_read(cls, path: str, seed_indices: tuple[int, ...] | None = None) -> "FileCoder":
        with open(path, "rb") as fp:
            blob = fp.read()

        if seed_indices is None:
            return cls(blob)

        # A leading 0x00 means "not obfuscated"; anything else is the first
        # byte of the crypt header.
        if blob[0] == 0:
            return cls(blob[1:], encryptable=True)

        header = blob[:CRYPT_HEADER_SIZE]
        seeds = [header[i] for i in seed_indices]
        return cls(cls.crypt(blob[CRYPT_HEADER_SIZE:], seeds),
                   crypt_header=header, encryptable=True)

    @property
    def encrypted(self) -> bool:
        return self.crypt_header is not None

    @property
    def prefix_size(self) -> int:
        """Bytes that precede the body in the on-disk image.

        Offsets recorded *inside* a file (such as Game.dat's size field) count
        from the true start of the file, so they must include the crypt header
        or the single 0x00 "not obfuscated" marker.
        """
        if self.encrypted:
            return CRYPT_HEADER_SIZE
        return 1 if self.encryptable else 0

    # -- primitive reads ---------------------------------------------------

    def read(self, size: int | None = None) -> bytes:
        if size is None:
            chunk = self.data[self.offset:]
            self.offset = len(self.data)
            return chunk
        if self.offset + size > len(self.data):
            raise WolfFormatError(
                f"read past end of file (want {size} bytes at {self.offset}, "
                f"have {len(self.data) - self.offset})"
            )
        chunk = self.data[self.offset:self.offset + size]
        self.offset += size
        return chunk

    def read_byte(self) -> int:
        return self.read(1)[0]

    def read_int(self) -> int:
        return struct.unpack("<i", self.read(4))[0]

    def read_uint(self) -> int:
        return struct.unpack("<I", self.read(4))[0]

    def read_string(self) -> bytes:
        """Read a length-prefixed, NUL-terminated string as raw bytes."""
        size = self.read_int()
        if size <= 0:
            raise WolfFormatError(f"string of size {size} at offset {self.offset - 4}")
        raw = self.read(size - 1)
        terminator = self.read_byte()
        if terminator != 0:
            raise WolfFormatError(
                f"string not NUL-terminated at offset {self.offset - 1} "
                f"(got {terminator:#04x})"
            )
        return raw

    def read_byte_array(self) -> list[int]:
        return list(self.read(self.read_int()))

    def read_int_array(self) -> list[int]:
        count = self.read_int()
        return list(struct.unpack(f"<{count}i", self.read(count * 4)))

    def read_string_array(self) -> list[bytes]:
        return [self.read_string() for _ in range(self.read_int())]

    def verify(self, expected: bytes) -> None:
        got = self.read(len(expected))
        if got != expected:
            raise WolfFormatError(
                f"magic mismatch at offset {self.offset - len(expected)}: "
                f"expected {expected.hex(' ')}, got {got.hex(' ')}"
            )

    def verify_variant(self, expected: bytes,
                       variable: dict[int, frozenset[int]]) -> bytes:
        """Verify a magic that carries an editor-version byte inside it.

        Wolf 3.x stamps a version marker into positions that were fixed 0x00 in
        2.x (and bumps the trailing format byte of the databases).  ``variable``
        maps offsets *within the magic* to the values accepted there; every
        other position must match ``expected`` exactly.  The bytes actually read
        are returned so ``dump`` can put the file back the way it came in.
        """
        got = self.read(len(expected))
        for i, (want, have) in enumerate(zip(expected, got)):
            allowed = variable.get(i)
            bad = (have != want) if allowed is None else (have not in allowed)
            if bad:
                raise WolfFormatError(
                    f"magic mismatch at offset {self.offset - len(expected)}: "
                    f"expected {expected.hex(' ')} (byte {i} may be "
                    f"{sorted(allowed) if allowed else [want]}), "
                    f"got {got.hex(' ')}"
                )
        return got

    def peek(self, size: int) -> bytes:
        """Look at the next ``size`` bytes without consuming them."""
        return self.data[self.offset:self.offset + size]

    @property
    def remaining(self) -> int:
        return len(self.data) - self.offset

    def skip(self, size: int) -> None:
        self.offset += size

    @property
    def eof(self) -> bool:
        return self.offset >= len(self.data)

    def tell(self) -> int:
        return self.offset + self.prefix_size

    # -- primitive writes --------------------------------------------------

    def write(self, data: bytes) -> None:
        self.out += data

    def write_byte(self, value: int) -> None:
        self.out.append(value & 0xFF)

    def write_int(self, value: int) -> None:
        self.out += struct.pack("<i", value)

    def write_string(self, raw: bytes) -> None:
        self.write_int(len(raw) + 1)
        self.out += raw
        self.out.append(0)

    def write_byte_array(self, values: list[int]) -> None:
        self.write_int(len(values))
        self.out += bytes(v & 0xFF for v in values)

    def write_int_array(self, values: list[int]) -> None:
        self.write_int(len(values))
        self.out += struct.pack(f"<{len(values)}i", *values)

    def write_string_array(self, values: list[bytes]) -> None:
        self.write_int(len(values))
        for value in values:
            self.write_string(value)

    def write_tell(self) -> int:
        return len(self.out) + self.prefix_size

    def getvalue(self, seed_indices: tuple[int, ...] | None = None) -> bytes:
        """Return the finished file image, re-applying obfuscation if needed."""
        if self.encrypted:
            if seed_indices is None:
                raise ValueError("seed_indices are required to re-encrypt this file")
            seeds = [self.crypt_header[i] for i in seed_indices]
            return bytes(self.crypt_header) + self.crypt(bytes(self.out), seeds)
        if self.encryptable:
            # Left in the clear by this game: keep the 0x00 marker.
            return b"\x00" + bytes(self.out)
        return bytes(self.out)

    def save(self, path: str, seed_indices: tuple[int, ...] | None = None) -> None:
        with open(path, "wb") as fp:
            fp.write(self.getvalue(seed_indices))

    # -- obfuscation -------------------------------------------------------

    @staticmethod
    def crypt(data: bytes, seeds: list[int]) -> bytes:
        """Symmetric XOR obfuscation keyed by three LCG streams."""
        buf = bytearray(data)
        for slot, seed in enumerate(seeds):
            step = DECRYPT_INTERVALS[slot]
            for i in range(0, len(buf), step):
                seed = (seed * 0x343FD + 0x269EC3) & 0xFFFFFFFF
                buf[i] ^= (seed >> 28) & 7
        return bytes(buf)
