"""Native program containers: the record envelope that wraps a test program, and the controls of
native_program's record and container selection."""
from pathlib import Path
import hashlib
import json
import struct
import subprocess
import sys
import zlib

import pixel_aot
from pixel_aot import native_program

from .common import assembly, lower, must_reject


def shader_record(blob: bytes, name: bytes) -> bytes:
    encoder = zlib.compressobj(wbits=-15)
    payload = encoder.compress(blob) + encoder.flush()
    return (bytes([len(name) + 1]) + name + b"\0\0"
            + struct.pack("<4I", len(payload), 0, len(payload), len(blob)) + payload)


def envelope(code: bytes, name: bytes = b"fixture", *, private_data: bytes | None = None, directory_end=None,
             compute_width=None, mesh_limits=None) -> bytes:
    """A named record holding `code` as the native program of a DXBC container. directory_end=(extent, end field)
    gives the FSSM image the v0x101 section directory with that code extent (from R0Y00/Xbox2Windows#477 by Royoo);
    compute_width makes it a compute program with a PSV0 thread-group width (#483), and mesh_limits a mesh program with
    those output limits (#491)."""
    program_start = 288 if directory_end is not None else 256
    image = bytearray(program_start) + code
    image[:4] = b"FSSM"
    struct.pack_into("<I", image, 192, program_start - 40)
    if directory_end is not None:
        extent, end_field = directory_end
        struct.pack_into("<I", image, 4, 0x101)
        struct.pack_into("<Q", image, 200, extent)
        struct.pack_into("<Q", image, 232, end_field)
    native = b"XBCH" + bytes(12) + struct.pack("<II", len(image), 0) + zlib.compress(image)
    program = (bytes(24) + b"XDAT" + struct.pack("<II", 1, 0)
               + struct.pack("<III", 13, 48, len(native)) + native)
    if compute_width is not None:
        program = program[:2] + struct.pack("<H", 13 if mesh_limits else 5) + program[4:]
    sections = [b"DXIL" + struct.pack("<I", len(program)) + program]
    if compute_width is not None:
        psv = bytearray(52)
        struct.pack_into("<I", psv, 0, 48)
        psv[28] = 13 if mesh_limits else 5
        if mesh_limits:
            psv[31] = 2
            struct.pack_into("<HH", psv, 16, *mesh_limits)
        struct.pack_into("<3I", psv, 40, compute_width, 1, 1)
        sections.append(b"PSV0" + struct.pack("<I", len(psv)) + psv)
    if private_data is not None:
        sections.append(b"PRIV" + struct.pack("<I", len(private_data)) + private_data)
    offset = 32 + 4 * len(sections)
    offsets = bytearray()
    for section in sections:
        offsets.extend(struct.pack("<I", offset))
        offset += len(section)
    blob = b"DXBC" + bytes(16) + struct.pack("<3I", 1, offset, len(sections)) + offsets + b"".join(sections)
    return shader_record(blob, name)


def check_program_extent(directory, library):
    """The FSSM v0x101 code extent and two-exit programs (from R0Y00/Xbox2Windows#477 by Royoo). A conditional jumps
    over the early exit; the alternate block starts with a two-dword instruction (s_mov_b32 with a literal operand)."""
    branch = bytes.fromhex("010084bf")
    end = bytes.fromhex("000081bf")
    mov = bytes.fromhex("ff0380be 01000000")
    pad = bytes.fromhex("00009fbf")
    code = branch + end + mov + end
    padding = pad * 5
    base = 288 - 40
    extent = 40 + len(code) + len(padding)
    archive = directory / "bounded.rpf"

    def extract(body, size=extent, limit=base + extent):
        archive.write_bytes(envelope(body, directory_end=(size, limit)))
        return native_program(archive, "fixture", llvm=library)[1]

    jump_over_nop = bytes.fromhex("010082bf 000080bf")
    assert extract(jump_over_nop + code + padding[8:]) == jump_over_nop + code
    must_reject(extract, bytes.fromhex("010082bf 810380be") + code + padding[8:])
    assert extract(code + padding + end) == code  # marker in metadata
    # A terminator in metadata cannot stand in for one missing inside the section.
    must_reject(extract, bytes(len(code)) + padding + end)
    assert extract(code + padding + pad * 4, limit=0xdeadbeefdeadbeef) == code
    must_reject(extract, code + padding, extent, base + extent + 4)
    must_reject(extract, code + padding[:-4])
    must_reject(extract, code + padding, extent, 0xdeadbeefdeadbeef)
    must_reject(extract, code + padding[:4] + bytes(16) + end)
    must_reject(extract, bytes.fromhex("020084bf") + code[4:] + padding)  # target inside literal
    must_reject(extract, bytes.fromhex("000080bf") + code[4:] + padding)  # disconnected block
    must_reject(extract, bytes.fromhex("040084bf") + code[4:] + padding)  # target in padding
    must_reject(extract, branch + bytes.fromhex("ff0380be") + end + bytes.fromhex("000080bf") + end + padding)
    # Without a disassembler a second exit is never accepted.
    archive.write_bytes(envelope(code + padding, directory_end=(extent, base + extent)))
    must_reject(native_program, archive, "fixture")


def binary_checks(directory, assembler, objcopy, library):
    check_program_extent(directory, library)


def check_container_selector(directory: Path, code: bytes, library: str | None = None) -> None:
    archive = directory / "same-name.rpf"
    records = [envelope(code, private_data=metadata) for metadata in (b"first", b"second")]
    containers = []
    for record in records:
        archive.write_bytes(record)
        container, native = native_program(archive, "fixture")
        assert native == code
        containers.append(container)
    digests = [hashlib.sha256(blob).hexdigest() for blob in containers]
    first, second = records
    broken = b"\x08fixture\0\0" + struct.pack("<4I", 2, 0, 2, 8) + b"\x07\xff"
    archive.write_bytes(first + second)
    must_reject(native_program, archive, "fixture")
    for digest, blob in zip(digests, containers, strict=True):
        assert native_program(archive, "fixture", container_sha256=digest.upper()) == (blob, code)

    for order in (broken + first, first + broken):
        archive.write_bytes(order)
        assert native_program(archive, "fixture", container_sha256=digests[0]) == (containers[0], code)
    # A bad frame can claim bytes covering a subsequent record of the same name.
    archive.write_bytes(b"\x08fixture\0\0" + struct.pack("<4I", len(first) + 2, 0, len(first) + 2, 8)
                        + b"\x07\xff" + first)
    assert native_program(archive, "fixture", container_sha256=digests[0]) == (containers[0], code)
    archive.write_bytes(first * 257 + second)
    assert native_program(archive, "fixture", container_sha256=digests[1]) == (containers[1], code)

    archive.write_bytes(envelope(code))
    intact, _ = native_program(archive, "fixture")
    corrupt = intact[:-1] + bytes([intact[-1] ^ 1])
    archive.write_bytes(first + shader_record(corrupt, b"fixture"))
    try:
        native_program(archive, "fixture", container_sha256=hashlib.sha256(corrupt).hexdigest())
    except zlib.error as error:
        assert "incorrect data check" in str(error), error
    else:
        raise AssertionError("Container selection hid a corrupt native stream")

    for contents, digest, reason in (
        (first + second, hashlib.sha256(code).hexdigest(), "No record matches the name and container SHA-256"),
        (first + second, "bad", "Invalid decoded container SHA-256"),
        (first + broken + first + second, digests[0], "Multiple records match the name and container SHA-256"),
    ):
        archive.write_bytes(contents)
        try:
            native_program(archive, "fixture", container_sha256=digest)
        except ValueError as error:
            assert str(error) == reason, error
        else:
            raise AssertionError("Container selection accepted an invalid digest or ambiguous record")

    if library is None:
        return
    archive.write_bytes(first + second)
    output = directory / "selected.hlsl"
    command = [sys.executable, "-B", Path(pixel_aot.__file__), archive, "fixture", "--llvm", library,
               "--texture-sgpr", "20", "--interp-sgpr", "24", "--sampler-words", "1", "2", "3", "4",
               "--output", output]
    ambiguous = subprocess.run(command, capture_output=True, text=True)
    assert ambiguous.returncode == 1 and "Multiple records match the name" in ambiguous.stderr
    for digest in digests:
        result = subprocess.run([*command, "--container-sha256", digest], capture_output=True, text=True, check=True)
        summary = json.loads(result.stdout)
        assert summary["container_sha256"] == digest
        assert summary["native_sha256"] == hashlib.sha256(code).hexdigest()
        assert output.read_text(encoding="utf-8") == lower(assembly(False), 20, 24, [1, 2, 3, 4])
    wrong = subprocess.run([*command, "--container-sha256", "0" * 64], capture_output=True, text=True)
    assert wrong.returncode == 1 and "No record matches the name and container SHA-256" in wrong.stderr


def controls(directory):
    archive = directory / "input.bin"
    code = bytes.fromhex("000080bf 000081bf")  # s_nop 0 followed by s_endpgm
    check_container_selector(directory, code)
    record = envelope(code)
    archive.write_bytes(b"another_fixture\0" + record)
    assert native_program(archive, "fixture")[1] == code
    long_name = b"synthetic_pixel_with_a_printable_length"
    archive.write_bytes(envelope(code, long_name))
    assert native_program(archive, long_name.decode())[1] == code
    for invalid in (record[:-1], record + b"\0" + record, envelope(code + code)):
        archive.write_bytes(invalid)
        must_reject(native_program, archive, "fixture")
