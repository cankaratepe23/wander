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


def test_backup_keeps_a_consistent_copy_and_rotates(tmp_path):
    import sqlite3
    from datetime import UTC, datetime, timedelta

    from app import backup

    settings = Settings(data_dir=tmp_path)
    con = sqlite3.connect(settings.db_path)
    con.execute("create table t(x)")
    con.execute("insert into t values (42)")
    con.commit()
    start = datetime(2026, 11, 1, tzinfo=UTC)
    for day in range(9):
        path = backup.backup(settings, start + timedelta(days=day))
    con.close()
    assert sqlite3.connect(path).execute("select x from t").fetchone() == (42,)
    assert len(list((tmp_path / "backups").glob("wander-*.db"))) == backup.KEEP
    nxt = backup.next_run(datetime(2026, 11, 8, 2, 0, tzinfo=UTC), "UTC")
    assert (nxt.day, nxt.hour, nxt.minute) == (8, 3, 17)
