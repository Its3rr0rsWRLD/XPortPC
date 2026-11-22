"""Assemble the original and the logical-window shader and check rejection paths."""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import spirv_address_window as window

fixture = Path(__file__).with_name("subtract.spvasm")
original = fixture.read_text(encoding="utf-8")
adapted = window.lower(original)
assert "OpMemoryModel Logical GLSL450" in adapted
assert "OpConvertUToPtr" not in adapted and "OpUGreaterThanEqual" in adapted
for source, reason in (
    (original.replace("OpDecorate %UserData Block", "OpDecorate %user_data DescriptorSet 2\nOpDecorate %UserData Block"),
     "descriptor sets"),
    (original.replace("OpStore %p2 %d", "%leak = OpConvertPtrToU %ulong %p2\nOpStore %p2 %d"),
     "physical word pointer"),
    (original.replace("OpTypePointer PhysicalStorageBuffer %uint", "OpTypePointer PhysicalStorageBuffer %ulong"),
     "scalar layout"),
):
    try:
        window.lower(source)
    except ValueError as error:
        assert reason in str(error), error
    else:
        raise AssertionError(f"accepted invalid profile: {reason}")

with tempfile.TemporaryDirectory() as directory:
    target = Path(directory) / "window.spv"
    tool = [sys.executable, "-B", str(ROOT / "tools" / "spirv_address_window.py")]
    subprocess.run([*tool, fixture, target], check=True)
    valid = target.read_bytes()
    assert valid[:4] == bytes.fromhex("03022307")
    broken = Path(directory) / "broken.spvasm"
    broken.write_text(original.replace("%b = OpLoad %uint %p1", "%b = OpLoad %uint %undefined"), encoding="utf-8")
    failed = subprocess.run([*tool, broken, target], capture_output=True)
    assert failed.returncode and target.read_bytes() == valid
print("physical and logical SPIR-V validated; rejection cases passed")
