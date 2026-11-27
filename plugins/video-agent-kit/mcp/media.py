"""Local media paths, executable discovery, atomic outputs and normalized cuts."""
import contextlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


CONFIG = Path.home() / ".stodex" / "video-agent-kit.json"
VIDEO = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".ts", ".mpeg", ".mpg", ".gif"}
AUDIO = {".wav", ".mp3", ".aac", ".flac", ".ogg", ".m4a", ".opus", ".aiff"}
IMAGE = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def config():
    if not CONFIG.is_file():
        return {}
    item = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    if not isinstance(item, dict):
        raise ValueError(f"Expected a JSON object in {CONFIG}")
    return item


def binary(name, required=True):
    folder = os.environ.get("STODEX_VIDEO_FFMPEG_DIR") or config().get("ffmpeg_dir")
    value = shutil.which(name, path=str(folder)) if folder and name in ("ffmpeg", "ffprobe") else None
    value = value or shutil.which(name)
    if not value and required:
        raise ValueError(f"Missing {name}. Run the setup-guide command. Set ffmpeg_dir in {CONFIG} or add it to PATH.")
    return value


def source(value, extensions=None):
    p = Path(value).expanduser().resolve(strict=True)
    if not p.is_file() or extensions and p.suffix.lower() not in extensions:
        raise ValueError(f"Expected a supported file: {value}")
    return p


@contextlib.contextmanager
def output(value, extensions):
    p = Path(value).expanduser().resolve()
    if p.suffix.lower() not in extensions or p.exists():
        raise ValueError(f"Choose a new output path ending in {sorted(extensions)}: {p}")
    p.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".video-kit-", dir=p.parent) as folder:
        scratch = Path(folder) / ("result" + p.suffix.lower())
        yield scratch
        if not scratch.is_file() or not scratch.stat().st_size:
            raise ValueError("No output was rendered")
        # Publish completely written bytes and never replace an existing user file.
        try:
            os.link(scratch, p)
        except FileExistsError:
            raise ValueError(f"Output already exists: {p}") from None
        except OSError:
            with p.open("xb") as dest, scratch.open("rb") as src:
                try:
                    shutil.copyfileobj(src, dest)
                except BaseException:
                    dest.close()
                    p.unlink(missing_ok=True)
                    raise


def run(args, cwd=None, seconds=560, data=None):
    proc = subprocess.run([str(a) for a in args], input=data, capture_output=True,
                          cwd=cwd, timeout=seconds, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if proc.returncode:
        raise ValueError(proc.stderr.decode("utf-8", "replace")[-2200:] or f"{Path(args[0]).name} failed with {proc.returncode}")
    return proc.stdout


def ff(args, cwd=None):
    return run([binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *args], cwd=cwd)


def probe(p):
    raw = run([binary("ffprobe"), "-v", "error", "-show_entries",
               "format=duration,size,format_name:stream=index,codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels,pix_fmt,duration",
               "-of", "json", "-i", p], seconds=30)
    value = json.loads(raw)
    return {"path": str(p), "duration": float(value["format"].get("duration") or 0),
            "bytes": int(value["format"].get("size") or 0), "streams": value.get("streams", [])}


def rendered(value):
    return probe(Path(value).expanduser().resolve())


def dimensions(w, h):
    if not (16 <= w <= 3840 and 16 <= h <= 3840 and w % 2 == h % 2 == 0):
        raise ValueError("Use even canvas dimensions between 16 and 3840")


def bounds(p, start, end):
    duration = probe(p)["duration"]
    stop = duration if end is None else end
    if not (0 <= start < stop <= duration + .06):
        raise ValueError(f"Invalid cut {start}–{stop} for duration {duration:.3f}")
    return min(stop, duration) - start


def normalize(item, dest, w, h, fps):
    p = source(item["path"], VIDEO | IMAGE)
    start = item.get("start", 0)
    if p.suffix.lower() in IMAGE:
        if start:
            raise ValueError("Still image timing is controlled by seconds")
        duration = item.get("seconds", 3)
        args = ["-loop", "1", "-framerate", fps, "-i", p]
        audio = False
    else:
        duration = bounds(p, start, item.get("end"))
        args = ["-ss", start, "-i", p]
        audio = any(s["codec_type"] == "audio" for s in probe(p)["streams"])
    if not audio:
        args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    ff([*args, "-t", duration, "-map", "0:v:0", "-map", "0:a:0" if audio else "1:a:0",
        "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p",
        "-af", "aresample=48000,apad", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-ac", 2, "-ar", 48000,
        "-video_track_timescale", 90000, dest])
    return duration
