import unittest
import sys
import os

# Ensure we can import the script
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from bump_version import calculate_next_version

class TestVersionLogic(unittest.TestCase):

    def test_stable_to_alpha_minor(self):
        # 1.2.3 (Stable) -> 1.3.0-alpha (Minor Bump)
        self.assertEqual(calculate_next_version("v1.2.3"), "1.3.0-alpha")
        self.assertEqual(calculate_next_version("1.0.0"), "1.1.0-alpha")

    def test_alpha_to_alpha_patch(self):
        # 1.3.0-alpha (Alpha) -> 1.3.1-alpha (Patch Bump)
        self.assertEqual(calculate_next_version("v1.3.0-alpha"), "1.3.1-alpha")
        self.assertEqual(calculate_next_version("2.2.5-alpha"), "2.2.6-alpha")

    def test_force_major(self):
        # 1.2.3 (Stable) + Force -> 2.0.0-alpha
        self.assertEqual(calculate_next_version("v1.2.3", force_major=True), "2.0.0-alpha")
        # 1.3.5-alpha (Alpha) + Force -> 2.0.0-alpha
        self.assertEqual(calculate_next_version("v1.3.5-alpha", force_major=True), "2.0.0-alpha")

    def test_legacy_tag_handling(self):
        # v2.0.2-alpha.1 (Legacy) -> treated as Alpha -> 2.0.3-alpha
        self.assertEqual(calculate_next_version("v2.0.2-alpha.1"), "2.0.3-alpha")

    def test_invalid_format(self):
        with self.assertRaises(ValueError):
            calculate_next_version("invalid-version")

if __name__ == '__main__':
    unittest.main()
