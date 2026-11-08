"""Phase 2 deep parsing (PLAN.md §4.2): archive the video, pull keyframes, transcribe the audio.

Travel videos often name the place only in an on-screen caption or the voice-over, so Claude gets 4-6
keyframes (it reads text overlays with vision) and a local faster-whisper transcript. All of it is
optional: without ffmpeg or faster-whisper the pipeline still runs and records a note.
"""

import logging
import shutil
import subprocess
from pathlib import Path

from app.config import Settings
from app.sources import Signals, ytdlp_options

log = logging.getLogger("wander.deep")

MAX_VIDEO_SECONDS = 15 * 60
KEYFRAMES = 5
TRANSCRIPT_CHARS = 5000
_whisper = None


def deepen(signals: Signals, settings: Settings, workdir: Path) -> None:
    if not signals.url:
        return
    if signals.duration_s and signals.duration_s > MAX_VIDEO_SECONDS:
        signals.notes.append("The video is long, so only its caption was read.")
        return
    video = download_video(signals.url, settings, workdir)
    if video is None:
        signals.notes.append("Couldn't download the video for a closer look.")
        return
    signals.video_path = video
    if shutil.which("ffmpeg"):
        signals.keyframe_paths = keyframes(
            video, workdir, signals.duration_s or probe_duration(video)
        )
    else:
        signals.notes.append("ffmpeg isn't installed, so no keyframes were read.")
    text = transcribe(video, settings)
    if text:
        signals.transcript = text[:TRANSCRIPT_CHARS]


def download_video(url: str, settings: Settings, workdir: Path) -> Path | None:
    import yt_dlp

    opts = ytdlp_options(settings)
    opts.update(
        {
            # Separate streams merged by ffmpeg where needed; never above 720p (PLAN.md decision 5).
            "format": "bv*[height<=720]+ba/b[height<=720]/bv*+ba/b",
            "merge_output_format": "mp4",
            "outtmpl": str(workdir / "video.%(ext)s"),
            "max_filesize": 300 * 1024 * 1024,
            "overwrites": True,
            "noprogress": True,
        }
    )
    opts.pop("skip_download", None)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as exc:  # noqa: BLE001
        log.warning("video download failed for %s: %s", url, exc)
        return None
    found = sorted(workdir.glob("video.*"))
    return found[0] if found else None


def probe_duration(video: Path) -> float | None:
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
            capture_output=True, text=True, timeout=30, check=True,
        )  # fmt: skip
        return float(out.stdout.strip())
    except (subprocess.SubprocessError, ValueError):
        return None


def keyframes(video: Path, workdir: Path, duration: float | None) -> list[Path]:
    duration = duration or 30.0
    paths = []
    for i in range(KEYFRAMES):
        at = duration * (0.08 + 0.84 * i / max(1, KEYFRAMES - 1))
        out = workdir / f"frame{i}.jpg"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{at:.2f}", "-i", str(video),
                 "-frames:v", "1", "-vf", "scale='min(720,iw)':-2", "-q:v", "4", str(out)],
                capture_output=True, timeout=60, check=True,
            )  # fmt: skip
        except subprocess.SubprocessError:
            continue
        if out.is_file() and out.stat().st_size > 0:
            paths.append(out)
    return paths


def transcribe(video: Path, settings: Settings) -> str | None:
    global _whisper
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    try:
        if _whisper is None:
            # About 20-40 s per minute of audio for "small" int8 on a low-power CPU (PLAN.md §4.2).
            _whisper = WhisperModel(
                settings.whisper_model,
                device="cpu",
                compute_type="int8",
                download_root=str(settings.data_dir / "models"),
            )
        audio = decode_audio(video)
        if audio is None:
            return None
        segments, _info = _whisper.transcribe(audio, vad_filter=True, beam_size=1)
        return " ".join(seg.text.strip() for seg in segments).strip() or None
    except Exception as exc:  # noqa: BLE001
        log.warning("transcription failed for %s: %s", video, exc)
        return None


def decode_audio(video: Path):
    """16 kHz mono float32 samples via ffmpeg (sidesteps faster-whisper's PyAV decoding)."""
    if not shutil.which("ffmpeg"):
        return None
    import numpy as np

    try:
        out = subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
            capture_output=True, timeout=300, check=True,
        )  # fmt: skip
    except subprocess.SubprocessError:
        return None
    samples = np.frombuffer(out.stdout, dtype=np.float32)
    return samples if samples.size else None


def prune_videos(settings: Settings) -> list[str]:
    """Delete the oldest archived videos until the archive fits under the cap. Returns their relative paths."""
    cap = settings.video_archive_max_gb * 1024**3
    videos = sorted(settings.media_dir.glob("*/video.*"), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in videos)
    removed = []
    while videos and total > cap:
        oldest = videos.pop(0)
        total -= oldest.stat().st_size
        oldest.unlink(missing_ok=True)
        removed.append(oldest.relative_to(settings.data_dir).as_posix())
    return removed
