"""Wolf RPG Editor database parsing (``*.project`` + ``*.dat`` pairs).

Ported from wolftrans's ``lib/wolfrpg/database.rb``.

A database splits its schema and its contents across two files: the ``.project``
holds type/field/entry *names*, the ``.dat`` holds the actual values.  Both must
be parsed together because the ``.dat`` gives no clue which values are strings.
"""

from __future__ import annotations

from .filecoder import FileCoder, WolfFormatError

__all__ = ["Database", "DBType", "DBField", "DBData"]

DAT_SEED_INDICES = (0, 3, 9)
DAT_MAGIC_NUMBER = bytes([0x57, 0x00, 0x00, 0x4F, 0x4C, 0x00, 0x46, 0x4D, 0x00, 0xC1])
# Byte 5 is 0x00 in Wolf 2.x and 0x55 in Wolf 3.x; the trailing byte is the
# database format version, which the file terminator repeats.
DAT_MAGIC_VARIABLE = {5: frozenset({0x00, 0x55}), 9: frozenset({0xC1, 0xC2})}
DAT_TERMINATORS = frozenset({0xC1, 0xC2})
DAT_TYPE_SEPARATOR = bytes([0xFE, 0xFF, 0xFF, 0xFF])

STRING_START = 0x07D0
INT_START = 0x03E8


class DBField:
    """A column: a name plus an index that encodes whether it is int or string."""

    __slots__ = ("name", "type", "unknown1", "string_args", "args",
                 "default_value", "indexinfo")

    def __init__(self, coder: FileCoder):
        self.name = coder.read_string()
        self.type = 0
        self.unknown1 = b""
        self.string_args: list[bytes] = []
        self.args: list[int] = []
        self.default_value = 0
        self.indexinfo = 0

    @property
    def is_string(self) -> bool:
        return self.indexinfo >= STRING_START

    @property
    def index(self) -> int:
        return self.indexinfo - (STRING_START if self.is_string else INT_START)

    def dump_project(self, coder: FileCoder) -> None:
        coder.write_string(self.name)

    def read_dat(self, coder: FileCoder) -> None:
        self.indexinfo = coder.read_int()

    def dump_dat(self, coder: FileCoder) -> None:
        coder.write_int(self.indexinfo)


class DBData:
    """A row: a name plus parallel int and string value lists."""

    __slots__ = ("name", "int_values", "string_values", "fields")

    def __init__(self, coder: FileCoder):
        self.name = coder.read_string()
        self.int_values: list[int] = []
        self.string_values: list[bytes] = []
        self.fields: list[DBField] = []

    def dump_project(self, coder: FileCoder) -> None:
        coder.write_string(self.name)

    def read_dat(self, coder: FileCoder, fields: list[DBField]) -> None:
        self.fields = fields
        int_count = sum(1 for f in fields if not f.is_string)
        string_count = sum(1 for f in fields if f.is_string)
        self.int_values = [coder.read_int() for _ in range(int_count)]
        self.string_values = [coder.read_string() for _ in range(string_count)]

    def dump_dat(self, coder: FileCoder) -> None:
        for value in self.int_values:
            coder.write_int(value)
        for value in self.string_values:
            coder.write_string(value)

    def get(self, field: DBField):
        return (self.string_values if field.is_string else self.int_values)[field.index]

    def set(self, field: DBField, value) -> None:
        target = self.string_values if field.is_string else self.int_values
        target[field.index] = value

    def translatable_fields(self):
        """Yield ``(field, raw_value)`` for string columns holding plain text.

        Field ``type`` 0 is the editor's "String" column; other types are file
        paths, database references and the like, which must not be translated.
        """
        for field in self.fields:
            if not field.is_string or field.type != 0:
                continue
            if field.index >= len(self.string_values):
                continue
            value = self.string_values[field.index]
            if value:
                yield field, value


class DBType:
    """One database type (a table)."""

    __slots__ = ("name", "fields", "data", "description", "field_type_list_size",
                 "unknown1", "dat_field_count", "dat_data_count")

    def __init__(self, coder: FileCoder):
        self.name = coder.read_string()
        self.fields = [DBField(coder) for _ in range(coder.read_int())]
        self.data = [DBData(coder) for _ in range(coder.read_int())]
        self.description = coder.read_string()
        self.unknown1 = 0
        # The .dat may cover fewer fields/rows than the .project declares; the
        # project-side lists must stay intact so the .project round-trips.
        self.dat_field_count = len(self.fields)
        self.dat_data_count = len(self.data)

        # Field metadata lives in parallel arrays after the name blocks.
        self.field_type_list_size = coder.read_int()
        for field in self.fields:
            field.type = coder.read_byte()
        coder.skip(self.field_type_list_size - len(self.fields))

        for i in range(coder.read_int()):
            self.fields[i].unknown1 = coder.read_string()
        for i in range(coder.read_int()):
            self.fields[i].string_args = [
                coder.read_string() for _ in range(coder.read_int())
            ]
        for i in range(coder.read_int()):
            self.fields[i].args = [coder.read_int() for _ in range(coder.read_int())]
        for i in range(coder.read_int()):
            self.fields[i].default_value = coder.read_int()

    def dump_project(self, coder: FileCoder) -> None:
        coder.write_string(self.name)
        coder.write_int(len(self.fields))
        for field in self.fields:
            field.dump_project(coder)
        coder.write_int(len(self.data))
        for datum in self.data:
            datum.dump_project(coder)
        coder.write_string(self.description)

        coder.write_int(self.field_type_list_size)
        for field in self.fields:
            coder.write_byte(field.type)
        for _ in range(self.field_type_list_size - len(self.fields)):
            coder.write_byte(0)

        coder.write_int(len(self.fields))
        for field in self.fields:
            coder.write_string(field.unknown1)
        coder.write_int(len(self.fields))
        for field in self.fields:
            coder.write_int(len(field.string_args))
            for arg in field.string_args:
                coder.write_string(arg)
        coder.write_int(len(self.fields))
        for field in self.fields:
            coder.write_int(len(field.args))
            for arg in field.args:
                coder.write_int(arg)
        coder.write_int(len(self.fields))
        for field in self.fields:
            coder.write_int(field.default_value)

    @property
    def dat_fields(self) -> list[DBField]:
        return self.fields[:self.dat_field_count]

    @property
    def dat_data(self) -> list[DBData]:
        return self.data[:self.dat_data_count]

    def read_dat(self, coder: FileCoder) -> None:
        coder.verify(DAT_TYPE_SEPARATOR)
        self.unknown1 = coder.read_int()
        self.dat_field_count = coder.read_int()
        if self.dat_field_count > len(self.fields):
            raise WolfFormatError(
                f"type {self.name!r}: .dat declares {self.dat_field_count} fields "
                f"but .project only names {len(self.fields)}"
            )
        fields = self.dat_fields
        for field in fields:
            field.read_dat(coder)
        self.dat_data_count = coder.read_int()
        for datum in self.dat_data:
            datum.read_dat(coder, fields)

    def dump_dat(self, coder: FileCoder) -> None:
        coder.write(DAT_TYPE_SEPARATOR)
        coder.write_int(self.unknown1)
        coder.write_int(self.dat_field_count)
        for field in self.dat_fields:
            field.dump_dat(coder)
        coder.write_int(self.dat_data_count)
        for datum in self.dat_data:
            datum.dump_dat(coder)


class Database:
    """A ``.project`` / ``.dat`` database pair."""

    def __init__(self, project_path: str, dat_path: str):
        self.project_path = project_path
        self.dat_path = dat_path

        coder = FileCoder.for_read(project_path)
        self.types = [DBType(coder) for _ in range(coder.read_int())]
        self.project_trailer = coder.read()

        coder = FileCoder.for_read(dat_path, DAT_SEED_INDICES)
        self.crypt_header = coder.crypt_header
        self.dat_magic = DAT_MAGIC_NUMBER
        if coder.encrypted:
            self.unknown_encrypted_1 = coder.read_byte()
        else:
            self.unknown_encrypted_1 = None
            self.dat_magic = coder.verify_variant(
                DAT_MAGIC_NUMBER, DAT_MAGIC_VARIABLE)

        type_count = coder.read_int()
        if type_count != len(self.types):
            raise WolfFormatError(
                f"{dat_path}: type count mismatch "
                f"({len(self.types)} in .project vs {type_count} in .dat)"
            )
        for db_type in self.types:
            db_type.read_dat(coder)
        self.dat_terminator = coder.read_byte()
        if self.dat_terminator not in DAT_TERMINATORS:
            raise WolfFormatError(
                f"{dat_path}: terminator {self.dat_terminator:#04x} is not one of "
                f"{sorted(DAT_TERMINATORS)}"
            )
        self.dat_trailer = coder.read()

    def dump(self, project_path: str, dat_path: str) -> None:
        coder = FileCoder()
        coder.write_int(len(self.types))
        for db_type in self.types:
            db_type.dump_project(coder)
        coder.write(self.project_trailer)
        coder.save(project_path)

        coder = FileCoder(crypt_header=self.crypt_header, encryptable=True)
        if self.crypt_header is not None:
            coder.write_byte(self.unknown_encrypted_1)
        else:
            coder.write(self.dat_magic)
        coder.write_int(len(self.types))
        for db_type in self.types:
            db_type.dump_dat(coder)
        coder.write_byte(self.dat_terminator)
        coder.write(self.dat_trailer)
        coder.save(dat_path, DAT_SEED_INDICES)
