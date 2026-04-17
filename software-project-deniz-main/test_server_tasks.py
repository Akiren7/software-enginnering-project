import asyncio
import io
import unittest
from unittest.mock import patch

from server.tasks import _queue_stdin_line


class _ImmediateLoop:
    def call_soon_threadsafe(self, callback, *args):
        callback(*args)


class _BrokenStdin:
    def __iter__(self):
        return self

    def __next__(self):
        raise OSError(5, "Input/output error")


class ServerTaskTests(unittest.TestCase):
    def _drain_queue(self, queue: asyncio.Queue) -> list[object]:
        items = []
        while True:
            try:
                items.append(queue.get_nowait())
            except asyncio.QueueEmpty:
                return items

    def test_queue_stdin_line_reads_all_lines_then_sends_sentinel(self):
        queue = asyncio.Queue()

        with patch("sys.stdin", io.StringIO("/help\n/exam\n")):
            _queue_stdin_line(_ImmediateLoop(), queue)

        self.assertEqual(self._drain_queue(queue), ["/help\n", "/exam\n", None])

    def test_queue_stdin_line_handles_input_output_error(self):
        queue = asyncio.Queue()

        with patch("sys.stdin", _BrokenStdin()), patch("builtins.print") as mock_print:
            _queue_stdin_line(_ImmediateLoop(), queue)

        self.assertEqual(self._drain_queue(queue), [None])
        self.assertTrue(mock_print.called)
        self.assertIn("Console input unavailable", mock_print.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
