"""Read format metadata from an explicit little-endian ADAT sound-effect bank."""
import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import struct
from typing import BinaryIO

from paged_resource import PagedResource, Segment


@dataclass
class FormatGroup:
    sample_rate_hz: int
    codec_id: int
    streams: int = 0
    samples: int = 0


def read_formats(stream: BinaryIO, offset: int, size: int) -> list[FormatGroup]:
    bank = PagedResource(stream, [Segment(offset, size, size, "raw")])
    magic, flags, count, header_size = struct.unpack("<4sIII", bank.read(0, 16))
    if magic != b"ADAT" or flags not in (0xff000001, 0xff020001):
        raise ValueError("Expected little-endian ADAT v1 without indexing, streaming or encryption flags")
    if not 1 <= count <= 4096:
        raise ValueError("AWC stream count outside the 1 to 4096 inventory limit")
    table = 16 + 4 * count
    if not table <= header_size <= size:
        raise ValueError("AWC stream table outside declared header")
    entries = [word for word, in struct.iter_unpack("<I", bank.read(16, 4 * count))]
    if entries[0] & 0x1fffffff == 0:
        raise ValueError("Streamed AWC banks are unsupported")
    table_bytes = 8 * sum(word >> 29 for word in entries)
    if table + table_bytes > header_size:
        raise ValueError("AWC tag table outside declared header")
    tags = struct.iter_unpack("<Q", bank.read(table, table_bytes))
    formats: list[int] = []
    spans: list[tuple[int, int]] = []
    for entry in entries:
        data_tags = 0
        format_offsets = []
        for _ in range(entry >> 29):
            word, = next(tags)
            kind = word >> 56
            length = (word >> 28) & 0x0fffffff
            start = word & 0x0fffffff
            if not header_size <= start <= start + length <= size:
                raise ValueError("AWC tag outside supplied bank extent")
            if length:
                spans.append((start, start + length))
            if kind == 0x55 and length:
                data_tags += 1
            elif kind == 0x76:
                if length < 32:
                    raise ValueError("Truncated AWC sound format tag")
                format_offsets.append(start)
        if data_tags != 1 or len(format_offsets) != 1:
            raise ValueError("Expected one data tag and one 0x76 format tag per sound")
        formats.append(format_offsets[0])

    # Establish that every format range is separate from data before reading it.
    spans.sort()
    if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
        raise ValueError("Overlapping AWC tag extents")
    groups: dict[tuple[int, int], FormatGroup] = {}
    for start in formats:
        header = bank.read(start, 32)
        samples, = struct.unpack_from("<I", header)
        rate, = struct.unpack_from("<H", header, 8)
        codec = header[28]
        key = rate, codec
        if key not in groups:
            groups[key] = FormatGroup(rate, codec)
        groups[key].streams += 1
        groups[key].samples += samples
    return [groups[key] for key in sorted(groups)]


def integer(text: str) -> int:
    return int(text, 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--offset", type=integer, required=True, help="Byte offset of the ADAT header")
    parser.add_argument("--size", type=integer, required=True, help="Bytes in the caller-supplied bank range")
    args = parser.parse_args()
    try:
        with args.archive.open("rb") as stream:
            groups = read_formats(stream, args.offset, args.size)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{args.archive}: {error}\n")
    print(json.dumps({"stream_count": sum(g.streams for g in groups), "formats": [asdict(g) for g in groups]}))


if __name__ == "__main__":
    main()
