"""DXA (DX Library Archive) version 8 reader — the format used by ``Data.wolf``.

Ported from the DXArchive.cpp / Huffman.cpp reference implementation bundled with
WolfDec (https://github.com/Sinflower/WolfDec), which in turn is Yamada Takumi's
DX Library archiver.

Only *decoding* is implemented: a Chinese patch never needs to rebuild the
archive, because the Wolf engine reads a loose file from disk in preference to
the archived copy.

Layout of a v8 archive::

    DARC_HEAD (64 bytes, stored in the clear)
    file data ...
    [ header block: name table / file table / directory table ]

The header block sits at ``file_name_table_start`` and runs to EOF.  It is
XOR-masked with the archive key, then Huffman-decoded, then LZ-decoded.  Each
file's data is XOR-masked with a *per-file* key derived from the archive key
plus the file's own uppercased name and the names of its parent directories.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import BinaryIO, Iterator

__all__ = [
    "DXA_KEYS",
    "DXArchive",
    "DXArchiveError",
    "huffman_decode",
    "lz_decode",
]


class DXArchiveError(Exception):
    """Raised when an archive cannot be parsed or decrypted."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DXA_HEAD = 0x5844  # 'DX' little-endian
DXA_VER = 0x0008
DXA_KEY_BYTES = 7
DXA_KEY_STRING_LENGTH = 63
DXA_KEY_STRING_MAXLENGTH = 2048

FLAG_NO_KEY = 0x00000001
FLAG_NO_HEAD_PRESS = 0x00000002

FILE_ATTRIBUTE_DIRECTORY = 0x00000010

NO_PRESS = 0xFFFFFFFFFFFFFFFF  # sentinel for "not compressed"
MIN_COMPRESS = 4

DEFAULT_KEY_STRING = b"DXBDXARC"

# Known archive keys, in the order WolfDec tries them.  Only the entries that
# use the v8 codec are listed here; v2.01/v2.10/v2.20 archives use the older
# DXArchive Ver5/Ver6 codecs and are rejected by this module with a clear error.
DXA_KEYS: dict[str, bytes] = {
    "Wolf RPG v2.281": b"WLFRPrO!p(;s5((8P@((UFWlu$#5(=",
    "Wolf RPG v3.10": bytes(
        [
            0x0F, 0x53, 0xE1, 0x3E, 0x8E, 0xB5, 0x41, 0x91, 0x52, 0x16,
            0x55, 0xAE, 0x34, 0xC9, 0x8F, 0x79, 0x59, 0x2F, 0x59, 0x6B,
            0x95, 0x19, 0x9B, 0x1B, 0x35, 0x9A, 0x2F, 0xDE, 0xC9, 0x7C,
            0x12, 0x96, 0xC3, 0x14, 0xB5, 0x0F, 0x53, 0xE1, 0x3E, 0x8E,
        ]
    ),
    "Wolf RPG v3.173": bytes(
        [
            0x31, 0xF9, 0x01, 0x36, 0xA3, 0xE3, 0x8D, 0x3C, 0x7B, 0xC3,
            0x7D, 0x25, 0xAD, 0x63, 0x28, 0x19, 0x1B, 0xF7, 0x8E, 0x6C,
            0xC4, 0xE5, 0xE2, 0x76, 0x82, 0xEA, 0x4F, 0xED, 0x61, 0xDA,
            0xE0, 0x44, 0x5B, 0xB6, 0x46, 0x3B, 0x06, 0xD5, 0xCE, 0xB6,
            0x78, 0x58, 0xD0, 0x7C, 0x82,
        ]
    ),
    "One Way Heroics": b"nGui9('&1=@3#a",
    "One Way Heroics Plus": b"Ph=X3^]o2A(,1=@3#a",
    "DX Library default": DEFAULT_KEY_STRING,
}


# ---------------------------------------------------------------------------
# Key derivation
# ---------------------------------------------------------------------------

def _crc32_table() -> list[int]:
    table = []
    for i in range(256):
        data = i
        for _ in range(8):
            b = data & 1
            data >>= 1
            if b:
                data ^= 0xEDB88320
        table.append(data)
    return table


_CRC32 = _crc32_table()


def hash_crc32(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for byte in data:
        crc = _CRC32[(crc ^ byte) & 0xFF] ^ (crc >> 8)
    return crc ^ 0xFFFFFFFF


def key_create(source: bytes) -> bytes:
    """Derive the 7-byte XOR key from a key string (DXArchive::KeyCreate)."""
    if len(source) < 4:
        source = source + DEFAULT_KEY_STRING
    even = source[0::2]
    odd = source[1::2]
    crc0 = hash_crc32(even)
    crc1 = hash_crc32(odd)
    return bytes(
        [
            crc0 & 0xFF,
            (crc0 >> 8) & 0xFF,
            (crc0 >> 16) & 0xFF,
            (crc0 >> 24) & 0xFF,
            crc1 & 0xFF,
            (crc1 >> 8) & 0xFF,
            (crc1 >> 16) & 0xFF,
        ]
    )


def key_conv(data: bytes | bytearray, position: int, key: bytes | None) -> bytes:
    """XOR ``data`` with the repeating 7-byte ``key``, phased at ``position``."""
    if key is None or not data:
        return bytes(data)
    start = position % DXA_KEY_BYTES
    rotated = key[start:] + key[:start]
    reps = -(-len(data) // DXA_KEY_BYTES)
    mask = (rotated * reps)[: len(data)]
    data = bytes(data)
    return (
        int.from_bytes(data, "big") ^ int.from_bytes(mask, "big")
    ).to_bytes(len(data), "big")


# ---------------------------------------------------------------------------
# LZ decoder (DXArchive::Decode)
# ---------------------------------------------------------------------------

def lz_decode(src: bytes, offset: int = 0) -> bytes:
    dest_size = struct.unpack_from("<I", src, offset)[0]
    src_size = struct.unpack_from("<I", src, offset + 4)[0] - 9
    keycode = src[offset + 8]

    dest = bytearray(dest_size)
    dp = 0
    sp = offset + 9
    end = sp + src_size

    while sp < end:
        if src[sp] != keycode:
            dest[dp] = src[sp]
            dp += 1
            sp += 1
            continue

        if src[sp + 1] == keycode:
            dest[dp] = keycode
            dp += 1
            sp += 2
            continue

        code = src[sp + 1]
        if code > keycode:
            code -= 1
        sp += 2

        conbo = code >> 3
        if code & 0x4:
            conbo |= src[sp] << 5
            sp += 1
        conbo += MIN_COMPRESS

        index_size = code & 0x3
        if index_size == 0:
            index = src[sp]
            sp += 1
        elif index_size == 1:
            index = struct.unpack_from("<H", src, sp)[0]
            sp += 2
        else:
            index = struct.unpack_from("<H", src, sp)[0] | (src[sp + 2] << 16)
            sp += 3
        index += 1

        if index < conbo:
            # Overlapping run: copy in doubling chunks, exactly like the original.
            num = index
            while conbo > num:
                dest[dp:dp + num] = dest[dp - num:dp]
                dp += num
                conbo -= num
                num += num
            if conbo:
                dest[dp:dp + conbo] = dest[dp - num:dp - num + conbo]
                dp += conbo
        else:
            dest[dp:dp + conbo] = dest[dp - index:dp - index + conbo]
            dp += conbo

    return bytes(dest)


# ---------------------------------------------------------------------------
# Huffman decoder (Huffman_Decode)
# ---------------------------------------------------------------------------

class _BitWriter:
    """MSB-first bit writer, matching BitStream_Write in the reference source."""

    __slots__ = ("buf", "bits")

    def __init__(self):
        self.buf = bytearray([0])
        self.bits = 0

    def write(self, bit_num: int, value: int) -> None:
        for i in range(bit_num):
            bit = (value >> (bit_num - 1 - i)) & 1
            self.buf[-1] |= bit << (7 - self.bits)
            self.bits += 1
            if self.bits == 8:
                self.bits = 0
                self.buf.append(0)

    def getvalue(self) -> bytes:
        # BitStream_GetBytes: partial trailing byte counts as one byte.
        return bytes(self.buf if self.bits else self.buf[:-1])


def _bit_num(value: int) -> int:
    """BitStream_GetBitNum: smallest i in 1..63 with value < (1 << i), else 64."""
    for i in range(1, 64):
        if value < (1 << i):
            return i
    return 64


class _BitReader:
    __slots__ = ("buf", "bytes_", "bits")

    def __init__(self, buf: bytes, offset: int = 0):
        self.buf = buf
        self.bytes_ = offset
        self.bits = 0

    def read(self, bit_num: int) -> int:
        result = 0
        buf = self.buf
        for i in range(bit_num):
            result |= ((buf[self.bytes_] >> (7 - self.bits)) & 1) << (bit_num - 1 - i)
            self.bits += 1
            if self.bits == 8:
                self.bytes_ += 1
                self.bits = 0
        return result

    def consumed_bytes(self, origin: int) -> int:
        return self.bytes_ - origin + (1 if self.bits else 0)


def _huffman_header(press: bytes, offset: int) -> tuple[int, int, list[int], int]:
    """Read the size fields and the 256-entry weight table."""
    br = _BitReader(press, offset)
    original_size = br.read(br.read(6) + 1)
    press_size = br.read(br.read(6) + 1)

    weight = [0] * 256
    bit_num = (br.read(3) + 1) * 2
    br.read(1)  # sign bit, unused for entry 0
    weight[0] = br.read(bit_num)
    for i in range(1, 256):
        bit_num = (br.read(3) + 1) * 2
        minus = br.read(1)
        save = br.read(bit_num)
        weight[i] = (weight[i - 1] - save) if minus else (weight[i - 1] + save)

    return original_size, press_size, weight, br.consumed_bytes(offset)


def huffman_decoded_size(press: bytes, offset: int = 0) -> int:
    return _huffman_header(press, offset)[0]


def _build_tree(weight: list[int]) -> tuple[list[int], list[list[int]], list[int], list[int]]:
    """Rebuild the canonical DX Library Huffman tree from the weight table.

    Returns ``(parent, child, index, bit_num)`` for the 511-node array.  The
    node-selection order (scan from 0, strict ``>`` comparisons) is reproduced
    exactly, because it determines the code assignment.
    """
    total = 256 + 255
    node_weight = weight + [0] * 255
    parent = [-1] * total
    child = [[-1, -1] for _ in range(total)]
    index = [0] * total

    data_num = 256
    node_num = 256
    while data_num > 1:
        min1 = -1
        min2 = -1
        node_index = 0
        seen = 0
        while seen < data_num:
            if parent[node_index] != -1:
                node_index += 1
                continue
            seen += 1
            if min1 == -1 or node_weight[min1] > node_weight[node_index]:
                min2 = min1
                min1 = node_index
            elif min2 == -1 or node_weight[min2] > node_weight[node_index]:
                min2 = node_index
            node_index += 1

        parent[node_num] = -1
        node_weight[node_num] = node_weight[min1] + node_weight[min2]
        child[node_num][0] = min1
        child[node_num][1] = min2
        index[min1] = 0
        index[min2] = 1
        parent[min1] = node_num
        parent[min2] = node_num
        node_num += 1
        data_num -= 1

    # Walk each node up to the root to recover its code, then reverse it so the
    # bits read low-to-high off the stream lead back down from the root.
    bit_num = [0] * total
    code = [0] * total
    for i in range(256 + 254):
        bits: list[int] = []
        n = i
        while parent[n] != -1:
            bits.append(index[n])
            n = parent[n]
        bit_num[i] = len(bits)
        # `bits` is leaf->root; the stream is read root->leaf, LSB first.
        value = 0
        for pos, bit in enumerate(reversed(bits)):
            value |= bit << pos
        code[i] = value

    return parent, child, bit_num, code


def huffman_encode(src: bytes) -> bytes:
    """Compress ``src`` into the DX Library Huffman format.

    Ported from Huffman_Encode.  The frequency table is rescaled to 0..65535
    before the tree is built, exactly as the reference does -- the decoder
    rebuilds the tree from those rescaled weights, so any deviation would make
    the two sides disagree on the code assignment.
    """
    if not src:
        return b""

    counts = [0] * 256
    for byte in src:
        counts[byte] += 1
    weight = [c * 0xFFFF // len(src) for c in counts]

    _parent, _child, bit_num, code = _build_tree(weight)

    # Body: each symbol's code, written LSB-first into LSB-first packed bytes.
    body = bytearray([0])
    bit_pos = 0
    for byte in src:
        value = code[byte]
        for i in range(bit_num[byte]):
            if bit_pos == 8:
                body.append(0)
                bit_pos = 0
            body[-1] |= ((value >> i) & 1) << bit_pos
            bit_pos += 1
    press_size = len(body)

    # Header: sizes, then the 256 weight deltas.
    bw = _BitWriter()
    n = _bit_num(len(src))
    if n > 0:
        n -= 1
    bw.write(6, n)
    bw.write(n + 1, len(src))

    n = _bit_num(press_size)
    bw.write(6, n)
    bw.write(n + 1, press_size)

    previous = 0
    for i in range(256):
        delta = weight[i] - previous
        previous = weight[i]
        minus = delta < 0
        value = -delta if minus else delta
        n = (_bit_num(value) + 1) // 2
        if n > 0:
            n -= 1
        bw.write(3, n)
        bw.write(1, 1 if minus else 0)
        bw.write((n + 1) * 2, value)

    return bw.getvalue() + bytes(body)


def lz_encode_stored(src: bytes) -> bytes:
    """Wrap ``src`` in a valid LZ stream that contains no back-references.

    ``lz_decode`` (and the engine's ``DXArchive::Decode``) accepts a stream made
    entirely of literals, so the header block can be put into the expected
    container without implementing a match finder.  Only the escape byte has to
    be doubled, and it is chosen as the rarest byte to keep that cost near zero.
    """
    counts = [0] * 256
    for byte in src:
        counts[byte] += 1
    keycode = min(range(256), key=lambda b: counts[b])

    body = bytearray()
    key_byte = bytes([keycode])
    for byte in src:
        body.append(byte)
        if byte == keycode:
            body.append(keycode)

    return (
        struct.pack("<I", len(src))
        + struct.pack("<I", len(body) + 9)
        + key_byte
        + bytes(body)
    )


def huffman_decode(press: bytes, offset: int = 0) -> bytes:
    original_size, _press_size, weight, head_size = _huffman_header(press, offset)
    if original_size == 0:
        return b""

    parent, child, bit_num, code = _build_tree(weight)

    # Fast path: a 9-bit lookup table resolves any code of length <= 9 in one
    # step, mirroring NodeIndexTable in the reference implementation.
    node_index_table = [-1] * 512
    for i in range(512):
        for j in range(256 + 254):
            nb = bit_num[j]
            if nb > 9 or nb == 0:
                continue
            mask = (1 << nb) - 1
            if (i & mask) == (code[j] & mask):
                node_index_table[i] = j
                break

    data = press[offset + head_size:]
    dest = bytearray(original_size)

    press_pos = 0
    bit_counter = 0
    bit_data = data[0]
    tail_start = original_size - 17

    for out_pos in range(original_size):
        if out_pos >= tail_start:
            node = 510
        else:
            if bit_counter == 8:
                press_pos += 1
                bit_data = data[press_pos]
                bit_counter = 0

            bit_data = (bit_data | (data[press_pos + 1] << (8 - bit_counter))) & 0x1FF
            node = node_index_table[bit_data]

            bit_counter += bit_num[node]
            if bit_counter >= 16:
                press_pos += 2
                bit_counter -= 16
                bit_data = data[press_pos] >> bit_counter
            elif bit_counter >= 8:
                press_pos += 1
                bit_counter -= 8
                bit_data = data[press_pos] >> bit_counter
            else:
                bit_data >>= bit_num[node]

        while node > 255:
            if bit_counter == 8:
                press_pos += 1
                bit_data = data[press_pos]
                bit_counter = 0
            node = child[node][bit_data & 1]
            bit_data >>= 1
            bit_counter += 1

        dest[out_pos] = node

    return bytes(dest)


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------

@dataclass
class DXAEntry:
    """One file inside the archive."""

    path: str                 # '/'-joined path, original casing
    name: str
    data_address: int
    data_size: int
    press_data_size: int
    huff_press_data_size: int
    attributes: int
    header_offset: int = 0    # byte offset of this DARC_FILEHEAD in the file table
    _key: bytes = field(repr=False, default=b"")

    @property
    def is_compressed(self) -> bool:
        return self.press_data_size != NO_PRESS

    @property
    def is_huffman(self) -> bool:
        return self.huff_press_data_size != NO_PRESS

    def stored_size(self, huffman_encode_kb: int) -> int:
        """Bytes this entry actually occupies in the archive's data region."""
        if self.data_size == 0:
            return 0
        head_tail = huffman_encode_kb * 1024 * 2
        if self.is_compressed:
            if self.is_huffman:
                extra = (self.press_data_size - head_tail
                         if huffman_encode_kb != 0xFF and self.press_data_size > head_tail
                         else 0)
                return self.huff_press_data_size + extra
            return self.press_data_size
        if self.is_huffman:
            extra = (self.data_size - head_tail
                     if huffman_encode_kb != 0xFF and self.data_size > head_tail
                     else 0)
            return self.huff_press_data_size + extra
        return self.data_size


@dataclass
class _Header:
    version: int
    head_size: int
    data_start: int
    name_table_start: int
    file_table_start: int
    directory_table_start: int
    char_code_format: int
    flags: int
    huffman_encode_kb: int

    @property
    def no_key(self) -> bool:
        return bool(self.flags & FLAG_NO_KEY)

    @property
    def no_head_press(self) -> bool:
        return bool(self.flags & FLAG_NO_HEAD_PRESS)


_HEAD_STRUCT = struct.Struct("<HHIQQQQIIB15s")


class DXArchive:
    """Read-only view over a DXA v8 archive such as ``Data.wolf``."""

    def __init__(self, path: str, key_string: bytes | None = None):
        self.path = path
        self._fp: BinaryIO = open(path, "rb")
        try:
            self.header = self._read_header()
            self.key_string = self._resolve_key(key_string)
            self.key = key_create(self.key_string)
            self._read_tables()
        except Exception:
            self._fp.close()
            raise

    # -- construction ------------------------------------------------------

    def _read_header(self) -> _Header:
        self._fp.seek(0)
        raw = self._fp.read(_HEAD_STRUCT.size)
        (
            head, version, head_size, data_start, name_table_start,
            file_table_start, directory_table_start, char_code_format,
            flags, huffman_kb, _reserve,
        ) = _HEAD_STRUCT.unpack(raw)

        if head != DXA_HEAD:
            raise DXArchiveError(f"{self.path}: not a DX archive (magic {head:#06x})")
        if version != DXA_VER:
            raise DXArchiveError(
                f"{self.path}: DXA version {version} is not supported "
                f"(this reader handles version {DXA_VER} only). "
                "Older Wolf RPG archives (v2.01/2.10/2.20) use a different codec."
            )

        self._fp.seek(0, 2)
        self.file_size = self._fp.tell()

        return _Header(
            version, head_size, data_start, name_table_start,
            file_table_start, directory_table_start, char_code_format,
            flags, huffman_kb,
        )

    def _raw_head_block(self) -> bytes:
        self._fp.seek(self.header.name_table_start)
        return self._fp.read(self.file_size - self.header.name_table_start)

    def _resolve_key(self, key_string: bytes | None) -> bytes:
        """Return the archive key string, brute-forcing the known list if needed."""
        if self.header.no_key:
            return b""
        if key_string is not None:
            return key_string[:DXA_KEY_STRING_LENGTH]

        raw = self._raw_head_block()
        for name, candidate in DXA_KEYS.items():
            trimmed = candidate[:DXA_KEY_STRING_LENGTH]
            if self._try_key(raw, key_create(trimmed)):
                self.detected_key_name = name
                return trimmed
        raise DXArchiveError(
            f"{self.path}: none of the known Wolf RPG keys decrypt this archive. "
            "Pass an explicit key with --key."
        )

    def _try_key(self, raw: bytes, key: bytes) -> bool:
        """Does this key turn the header block into a well-formed table?"""
        if self.header.no_head_press:
            self._head_buffer = key_conv(raw, 0, key)[: self.header.head_size]
            return True
        try:
            plain = key_conv(raw, 0, key)
            # Cheap gate first: the Huffman stream announces its own sizes, and
            # a wrong key almost always yields absurd ones.
            lz_size, press_size, _weight, _hs = _huffman_header(plain, 0)
            # The LZ stream sits between Huffman and the final table, and an
            # uncompressed-literal LZ stream is slightly *larger* than the table
            # it wraps, so the bound has to be generous rather than exact.
            if not 0 < lz_size <= self.header.head_size * 4 + 4096:
                return False
            if not 0 < press_size <= len(plain):
                return False
            head = lz_decode(huffman_decode(plain))
        except (IndexError, ValueError, struct.error, MemoryError, OverflowError):
            return False
        if len(head) != self.header.head_size:
            return False
        self._head_buffer = head
        return True

    def _read_tables(self) -> None:
        head = getattr(self, "_head_buffer", None)
        if head is None:
            raw = self._raw_head_block()
            plain = key_conv(raw, 0, None if self.header.no_key else self.key)
            if self.header.no_head_press:
                head = plain[: self.header.head_size]
            else:
                head = lz_decode(huffman_decode(plain))
        self._name_table = head
        self._file_table_off = self.header.file_table_start
        self._dir_table_off = self.header.directory_table_start

        self.entries: list[DXAEntry] = []
        self._walk_directory(0, "", [])

    # -- name table --------------------------------------------------------

    def _name_at(self, address: int) -> tuple[str, bytes, bytes]:
        """Return (original-case name, uppercase bytes, original bytes)."""
        buf = self._name_table
        length = struct.unpack_from("<H", buf, address)[0] * 4
        upper_start = address + 4
        upper = buf[upper_start:upper_start + length]
        upper = upper.split(b"\0", 1)[0]
        orig_start = upper_start + length
        orig = buf[orig_start:orig_start + length]
        orig = orig.split(b"\0", 1)[0]
        encoding = _codepage_to_encoding(self.header.char_code_format)
        return orig.decode(encoding, errors="replace"), upper, orig

    # -- directory walk ----------------------------------------------------

    _DIR_STRUCT = struct.Struct("<QQQQ")
    _FILE_STRUCT = struct.Struct("<QQQQQQQQQ")  # name, attr, 3x time, addr, size, press, huff

    def _walk_directory(self, dir_offset: int, prefix: str, upper_chain: list[bytes]) -> None:
        (
            directory_address,
            parent_directory_address,
            file_head_num,
            file_head_address,
        ) = self._DIR_STRUCT.unpack_from(self._name_table, self._dir_table_off + dir_offset)

        for i in range(file_head_num):
            off = self._file_table_off + file_head_address + i * self._FILE_STRUCT.size
            (
                name_address, attributes, _t_create, _t_access, _t_write,
                data_address, data_size, press_data_size, huff_press_data_size,
            ) = self._FILE_STRUCT.unpack_from(self._name_table, off)

            name, upper, _orig = self._name_at(name_address)
            child_path = f"{prefix}{name}"

            if attributes & FILE_ATTRIBUTE_DIRECTORY:
                self._walk_directory(
                    data_address, child_path + "/", upper_chain + [upper]
                )
            else:
                self.entries.append(
                    DXAEntry(
                        path=child_path,
                        name=name,
                        data_address=data_address,
                        data_size=data_size,
                        press_data_size=press_data_size,
                        huff_press_data_size=huff_press_data_size,
                        attributes=attributes,
                        header_offset=file_head_address + i * self._FILE_STRUCT.size,
                        _key=self._file_key(upper, upper_chain),
                    )
                )

    def _file_key(self, upper_name: bytes, upper_chain: list[bytes]) -> bytes:
        """Per-file key: archive key string + uppercase filename + parent dirs.

        Mirrors DXArchive::CreateKeyFileString, which concatenates the file's
        own uppercased name and then walks up the directory chain appending each
        parent's uppercased name.
        """
        if self.header.no_key:
            return b""
        buf = bytearray(self.key_string)
        buf += upper_name
        for parent in reversed(upper_chain):
            buf += parent
        return key_create(bytes(buf))

    # -- extraction --------------------------------------------------------

    def read(self, entry: DXAEntry) -> bytes:
        """Return the decrypted, decompressed contents of ``entry``."""
        if entry.data_size == 0:
            return b""

        key = None if self.header.no_key else entry._key
        huff_kb = self.header.huffman_encode_kb
        self._fp.seek(self.header.data_start + entry.data_address)

        if entry.is_compressed:
            if entry.is_huffman:
                raw = key_conv(
                    self._fp.read(entry.huff_press_data_size), entry.data_size, key
                )
                lz = bytearray(huffman_decode(raw))
                if huff_kb != 0xFF and entry.press_data_size > huff_kb * 1024 * 2:
                    # Only the head and tail were Huffman-packed; the middle is
                    # still sitting in the archive, LZ-compressed but raw.
                    head_kb = huff_kb * 1024
                    middle_len = entry.press_data_size - head_kb * 2
                    middle = key_conv(
                        self._fp.read(middle_len),
                        entry.data_size + entry.huff_press_data_size,
                        key,
                    )
                    lz = bytearray(lz[:head_kb]) + bytearray(middle) + bytearray(lz[head_kb:])
                return lz_decode(bytes(lz))[: entry.data_size]

            raw = key_conv(self._fp.read(entry.press_data_size), entry.data_size, key)
            return lz_decode(raw)[: entry.data_size]

        if entry.is_huffman:
            raw = key_conv(
                self._fp.read(entry.huff_press_data_size), entry.data_size, key
            )
            out = bytearray(huffman_decode(raw))
            if huff_kb != 0xFF and entry.data_size > huff_kb * 1024 * 2:
                head_kb = huff_kb * 1024
                middle_len = entry.data_size - head_kb * 2
                middle = key_conv(
                    self._fp.read(middle_len),
                    entry.data_size + entry.huff_press_data_size,
                    key,
                )
                out = bytearray(out[:head_kb]) + bytearray(middle) + bytearray(out[head_kb:])
            return bytes(out[: entry.data_size])

        return key_conv(self._fp.read(entry.data_size), entry.data_size, key)

    # -- misc --------------------------------------------------------------

    def __iter__(self) -> Iterator[DXAEntry]:
        return iter(self.entries)

    def close(self) -> None:
        self._fp.close()

    def __enter__(self) -> "DXArchive":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _codepage_to_encoding(codepage: int) -> str:
    return {
        932: "cp932",
        936: "cp936",
        949: "cp949",
        950: "cp950",
        65001: "utf-8",
        1200: "utf-16-le",
    }.get(codepage, "cp932")
