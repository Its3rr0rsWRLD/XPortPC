"""Automated checks with source-owned inputs for RDNA 2 disassembly, extraction, and scanning tools."""
import argparse
from io import StringIO
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from disasm_rdna2 import disasm_rdna2, decode_instruction, disassemble_binary
from extract_shaders import extract_shaders, extract_native_rdna2_code
from pixel_aot import native_program
from scan_unsupported_shaders import (
    analyze_shader_instructions,
    is_instruction_supported,
    is_opcode_recognized,
    classify_isa_category,
    generate_reports,
    scan_directory_or_files,
    detect_shader_stage,
    generate_progress_dashboard,
    disassemble_binary_shader,
    make_failed_shader_record,
)
try:
    from pixel_aot import disassemble as llvm_disassemble
except ImportError:
    llvm_disassemble = None


def resolve_llvm_lib(name_or_path: str) -> str:
    """Resolve an LLVM shared library name or path for ctypes.CDLL loading."""
    p = Path(name_or_path)
    if p.is_file():
        return str(p.resolve())
    import ctypes.util
    found = ctypes.util.find_library(name_or_path)
    if found and Path(found).is_file():
        return str(Path(found).resolve())
    for directory in [
        "/usr/lib/x86_64-linux-gnu",
        "/usr/lib/aarch64-linux-gnu",
        "/usr/lib",
        "/usr/local/lib",
    ]:
        candidate = Path(directory) / name_or_path
        if candidate.is_file():
            return str(candidate.resolve())
    return name_or_path


def resolve_tool(env_var: str, default_names: list[str]) -> str | None:
    """Resolve a command-line tool path via environment variable or system search."""
    val = os.environ.get(env_var)
    if val:
        w = shutil.which(val)
        if w:
            return w
        p = Path(val)
        if p.is_file():
            return str(p.resolve())
    for name in default_names:
        w = shutil.which(name)
        if w:
            return w
    return None


def assemble_with_llvm_mc(instructions: list[str], assembler: str, objcopy: str) -> bytes:
    """Assemble AMDGPU instructions for gfx1013 using llvm-mc and extract .text bytes."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        src = tmp_dir / "fixture.s"
        obj = tmp_dir / "fixture.o"
        binary = tmp_dir / "fixture.bin"
        src.write_text("\n".join(instructions) + "\n", encoding="ascii")
        subprocess.run(
            [assembler, "-triple=amdgcn--amdpal", "-mcpu=gfx1013", "-filetype=obj", str(src), "-o", str(obj)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [objcopy, "-O", "binary", "--only-section=.text", str(obj), str(binary)],
            check=True,
            capture_output=True,
        )
        return binary.read_bytes()


def envelope(code: bytes, name: bytes = b"fixture_ps") -> bytes:
    """Create a source-owned DXBC container wrapping native GFX1013 machine code."""
    program_start = 256
    image = bytearray(program_start) + code
    image[:4] = b"FSSM"
    struct.pack_into("<I", image, 192, program_start - 40)
    native = b"XBCH" + bytes(12) + struct.pack("<II", len(image), 0) + zlib.compress(image)
    program = (bytes(24) + b"XDAT" + struct.pack("<II", 1, 0)
               + struct.pack("<III", 13, 48, len(native)) + native)
    blob = (b"DXBC" + bytes(16) + struct.pack("<4I", 1, 44 + len(program), 1, 36)
            + b"DXIL" + struct.pack("<I", len(program)) + program)
    encoder = zlib.compressobj(wbits=-15)
    payload = encoder.compress(blob) + encoder.flush()
    return (bytes([len(name) + 1]) + name + b"\0\0"
            + struct.pack("<4I", len(payload), 0, len(payload), len(blob)) + payload)


class TestRdna2Disasm(unittest.TestCase):
    """Test pure-Python RDNA 2 disassembler and verify against golden vectors and LLVM."""

    def test_golden_vectors(self):
        vectors = [
            # (hex_bytes, expected_opcode, expected_mnemonic)
            ("000080bf", "s_nop", "s_nop 0"),
            ("000081bf", "s_endpgm", "s_endpgm"),
            ("000082bf", "s_branch", "s_branch label_0x4"),
            ("7f008cbf", "s_waitcnt", "s_waitcnt vmcnt(7) lgkmcnt(0)"),
            ("000382be", "s_mov_b32", "s_mov_b32 s2, s0"),
            ("000482be", "s_mov_b64", "s_mov_b64 s2, s0"),
            ("00008080", "s_sub_u32", "s_sub_u32 s0, s0, s0"),
            # GFX10 scalar operand codes: 108-123 are ttmp0-15, 125 is null (SOP2 ssrc1)
            ("007d8080", "s_sub_u32", "s_sub_u32 s0, s0, null"),
            ("006c8080", "s_sub_u32", "s_sub_u32 s0, s0, ttmp0"),
            # GFX10 / RDNA 2 opcode numbers, encodings as in LLVM's gfx10 MC tests
            ("01020083", "s_min_i32", "s_min_i32 s0, s1, s2"),
            ("01020093", "s_mul_i32", "s_mul_i32 s0, s1, s2"),
            ("341281b1", "s_cmpk_eq_i32", "s_cmpk_eq_i32 s1, 0x1234"),
            # SOPC: [31:23] == 0b101111110. These encodings were previously
            # consumed by the SOPK prefix check (e.g. 000100bf as s_sopk_1e).
            ("000100bf", "s_cmp_eq_i32", "s_cmp_eq_i32 s0, s1"),
            ("000106bf", "s_cmp_eq_u32", "s_cmp_eq_u32 s0, s1"),
            ("020302bf", "s_cmp_gt_i32", "s_cmp_gt_i32 s2, s3"),
            ("007d00bf", "s_cmp_eq_i32", "s_cmp_eq_i32 s0, null"),
            ("00010cbf", "s_bitcmp0_b32", "s_bitcmp0_b32 s0, s1"),
            ("000212bf", "s_cmp_eq_u64", "s_cmp_eq_u64 s[0:1], s[2:3]"),
            ("04060ebf", "s_bitcmp0_b64", "s_bitcmp0_b64 s[4:5], s6"),
            ("000080bb", "s_waitcnt_vscnt", "s_waitcnt_vscnt s0, 0x0"),
            ("0100a0bf", "s_inst_prefetch", "s_inst_prefetch 0x1"),
            ("0255027e", "v_rcp_f32_e32", "v_rcp_f32_e32 v1, v2"),
            ("010d007e", "v_cvt_f32_u32_e32", "v_cvt_f32_u32_e32 v0, v1"),
            ("0000027e", "v_nop", "v_nop"),
            # VOP1 9-bit SRC0: 0..255 scalar/constant, 256..511 VGPR
            ("0103007e", "v_mov_b32_e32", "v_mov_b32_e32 v0, v1"),
            ("0102007e", "v_mov_b32_e32", "v_mov_b32_e32 v0, s1"),
            ("f202047e", "v_mov_b32_e32", "v_mov_b32_e32 v2, 1.0"),
            ("f002067e", "v_mov_b32_e32", "v_mov_b32_e32 v3, 0.5"),
            ("8002087e", "v_mov_b32_e32", "v_mov_b32_e32 v4, 0"),
            # VOP2 9-bit SRC0 (VGPR vs SGPR vs inline constant)
            ("01050602", "v_add_f32_e32", "v_add_f32_e32 v3, v1, v2"),
            ("01040602", "v_add_f32_e32", "v_add_f32_e32 v3, s1, v2"),
            ("f0040602", "v_add_f32_e32", "v_add_f32_e32 v3, 0.5, v2"),
        ]
        for hex_str, expected_op, expected_asm in vectors:
            raw = bytes.fromhex(hex_str)
            insns = disasm_rdna2(raw)
            self.assertEqual(len(insns), 1, f"Failed for {hex_str}")
            self.assertEqual(insns[0]["opcode"], expected_op, f"Mismatched opcode for {hex_str}")
            self.assertEqual(insns[0]["assembly"], expected_asm, f"Mismatched assembly for {hex_str}")

    def test_sopc_literal_keeps_the_following_instruction_aligned(self):
        # src1 == literal (255) makes the SOPC encoding 8 bytes. Without
        # consuming the literal dword, the following s_endpgm would be misread.
        raw = bytes.fromhex("00ff06bf 78563412 000081bf")
        insns = disasm_rdna2(raw)
        self.assertEqual(
            [(i["opcode"], i["length"], i["assembly"]) for i in insns],
            [
                ("s_cmp_eq_u32", 8, "s_cmp_eq_u32 s0, 0x12345678"),
                ("s_endpgm", 4, "s_endpgm"),
            ],
        )

    def test_cli_hex_entry_point(self):
        script = Path(__file__).resolve().parents[1] / "tools" / "disasm_rdna2.py"
        res = subprocess.run(
            [sys.executable, "-B", str(script), "--hex", "000080bf 000081bf"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("s_nop 0", res.stdout)
        self.assertIn("s_endpgm", res.stdout)

    def test_llvm_comparison(self):
        llvm_lib_env = os.environ.get("LLVM_LIB")
        if not llvm_lib_env:
            self.skipTest("LLVM_LIB environment variable not set; verified against golden vectors")

        if llvm_disassemble is None:
            self.fail("pixel_aot.disassemble helper could not be imported")

        resolved_lib = resolve_llvm_lib(llvm_lib_env)

        fixture_instructions = [
            "s_nop 0",
            "s_waitcnt lgkmcnt(0)",
            "v_mov_b32_e32 v0, v1",
            "v_mov_b32_e32 v0, s1",
            "v_mov_b32_e32 v2, 1.0",
            "v_mov_b32_e32 v3, 0.5",
            "v_mov_b32_e32 v4, 0",
            "s_cmp_eq_i32 s0, s1",
            "s_cmp_eq_u32 s0, s1",
            "s_cmp_gt_i32 s2, s3",
            "s_cmp_eq_u64 s[0:1], s[2:3]",
            "s_bitcmp0_b32 s0, s1",
            "s_bitcmp0_b64 s[4:5], s6",
            "s_endpgm",
        ]

        assembler = resolve_tool("LLVM_MC", ["llvm-mc-15", "llvm-mc"])
        objcopy = resolve_tool("LLVM_OBJCOPY", ["llvm-objcopy-15", "llvm-objcopy"])

        if not assembler or not objcopy:
            self.fail(
                f"Designated LLVM comparison job requires llvm-mc and llvm-objcopy "
                f"(assembler={assembler}, objcopy={objcopy})"
            )

        try:
            emitted_bytes = assemble_with_llvm_mc(fixture_instructions, assembler, objcopy)
        except Exception as e:
            self.fail(f"Failed to assemble comparison fixture with llvm-mc: {e}")

        self.assertGreater(len(emitted_bytes), 0, "llvm-mc emitted empty machine code")
        self.assertEqual(len(emitted_bytes) % 4, 0, "Emitted bytes length must be multiple of 4")

        try:
            llvm_lines = llvm_disassemble(emitted_bytes, resolved_lib)
        except Exception as e:
            self.fail(
                f"Designated LLVM comparison failed to load or run with '{llvm_lib_env}' "
                f"(resolved: '{resolved_lib}'): {e}"
            )

        rdna2_insns = disasm_rdna2(emitted_bytes)
        self.assertEqual(
            len(llvm_lines), len(fixture_instructions),
            f"LLVM disassembled instruction count mismatch: {llvm_lines}"
        )
        self.assertEqual(
            len(rdna2_insns), len(fixture_instructions),
            f"RDNA 2 disassembled instruction count mismatch: {rdna2_insns}"
        )

        for i, (orig_inst, llvm_line, rdna2_rec) in enumerate(zip(fixture_instructions, llvm_lines, rdna2_insns)):
            orig_op = orig_inst.split()[0].lower()
            llvm_op = llvm_line.split()[0].lower()
            rdna2_op = rdna2_rec["opcode"].lower()
            self.assertEqual(
                llvm_op, orig_op,
                f"Instruction {i}: LLVM opcode '{llvm_op}' does not match original '{orig_op}'"
            )
            self.assertEqual(
                rdna2_op, orig_op,
                f"Instruction {i}: disasm_rdna2 opcode '{rdna2_op}' does not match original '{orig_op}'"
            )
            self.assertEqual(
                rdna2_op, llvm_op,
                f"Instruction {i}: disasm_rdna2 opcode '{rdna2_op}' does not match LLVM opcode '{llvm_op}'"
            )
            if orig_op.startswith("v_"):
                self.assertEqual(
                    " ".join(rdna2_rec["assembly"].lower().split()),
                    " ".join(llvm_line.lower().split()),
                    f"Instruction {i}: disasm_rdna2 '{rdna2_rec['assembly']}' does not match LLVM '{llvm_line}'"
                )


class TestRdna2Extractor(unittest.TestCase):
    """Test shader extraction from RPF archives against known source-owned fixtures."""

    def test_extract_bytes_match_fixture(self):
        known_code = bytes.fromhex(
            "000080bf"  # s_nop 0
            "7f008cbf"  # s_waitcnt
            "000081bf"  # s_endpgm
        )
        record = envelope(known_code, b"PS_SourceOwned_Fixture")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / "synthetic_shaders.rpf"
            archive.write_bytes(b"RPF_MAGIC_HEADER_PAD\0" + record)

            output_dir = tmp_path / "extracted"
            out_path, manifest_file = extract_shaders(archive, output_dir, target_stages={"pixel"})

            extracted_file = out_path / "pixel" / "PS_SourceOwned_Fixture.bin"
            self.assertTrue(extracted_file.is_file(), "Extracted binary file not found")
            extracted_bytes = extracted_file.read_bytes()

            # Byte-for-byte exact check against source-owned input
            self.assertEqual(extracted_bytes, known_code)

            # Check manifest.json metadata
            self.assertTrue(manifest_file.is_file(), "Manifest not generated")
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            self.assertEqual(manifest["total_extracted"], 1)
            self.assertEqual(manifest["shaders"][0]["name"], "PS_SourceOwned_Fixture")
            self.assertEqual(manifest["shaders"][0]["native_size"], len(known_code))
            self.assertEqual(manifest["shaders"][0]["stage"], "pixel")

    def test_duplicate_record_names(self):
        """Verify that duplicate record names produce distinct files without overwriting."""
        code_1 = bytes.fromhex("000080bf 000081bf")  # s_nop 0, s_endpgm
        code_2 = bytes.fromhex("000382be 000081bf")  # s_mov_b32, s_endpgm
        record_1 = envelope(code_1, b"PS_DuplicateName")
        record_2 = envelope(code_2, b"PS_DuplicateName")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / "dups.rpf"
            archive.write_bytes(b"RPF\0" + record_1 + record_2)

            output_dir = tmp_path / "extracted_dups"
            out_path, manifest_file = extract_shaders(archive, output_dir, target_stages={"pixel"})

            file_1 = out_path / "pixel" / "PS_DuplicateName.bin"
            file_2 = out_path / "pixel" / "PS_DuplicateName_1.bin"

            self.assertTrue(file_1.is_file(), "First duplicate shader file not found")
            self.assertTrue(file_2.is_file(), "Second duplicate disambiguated file not found")

            self.assertEqual(file_1.read_bytes(), code_1)
            self.assertEqual(file_2.read_bytes(), code_2)

            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            self.assertEqual(manifest["total_extracted"], 2)
            self.assertEqual(manifest["shaders"][0]["native_file"], "pixel/PS_DuplicateName.bin")
            self.assertEqual(manifest["shaders"][1]["native_file"], "pixel/PS_DuplicateName_1.bin")
            self.assertNotEqual(manifest["shaders"][0]["sha256"], manifest["shaders"][1]["sha256"])

    def test_cli_extraction(self):
        """Invoke extractor via its actual CLI entry point on synthetic fixture."""
        known_code = bytes.fromhex("000080bf 000081bf")
        record = envelope(known_code, b"PS_CliTest")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / "cli_shaders.rpf"
            archive.write_bytes(b"RPF_MAGIC\0" + record)
            output_dir = tmp_path / "cli_out"
            script = Path(__file__).resolve().parents[1] / "tools" / "extract_shaders.py"
            res = subprocess.run(
                [sys.executable, "-B", str(script), str(archive), "--output-dir", str(output_dir), "--stage", "pixel"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(res.returncode, 0)
            self.assertTrue((output_dir / "pixel" / "PS_CliTest.bin").is_file())
            self.assertEqual((output_dir / "pixel" / "PS_CliTest.bin").read_bytes(), known_code)
            self.assertTrue((output_dir / "manifest.json").is_file())

    def test_extracted_names_round_trip_length_prefixed_records(self) -> None:
        code = bytes.fromhex("000080bf 000081bf")
        names = (b"PS_A", b"PS_" + b"S" * 28, b"!" + b"A" * 32,
                 b"PS_" + b"X" * 122, b"~" + b"B" * 125, b"~" + b"C" * 126)
        legacy_name = b"PS_Legacy"
        legacy = envelope(code, legacy_name)[1:]
        truncated = envelope(code, b"PS_Truncated_Length_Prefix_Fixture")[:-1]
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            archive = work / "source_built.rpf"
            archive.write_bytes(b"RPF\0" + b"".join(envelope(code, name) for name in names) + legacy + truncated)
            output, manifest_path = extract_shaders(archive, work / "shaders", target_stages={"pixel"},
                                                    length_prefixed_names=True)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

            self.assertEqual(manifest["total_extracted"], len(names) + 1)
            for source_name, record in zip((*names, legacy_name), manifest["shaders"], strict=True):
                name = source_name.decode("ascii")
                with self.subTest(length=len(source_name)):
                    self.assertEqual(record["name"], name)
                    self.assertEqual(record["native_file"], f"pixel/{name}.bin")
                    self.assertEqual((output / record["native_file"]).read_bytes(), code)
                    if source_name != legacy_name:
                        self.assertEqual(native_program(archive, record["name"])[1], code)

    def test_ambiguous_length_prefix_requires_explicit_mode(self) -> None:
        code = bytes.fromhex("000080bf 000081bf")
        legacy_name = b"PS_" + b"L" * 77
        prefixed_name = legacy_name[1:]
        data = envelope(code, legacy_name)[1:]
        self.assertEqual(data, envelope(code, prefixed_name))
        script = Path(__file__).resolve().parents[1] / "tools" / "extract_shaders.py"

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            archive = work / "ambiguous.rpf"
            archive.write_bytes(b"RPF\0" + data)
            for expected_name, options in ((legacy_name, []), (prefixed_name, ["--length-prefixed-names"])):
                name = expected_name.decode("ascii")
                with self.subTest(options=options):
                    output = work / name
                    subprocess.run([sys.executable, "-B", str(script), str(archive), "--output-dir", str(output),
                                    *options], capture_output=True, check=True)
                    manifest_path = output / "manifest.json"
                    record, = json.loads(manifest_path.read_text(encoding="utf-8"))["shaders"]
                    self.assertEqual(record["name"], name)
                    self.assertEqual(record["native_file"], f"pixel/{name}.bin")
                    self.assertEqual((output / record["native_file"]).read_bytes(), code)

    def test_stage_filtering(self):
        known_code = bytes.fromhex("000080bf 000081bf")
        record = envelope(known_code, b"PS_PixelOnly")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / "test.rpf"
            archive.write_bytes(b"HEADER\0" + record)

            output_dir = tmp_path / "extracted_compute"
            out_path, manifest_file = extract_shaders(archive, output_dir, target_stages={"compute"})
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            self.assertEqual(manifest["total_extracted"], 0)

    def test_false_positive_header_does_not_skip_following_record(self):
        """A candidate header whose deflate payload fails must not skip a valid record inside its span."""
        known_code = bytes.fromhex("000080bf 000081bf")
        valid_record = envelope(known_code, b"PS_AfterFalsePositive")
        bogus_stored = len(valid_record) + 16
        false_header = b"FAKE_HDR\0\0" + struct.pack("<4I", bogus_stored, 0, bogus_stored, 256)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / "false_positive.rpf"
            archive.write_bytes(false_header + b"\x00\x01\x02\x03" + valid_record + bytes(16))

            output_dir = tmp_path / "extracted_fp"
            out_path, manifest_file = extract_shaders(archive, output_dir, target_stages={"pixel"})
            extracted_file = out_path / "pixel" / "PS_AfterFalsePositive.bin"
            self.assertTrue(extracted_file.is_file(), "Valid record after false-positive header was skipped")
            self.assertEqual(extracted_file.read_bytes(), known_code)
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            self.assertEqual(manifest["total_extracted"], 1)

    def test_oversized_claimed_span_with_unused_data_does_not_skip_following_record(self):
        """Cursor advancement must stop at consumed deflate bytes when unused_data holds another record."""
        code_1 = bytes.fromhex("000080bf 000081bf")
        code_2 = bytes.fromhex("000082be 000081bf")
        record_1 = envelope(code_1, b"PS_OversizedSpan")
        record_2 = envelope(code_2, b"PS_InsideUnusedTail")
        name_end = record_1.index(b"PS_OversizedSpan") + len(b"PS_OversizedSpan")
        stored_1, _, _, decoded_1 = struct.unpack_from("<4I", record_1, name_end + 2)
        payload_1 = record_1[name_end + 18:name_end + 18 + stored_1]
        oversized_stored = stored_1 + len(record_2)
        oversized_record_1 = (record_1[:name_end + 2]
                              + struct.pack("<4I", oversized_stored, 0, oversized_stored, decoded_1)
                              + payload_1)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / "oversized_span.rpf"
            archive.write_bytes(b"RPF\0" + oversized_record_1 + record_2)

            output_dir = tmp_path / "extracted_oversized"
            out_path, manifest_file = extract_shaders(archive, output_dir, target_stages={"pixel"})
            file_1 = out_path / "pixel" / "PS_OversizedSpan.bin"
            file_2 = out_path / "pixel" / "PS_InsideUnusedTail.bin"
            self.assertTrue(file_1.is_file(), "First shader in oversized span not extracted")
            self.assertTrue(file_2.is_file(), "Second shader inside unused_data tail was skipped")
            self.assertEqual(file_1.read_bytes(), code_1)
            self.assertEqual(file_2.read_bytes(), code_2)
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            self.assertEqual(manifest["total_extracted"], 2)

    def test_disambiguated_stem_does_not_collide_with_existing_or_case_variant(self):
        """Disambiguated stems must not overwrite explicit _1 names or case variants."""
        codes = [
            bytes.fromhex("000080bf 000081bf"),
            bytes.fromhex("000082be 000081bf"),
            bytes.fromhex("000182be 000081bf"),
            bytes.fromhex("0000027e 000081bf"),
        ]
        records = [
            envelope(codes[0], b"PS_Dup"),
            envelope(codes[1], b"PS_Dup"),
            envelope(codes[2], b"PS_Dup_1"),
            envelope(codes[3], b"ps_dup"),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / "collisions.rpf"
            archive.write_bytes(b"RPF\0" + b"".join(records))

            output_dir = tmp_path / "extracted_collisions"
            out_path, manifest_file = extract_shaders(archive, output_dir, target_stages={"pixel"})
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            self.assertEqual(manifest["total_extracted"], 4)
            paths = [entry["native_file"] for entry in manifest["shaders"]]
            self.assertEqual(len({p.casefold() for p in paths}), 4, f"Colliding output paths: {paths}")
            for entry, expected in zip(manifest["shaders"], codes):
                self.assertEqual((out_path / entry["native_file"]).read_bytes(), expected)

    def test_empty_archive_produces_empty_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / "empty.rpf"
            archive.write_bytes(b"")

            output_dir = tmp_path / "extracted_empty"
            _, manifest_file = extract_shaders(archive, output_dir, target_stages={"all"})
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            self.assertEqual(manifest["total_extracted"], 0)
            self.assertEqual(manifest["shaders"], [])

    def test_invalid_xbch_offset_or_size_rejected(self):
        known_code = bytes.fromhex("000080bf 000081bf")
        program_start = 256
        image = bytearray(program_start) + known_code
        image[:4] = b"FSSM"
        struct.pack_into("<I", image, 192, program_start - 40)
        compressed = zlib.compress(image)

        wrong_size_native = b"XBCH" + bytes(12) + struct.pack("<II", len(image) + 4, 0) + compressed
        wrong_size_program = (bytes(24) + b"XDAT" + struct.pack("<II", 1, 0)
                              + struct.pack("<III", 13, 48, len(wrong_size_native)) + wrong_size_native)
        self.assertIsNone(extract_native_rdna2_code(wrong_size_program))

        valid_native = b"XBCH" + bytes(12) + struct.pack("<II", len(image), 0) + compressed
        overlapping_program = (b"XBCH" + bytes(20) + b"XDAT" + struct.pack("<II", 1, 0)
                               + struct.pack("<III", 13, 0, len(valid_native)) + valid_native)
        self.assertIsNone(extract_native_rdna2_code(overlapping_program))


class TestRdna2Scanner(unittest.TestCase):
    """Test scanner instruction recognition vs full shader translator acceptance."""

    def test_accepted_full_shader(self):
        """Canonical straight-line pixel shader accepted by pixel_aot translator."""
        canonical_shader = [
            "s_mov_b64 s[50:51], exec",
            "s_wqm_b64 exec, exec",
            "s_mov_b32 m0, s24",
            "v_interp_p1_f32_e32 v8, v0, attr0.x",
            "v_interp_p1_f32_e32 v9, v0, attr0.y",
            "v_interp_p2_f32_e32 v9, v1, attr0.y",
            "v_interp_p2_f32_e32 v8, v1, attr0.x",
            "s_and_b64 exec, exec, s[50:51]",
            "s_mov_b32 s21, 0",
            "s_load_dwordx8 s[28:35], s[20:21], null",
            "s_mov_b32 s40, 1",
            "s_mov_b32 s41, 2",
            "s_mov_b32 s42, 3",
            "s_mov_b32 s43, 4",
            "s_waitcnt lgkmcnt(0)",
            "image_sample v[12:15], v[8:9], s[28:35], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D",
            "s_waitcnt vmcnt(0)",
            "v_cvt_pkrtz_f16_f32_e32 v16, v12, v13",
            "v_cvt_pkrtz_f16_f32_e32 v17, v14, v15",
            "exp mrt0 v16, v16, v17, v17 done compr vm",
            "s_endpgm",
        ]
        res = analyze_shader_instructions("canonical_ps", canonical_shader)
        self.assertTrue(res["opcodes_recognized"])
        self.assertTrue(res["translator_accepted"])
        self.assertEqual(res["compatibility_category"], "accepted")
        self.assertTrue(res["is_fully_supported"])

    def test_opcodes_recognized_but_translator_rejected(self):
        """Shader with valid RDNA 2 opcodes whose structure violates pixel_aot constraints."""
        valid_rdna2_but_rejected = [
            "s_mov_b64 s[50:51], exec",
            "s_branch 0",  # s_branch is a valid RDNA 2 opcode recognized by scanner, but rejected by translator
            "s_mov_b32 m0, s24",
            "v_cvt_pkrtz_f16_f32_e32 v16, v12, v13",
            "exp mrt0 v16, v16, v17, v17 done compr vm",
            "s_endpgm",
        ]
        res = analyze_shader_instructions("branched_ps", valid_rdna2_but_rejected)
        # All opcodes are valid RDNA 2 instructions
        self.assertTrue(res["opcodes_recognized"])
        # But translator rejects the non-straight-line structure
        self.assertFalse(res["translator_accepted"])
        self.assertEqual(res["compatibility_category"], "opcode_recognized_translator_rejected")
        self.assertFalse(res["is_fully_supported"])
        self.assertIsNotNone(res["lower_error"])

    def test_unsupported_opcode_shader(self):
        """Shader containing opcodes unknown or unsupported by the ISA scanner."""
        unknown_opcode_shader = [
            "s_mov_b64 s[50:51], exec",
            "v_imaginary_opcode_xyz v0, v1, v2",
            "s_endpgm",
        ]
        res = analyze_shader_instructions("unknown_ps", unknown_opcode_shader)
        self.assertFalse(res["opcodes_recognized"])
        self.assertFalse(res["translator_accepted"])
        self.assertEqual(res["compatibility_category"], "unsupported_opcodes")
        self.assertIn("v_imaginary_opcode_xyz", res["unsupported_opcodes"])

    def test_vopc_classification(self):
        """Vector compare opcodes with type suffixes must classify as VOPC, not VALU."""
        for opcode in ("v_cmp_lt_f32", "v_cmp_eq_u32", "v_cmp_gt_i32", "v_cmp_le_f16"):
            self.assertEqual(classify_isa_category(opcode), "VOPC (Vector Compare)", opcode)
        self.assertEqual(classify_isa_category("v_add_f32"), "VOP / VALU (Vector ALU - VOP1/VOP2/VOP3)")

    def test_inline_slash_comments_and_blank_lines(self):
        """Inline // comments must be stripped and blank/comment lines must not inflate counts."""
        self.assertTrue(is_instruction_supported("s_endpgm // shader exit"))
        res = analyze_shader_instructions(
            "commented_ps",
            [
                "",
                "; header comment",
                "// llvm-style comment",
                "s_endpgm // shader exit",
                "v_imaginary_opcode_xyz v0, v1 // unsupported",
            ],
        )
        self.assertEqual(res["total_instructions"], 2)
        self.assertEqual(res["supported_instructions"], 1)
        self.assertEqual(res["unsupported_count"], 1)
        self.assertEqual(res["support_percentage"], 50.0)
        self.assertEqual(res["unsupported_details"][0]["raw"], "v_imaginary_opcode_xyz v0, v1")

    def test_cli_scanner(self):
        """Invoke scanner via its actual CLI entry point on synthetic assembly file."""
        canonical_shader = "\n".join([
            "s_mov_b64 s[50:51], exec",
            "s_wqm_b64 exec, exec",
            "s_mov_b32 m0, s24",
            "v_interp_p1_f32_e32 v8, v0, attr0.x",
            "v_interp_p1_f32_e32 v9, v0, attr0.y",
            "v_interp_p2_f32_e32 v9, v1, attr0.y",
            "v_interp_p2_f32_e32 v8, v1, attr0.x",
            "s_and_b64 exec, exec, s[50:51]",
            "s_mov_b32 s21, 0",
            "s_load_dwordx8 s[28:35], s[20:21], null",
            "s_mov_b32 s40, 1",
            "s_mov_b32 s41, 2",
            "s_mov_b32 s42, 3",
            "s_mov_b32 s43, 4",
            "s_waitcnt lgkmcnt(0)",
            "image_sample v[12:15], v[8:9], s[28:35], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D",
            "s_waitcnt vmcnt(0)",
            "v_cvt_pkrtz_f16_f32_e32 v16, v12, v13",
            "v_cvt_pkrtz_f16_f32_e32 v17, v14, v15",
            "exp mrt0 v16, v16, v17, v17 done compr vm",
            "s_endpgm",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            shader_file = tmp_path / "canonical.s"
            shader_file.write_text(".text\n.globl pixel\n.type pixel,@function\npixel:\n"
                                   + canonical_shader + "\n.size pixel, .-pixel\n", encoding="utf-8")
            out_dir = tmp_path / "scan_reports"
            script = Path(__file__).resolve().parents[1] / "tools" / "scan_unsupported_shaders.py"
            res = subprocess.run(
                [sys.executable, "-B", str(script), str(shader_file), "--output-dir", str(out_dir)],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(res.returncode, 0)
            self.assertIn("SCAN RESULTS SUMMARY", res.stdout)
            self.assertIn("Full Shaders Accepted by Translator:       1", res.stdout)
            self.assertTrue((out_dir / "shader_scan_report.json").is_file())
            self.assertTrue((out_dir / "shader_scan_report.md").is_file())
            with shader_file.open("a", encoding="utf-8") as stream:
                stream.write(".long 0\n")
            result = subprocess.run([sys.executable, "-B", str(script), str(shader_file),
                                     "--output-dir", str(out_dir)], capture_output=True, text=True, check=True)
            self.assertIn("Full Shaders Accepted by Translator:       0", result.stdout)

    def test_report_generation(self):
        canonical_shader = [
            "s_mov_b64 s[50:51], exec",
            "s_wqm_b64 exec, exec",
            "s_mov_b32 m0, s24",
            "v_interp_p1_f32_e32 v8, v0, attr0.x",
            "v_interp_p1_f32_e32 v9, v0, attr0.y",
            "v_interp_p2_f32_e32 v9, v1, attr0.y",
            "v_interp_p2_f32_e32 v8, v1, attr0.x",
            "s_and_b64 exec, exec, s[50:51]",
            "s_mov_b32 s21, 0",
            "s_load_dwordx8 s[28:35], s[20:21], null",
            "s_mov_b32 s40, 1",
            "s_mov_b32 s41, 2",
            "s_mov_b32 s42, 3",
            "s_mov_b32 s43, 4",
            "s_waitcnt lgkmcnt(0)",
            "image_sample v[12:15], v[8:9], s[28:35], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D",
            "s_waitcnt vmcnt(0)",
            "v_cvt_pkrtz_f16_f32_e32 v16, v12, v13",
            "v_cvt_pkrtz_f16_f32_e32 v17, v14, v15",
            "exp mrt0 v16, v16, v17, v17 done compr vm",
            "s_endpgm",
        ]
        rejected_shader = [
            "s_mov_b64 s[50:51], exec",
            "s_branch 0",
            "s_endpgm",
        ]
        results = [
            analyze_shader_instructions("accepted_ps", canonical_shader),
            analyze_shader_instructions("rejected_ps", rejected_shader),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            json_file, md_file = generate_reports(results, tmp_path)
            self.assertTrue(json_file.is_file())
            self.assertTrue(md_file.is_file())

            data = json.loads(json_file.read_text(encoding="utf-8"))
            summary = data["summary"]
            self.assertEqual(summary["total_shaders_scanned"], 2)
            self.assertEqual(summary["translator_accepted"], 1)
            self.assertEqual(summary["opcodes_recognized_translator_rejected"], 1)

    def test_detect_shader_stage(self):
        """Verify pipeline stage detection from file names and relative paths."""
        self.assertEqual(detect_shader_stage("shaders/pixel/ps_draw.bin"), "pixel")
        self.assertEqual(detect_shader_stage("cs_dispatch.bin"), "compute")
        self.assertEqual(detect_shader_stage("shaders/vertex/vs_main.s"), "vertex")
        self.assertEqual(detect_shader_stage("unknown_kernel.bin"), "other")

    def test_binary_shader_scanning(self):
        """Verify scanning raw .bin files directly with disasm_rdna2 without LLVM."""
        raw_code = bytes.fromhex(
            "000080bf"  # s_nop 0
            "7f008cbf"  # s_waitcnt
            "000081bf"  # s_endpgm
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bin_file = tmp_path / "ps_test.bin"
            bin_file.write_bytes(raw_code)
            results = scan_directory_or_files([bin_file])
            self.assertEqual(len(results), 1)
            res = results[0]
            self.assertEqual(res["shader_name"], "ps_test.bin")
            self.assertEqual(res["stage"], "pixel")
            self.assertEqual(res["total_instructions"], 3)
            self.assertTrue(res["opcodes_recognized"])

    def test_disassemble_binary_shader_error(self):
        """Verify disassemble_binary_shader raises on invalid or empty input."""
        with self.assertRaises(ValueError):
            disassemble_binary_shader(b"")

    def test_mixed_binary_shader_scanning(self):
        """Verify that failed/invalid binary inputs are retained in results and denominator."""
        valid_code = bytes.fromhex(
            "000080bf"  # s_nop 0
            "000081bf"  # s_endpgm
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            good_file = tmp_path / "ps_good.bin"
            good_file.write_bytes(valid_code)
            bad_file = tmp_path / "ps_bad.bin"
            bad_file.write_bytes(b"")  # Empty binary triggers decoder failure

            results = scan_directory_or_files([tmp_path])
            # Denominator must account for BOTH inputs
            self.assertEqual(len(results), 2)

            by_name = {r["shader_name"]: r for r in results}
            good_res = by_name.get("ps_good.bin")
            bad_res = by_name.get("ps_bad.bin")

            self.assertIsNotNone(good_res)
            self.assertEqual(good_res["total_instructions"], 2)
            self.assertEqual(good_res["supported_instructions"], 2)
            self.assertTrue(good_res["opcodes_recognized"])

            self.assertIsNotNone(bad_res)
            self.assertEqual(bad_res["total_instructions"], 0)
            self.assertFalse(bad_res["is_fully_supported"])
            self.assertFalse(bad_res["translator_accepted"])
            self.assertEqual(bad_res["lower_status"], "decode_failed")
            self.assertIn("empty", bad_res["lower_error"].lower())

            # Verify that dashboard accounts for both inputs and clearly labels instruction vs file metrics
            out_dir = tmp_path / "out"
            json_file, md_file = generate_progress_dashboard(results, out_dir)
            data = json.loads(json_file.read_text(encoding="utf-8"))

            # File-level denominator tested separately: two inputs, one decode failure
            self.assertEqual(data["overall"]["total_shaders"], 2)
            self.assertEqual(data["overall"]["completely_unsupported"], 1)
            self.assertEqual(data["overall"]["fully_accepted"], 0)

            # Instruction metric: every decoded instruction in valid_code is supported,
            # so instruction coverage legitimately reaches 100% while file denominator retains failure.
            self.assertEqual(data["overall"]["total_instructions"], 2)
            self.assertEqual(data["overall"]["supported_instructions"], 2)
            self.assertEqual(data["overall"]["instruction_coverage_percentage"], 100.0)
            self.assertEqual(data["overall"]["coverage_percentage"], 100.0)

            md_text = md_file.read_text(encoding="utf-8")
            self.assertIn("| **Total Shaders Analyzed** | 2 | 100.0% |", md_text)
            self.assertIn("| **Unsupported / Blocked** | 1 | 50.0% |", md_text)
            self.assertIn("| **Total Decoded Instructions** | 2 | 100.0% |", md_text)
            self.assertIn("Instruction Coverage:", md_text)

    def test_dashboard_report_generation(self):
        """Verify generation of PROGRESS.md and progress.json."""
        canonical_shader = [
            "s_mov_b64 s[50:51], exec",
            "s_wqm_b64 exec, exec",
            "s_mov_b32 m0, s24",
            "v_interp_p1_f32_e32 v8, v0, attr0.x",
            "v_interp_p1_f32_e32 v9, v0, attr0.y",
            "v_interp_p2_f32_e32 v9, v1, attr0.y",
            "v_interp_p2_f32_e32 v8, v1, attr0.x",
            "s_and_b64 exec, exec, s[50:51]",
            "s_mov_b32 s21, 0",
            "s_load_dwordx8 s[28:35], s[20:21], null",
            "s_mov_b32 s40, 1",
            "s_mov_b32 s41, 2",
            "s_mov_b32 s42, 3",
            "s_mov_b32 s43, 4",
            "s_waitcnt lgkmcnt(0)",
            "image_sample v[12:15], v[8:9], s[28:35], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D",
            "s_waitcnt vmcnt(0)",
            "v_cvt_pkrtz_f16_f32_e32 v16, v12, v13",
            "v_cvt_pkrtz_f16_f32_e32 v17, v14, v15",
            "exp mrt0 v16, v16, v17, v17 done compr vm",
            "s_endpgm",
        ]
        results = [analyze_shader_instructions("ps_canonical", canonical_shader)]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            json_file, md_file = generate_progress_dashboard(results, tmp_path)
            self.assertTrue(json_file.is_file())
            self.assertTrue(md_file.is_file())
            md_content = md_file.read_text(encoding="utf-8")
            self.assertIn("Instruction Coverage:", md_content)
            self.assertIn("Pipeline Stage Breakdown", md_content)
            json_content = json.loads(json_file.read_text(encoding="utf-8"))
            self.assertIn("overall", json_content)
            self.assertIn("stages", json_content)
            self.assertIn("missing_opcodes_ranked", json_content)


if __name__ == "__main__":
    unittest.main()
