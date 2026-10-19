"""Host-compiled three-motor sketch with fake I/O, never a real board."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class FirmwareContractTests(unittest.TestCase):
    def test_sketch_protocol_pins_quantization_and_rejection_without_hardware(self):
        compiler = shutil.which("clang++") or shutil.which("g++")
        if compiler is None:
            self.skipTest("Host C++ compiler unavailable; Arduino IDE build still required")
        source = Path(__file__).resolve().parent / "firmware"
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "contract"
            compiled = subprocess.run(
                [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", str(source),
                 str(source / "contract.cpp"), "-o", str(executable)],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Firmware contract passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
