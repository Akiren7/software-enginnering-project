from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import argparse


class MacReplayRecorder:
    def __init__(
        self,
        session_uuid: str,
        base_dir: str = "recordings",
        segment_time: int = 5,
        total_duration: int = 60,
        fps: int = 30,
        mac_audio_device: str = "none",
    ):
        self.root_dir = os.path.join(base_dir, session_uuid)
        self.cache_dir = os.path.join(self.root_dir, "cache")
        self.output_dir = os.path.join(self.root_dir, "replays")
        self.segment_time = int(segment_time)
        self.total_duration = int(total_duration)
        self.max_segments = max(1, self.total_duration // self.segment_time)
        self.fps = int(fps)
        self.mac_audio_device = mac_audio_device

        self.process = None
        self.video_device = None

        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

    @staticmethod
    def list_devices():
        result = subprocess.run(
            ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True,
            text=True,
        )
        return result.stderr or result.stdout

    @classmethod
    def detect_screen_device(cls):
        text = cls.list_devices()
        for line in text.splitlines():
            if "screen" in line.lower():
                m = re.search(r"\[(\d+)\]", line)
                if m:
                    return m.group(1)
        return None

    def start(self):
        if sys.platform != "darwin":
            raise RuntimeError("This recorder is macOS-only.")

        if self.process:
            return True

        self.video_device = self.detect_screen_device()
        if self.video_device is None:
            print("Could not auto-detect screen device.")
            return False

        keyint = self.fps * self.segment_time
        segment_pattern = os.path.join(self.cache_dir, "cache_%03d.ts")
        segment_list = os.path.join(self.cache_dir, "replay.m3u8")

        cmd = [
            "ffmpeg",
            "-y",
            "-f", "avfoundation",
            "-framerate", str(self.fps),
            "-capture_cursor", "1",
            "-i", f"{self.video_device}:{self.mac_audio_device}",
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

        self.process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        time.sleep(1.5)
        if self.process.poll() is not None:
            self.process = None
            print("FFmpeg failed to start.")
            return False

        print(f"Started. Auto-selected screen device: {self.video_device}")
        return True

    def save_replay(self):
        if not self.process:
            print("Recorder is not running.")
            return None

        m3u8_path = os.path.join(self.cache_dir, "replay.m3u8")
        if not os.path.exists(m3u8_path):
            print("No replay list yet.")
            return None

        segments = []
        with open(m3u8_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    seg = os.path.join(self.cache_dir, line)
                    if os.path.exists(seg):
                        segments.append(seg)

        if not segments:
            print("No valid segments found.")
            return None

        concat_list = os.path.join(self.cache_dir, "concat_list.txt")
        with open(concat_list, "w", encoding="utf-8") as f:
            for seg in segments:
                f.write(f"file '{seg}'\n")

        out_file = os.path.join(
            self.output_dir,
            f"replay_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
        )

        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list,
                "-c", "copy",
                out_file,
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print("Replay merge failed.")
            return None

        print("Saved:", out_file)
        return out_file

    def stop(self):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
            print("Stopped.")

    def run_forever(self):
        if not self.start():
            return 1

        print("Recorder is running. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping recorder...")
            self.stop()
            return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="macOS rolling screen recorder")
    parser.add_argument("--list-devices", action="store_true", help="List FFmpeg AVFoundation devices")
    parser.add_argument("--session-uuid", default="standalone", help="Session id used for output folders")
    parser.add_argument("--base-dir", default="recordings", help="Base output directory")
    parser.add_argument("--segment-time", type=int, default=5, help="Segment length in seconds")
    parser.add_argument("--total-duration", type=int, default=60, help="Rolling buffer duration in seconds")
    parser.add_argument("--fps", type=int, default=30, help="Capture framerate")
    parser.add_argument("--audio-device", default="none", help="AVFoundation audio device index or 'none'")
    parser.add_argument("--save-on-exit", action="store_true", help="Save replay automatically when stopping")
    args = parser.parse_args()

    if args.list_devices:
        print(MacReplayRecorder.list_devices())
        raise SystemExit(0)

    recorder = MacReplayRecorder(
        session_uuid=args.session_uuid,
        base_dir=args.base_dir,
        segment_time=args.segment_time,
        total_duration=args.total_duration,
        fps=args.fps,
        mac_audio_device=args.audio_device,
    )

    try:
        exit_code = recorder.run_forever()
    finally:
        if args.save_on_exit:
            recorder.save_replay()

    raise SystemExit(exit_code)