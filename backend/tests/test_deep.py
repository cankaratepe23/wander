import os

from app import deep
from app.config import Settings


def test_prune_deletes_oldest_videos_until_under_the_cap(tmp_path):
    settings = Settings(data_dir=tmp_path, video_archive_max_gb=2500 / 1024**3)  # 2,500-byte cap
    for i, age in enumerate([300, 200, 100]):  # capture 0 is the oldest
        d = tmp_path / "media" / str(i)
        d.mkdir(parents=True)
        f = d / "video.mp4"
        f.write_bytes(b"x" * 1000)
        os.utime(f, (1_000_000 - age, 1_000_000 - age))
    removed = deep.prune_videos(settings)
    assert removed == ["media/0/video.mp4"]
    assert sorted(p.parent.name for p in (tmp_path / "media").glob("*/video.*")) == ["1", "2"]


def test_long_videos_skip_deep_parsing(tmp_path):
    from app.sources import Signals

    s = Signals(platform="youtube", url="https://youtu.be/x", duration_s=deep.MAX_VIDEO_SECONDS + 1)
    deep.deepen(s, Settings(data_dir=tmp_path), tmp_path)
    assert s.video_path is None and "long" in s.notes[0]
