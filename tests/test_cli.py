import json
import subprocess
import sys
import tempfile
import unittest


class CliTests(unittest.TestCase):
    def test_stats_command_works_without_gui(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'orca_flow', '--data-dir', directory, '--stats'],
                                    capture_output=True, encoding='utf-8', timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['customers'], 0)
