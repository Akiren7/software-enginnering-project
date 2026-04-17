"""
replay_recorder_macos.py -- macOS-only rolling screen recorder using FFmpeg.

Purpose:
    Keep the last N seconds of the screen in rolling .ts segments.
    When save_replay() is called, merge the currently buffered segments into one mp4.

Designed to be called only on macOS after your main launcher checks sys.platform.

Example:
    from replay_recorder_macos import MacReplayRecorder

    rec = MacReplayRecorder(session_uuid="session123")
    rec.start()
    # ... later ...
    path = rec.save_replay()
    rec.stop()

Notes:
    - Requires ffmpeg in PATH.
    - Requires macOS Screen Recording permission for the app/process that launches ffmpeg.
    - First run device discovery with:
          python replay_recorder_macos.py --list-devices
      Then set mac_video_device to the index/name that corresponds to the screen.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from typing import Optional


class MacReplayRecorder:
    def __init__(
        self,
        session_uuid: str,
        base_dir: str = "recordings",
        segment_time: int = 5,
        total_duration: int = 60,
        mac_video_device: str = "1",
        mac_audio_device: str = "none",
        fps: int = 30,
    ):
        self.session_uuid = session_uuid
        self.base_dir = base_dir
        self.root_dir = os.path.join("data", "client", session_uuid, base_dir)
        self.cache_dir = os.path.join(self.root_dir, "cache")
        self.output_dir = os.path.join(self.root_dir, "replays")
        self.segment_time = int(segment_time)
        self.total_duration = int(total_duration)
        self.max_segments = max(1, self.total_duration // self.segment_time)
        self.mac_video_device = str(mac_video_device)
        self.mac_audio_device = str(mac_audio_device)
        self.fps = int(fps)

        self._process: Optional[subprocess.Popen] = None
        self._running = False
        self._log_file = None
        self._log_path = os.path.join(self.cache_dir, "ffmpeg.log")

        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Device helpers
    # ------------------------------------------------------------------

    @staticmethod
    def list_avfoundation_devices() -> str:
        """
        Return FFmpeg avfoundation device listing text.
        FFmpeg prints it to stderr.
        """
        cmd = ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.stderr.strip() or result.stdout.strip()

    def _build_capture_args(self) -> list[str]:
        if sys.platform != "darwin":
            raise RuntimeError(f"MacReplayRecorder can only run on macOS, got: {sys.platform}")

        input_spec = f"{self.mac_video_device}:{self.mac_audio_device}"
        return [
            "-f", "avfoundation",
            "-framerate", str(self.fps),
            "-capture_cursor", "1",
            "-i", input_spec,
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> bool:
        if self._running:
            print("[MAC RECORDER] Already running.")
            return True

        self._cleanup_cache()

        try:
            capture_args = self._build_capture_args()
        except Exception as exc:
            print(f"[MAC RECORDER] ERROR: {exc}")
            return False

        keyint = self.fps * self.segment_time
        segment_pattern = os.path.join(self.cache_dir, "cache_%03d.ts")
        segment_list = os.path.join(self.cache_dir, "replay.m3u8")

        cmd = [
            "ffmpeg",
            "-y",
            *capture_args,
            "-pix_fmt", "yuv420p",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-g", str(keyint),
            "-keyint_min", str(keyint),
            "-sc_threshold", "0",
            "-force_key_frames", f"expr:gte(t,n_forced*{self.segment_time})",
            "-f", "segment",
            "-segment_time", str(self.segment_time),
            "-segment_list", segment_list,
            "-segment_list_size", str(self.max_segments),
            "-segment_wrap", str(self.max_segments + 2),
            "-segment_format", "mpegts",
            "-reset_timestamps", "1",
            segment_pattern,
        ]

        try:
            self._log_file = open(self._log_path, "w", encoding="utf-8")
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=self._log_file,
            )
            self._running = True
            print("[MAC RECORDER] Started FFmpeg screen recording.")

            time.sleep(1.5)
            if self._process.poll() is not None:
                self._running = False
                self._safe_close_log()
                tail = self._read_log_tail()
                print("[MAC RECORDER] ERROR: FFmpeg exited immediately.")
                if tail:
                    print(tail)
                self._process = None
                return False

            return True

        except FileNotFoundError:
            self._running = False
            self._safe_close_log()
            print("[MAC RECORDER] ERROR: ffmpeg not found in PATH.")
            return False
        except Exception as exc:
            self._running = False
            self._safe_close_log()
            print(f"[MAC RECORDER] ERROR: failed to start recorder: {exc}")
            return False

    def save_replay(self) -> Optional[str]:
        if not self._running:
            print("[MAC RECORDER] Not running, nothing to save.")
            return None

        if self._process and self._process.poll() is not None:
            print("[MAC RECORDER] FFmpeg process is no longer alive.")
            self._running = False
            tail = self._read_log_tail()
            if tail:
                print(tail)
            return None

        m3u8_path = os.path.join(self.cache_dir, "replay.m3u8")
        if not os.path.exists(m3u8_path):
            print("[MAC RECORDER] No segment list yet. Wait a few seconds.")
            return None

        segments = []
        with open(m3u8_path, "r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if line and not line.startswith("#"):
                    seg_path = os.path.join(self.cache_dir, line)
                    if os.path.exists(seg_path):
                        segments.append(seg_path)

        if not segments:
            print("[MAC RECORDER] No valid segments available to save.")
            return None

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_file = os.path.join(self.output_dir, f"replay_{timestamp}.mp4")
        concat_list_path = os.path.join(self.cache_dir, "concat_list.txt")

        with open(concat_list_path, "w", encoding="utf-8") as handle:
            for seg in segments:
                escaped = seg.replace("'", r"'\\''")
                handle.write(f"file '{escaped}'\n")

        merge_cmd = [
            "ffmpeg",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_list_path,
            "-c", "copy",
            output_file,
        ]

        result = subprocess.run(merge_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print("[MAC RECORDER] ERROR: replay merge failed.")
            tail = (result.stderr or result.stdout or "").strip()
            if tail:
                print("\n".join(tail.splitlines()[-20:]))
            return None

        print(f"[MAC RECORDER] Replay saved to: {output_file}")
        return output_file

    def stop(self):
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)
            except Exception as exc:
                print(f"[MAC RECORDER] Warning while stopping ffmpeg: {exc}")
            finally:
                self._process = None

        self._safe_close_log()
        self._running = False
        self._cleanup_cache()
        print("[MAC RECORDER] Stopped.")

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _safe_close_log(self):
        if self._log_file:
            try:
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None

    def _read_log_tail(self, max_lines: int = 30) -> str:
        try:
            if not os.path.exists(self._log_path):
                return ""
            with open(self._log_path, "r", encoding="utf-8", errors="replace") as handle:
                lines = handle.read().splitlines()
            return "\n".join(lines[-max_lines:])
        except Exception:
            return ""

    def _cleanup_cache(self):
        if not os.path.isdir(self.cache_dir):
            return
        for filename in os.listdir(self.cache_dir):
            path = os.path.join(self.cache_dir, filename)
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except Exception as exc:
                print(f"[MAC RECORDER] Warning: could not delete {path}: {exc}")


if __name__ == "__main__":
    if "--list-devices" in sys.argv:
        print(MacReplayRecorder.list_avfoundation_devices())
        raise SystemExit(0)

    print("This is a macOS-only recorder module.")
    print("Use --list-devices to discover the screen device index/name.")
