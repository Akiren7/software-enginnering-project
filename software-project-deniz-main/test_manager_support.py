import sys
import tempfile
import time
import unittest
from pathlib import Path

from common.manager_support import ManagedProcessSession


class ManagerSupportTests(unittest.TestCase):
    def test_managed_process_session_captures_output_to_session_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = ManagedProcessSession(
                session_name="server_cli_session",
                log_dir=Path(temp_dir),
            )
            process = session.start(
                [
                    sys.executable,
                    "-u",
                    "-c",
                    "import sys; print('alpha'); sys.stderr.write('beta\\n')",
                ],
                cwd=temp_dir,
                env={},
            )
            process.wait(timeout=5)
            session._reader_thread.join(timeout=2)

            output = session.read_output_text()
            self.assertIn("alpha", output)
            self.assertIn("beta", output)
            self.assertIn("process exited with code 0", output)

    def test_managed_process_session_records_sent_commands(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = ManagedProcessSession(
                session_name="client_cli_session",
                log_dir=Path(temp_dir),
            )
            process = session.start(
                [
                    sys.executable,
                    "-u",
                    "-c",
                    (
                        "import sys; "
                        "print('ready'); "
                        "line = sys.stdin.readline().strip(); "
                        "print(f'echo:{line}')"
                    ),
                ],
                cwd=temp_dir,
                env={},
            )
            time.sleep(0.2)
            self.assertTrue(session.send_line("start"))
            process.wait(timeout=5)
            session._reader_thread.join(timeout=2)

            output = session.read_output_text()
            self.assertIn("[MANAGER] > start", output)
            self.assertIn("echo:start", output)


if __name__ == "__main__":
    unittest.main()
