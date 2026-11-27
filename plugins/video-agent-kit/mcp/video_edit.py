"""Stodex Video Agent Kit's media MCP service."""
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from media import AUDIO, IMAGE, VIDEO, binary, bounds, dimensions, ff, normalize, output, probe, rendered, run, source
from protocol import BOOL, INTEGER, NUMBER, POSITIVE, STRING, TIME, choice, fields, listed, picture, result, serve, tool

CLIP = fields({"path": STRING, "start": TIME, "end": POSITIVE, "seconds": POSITIVE}, ["path"])
CUE = fields({"start": TIME, "end": POSITIVE, "text": STRING}, ["start", "end", "text"])


@tool("Inspect codecs, dimensions, audio tracks, duration and byte count for a local media file.", fields({"path": STRING}, ["path"]))
def probe_media(path):
    return probe(source(path, VIDEO | AUDIO | IMAGE))


@tool("Read visible evidence at exact times. Returns JPEG images to Stodex plus their timestamps.", fields({"path": STRING, "timestamps": listed(TIME, 1, 12)}, ["path", "timestamps"]))
def extract_frames(path, timestamps):
    media = source(path, VIDEO)
    duration = probe(media)["duration"]
    items = []
    with tempfile.TemporaryDirectory() as tmp:
        for index, time in enumerate(timestamps):
            if time >= duration:
                raise ValueError(f"Timestamp {time} is outside the {duration}s clip")
            frame = Path(tmp) / f"{index}.jpg"
            ff(["-ss", time, "-i", media, "-frames:v", 1, "-vf", "scale=w='min(720,iw)':h='min(720,ih)':force_original_aspect_ratio=decrease", "-q:v", 4, frame])
            if not frame.is_file():
                raise ValueError(f"No frame at {time}; seek slightly earlier")
            items.extend([result({"time": time, "source": media.name}), picture(frame)])
    return items


@tool("Frame-accurate cut or transcode to MP4 with optional resize, mute and compression.", fields({"path": STRING, "output_path": STRING,
      "start": TIME, "end": POSITIVE, "width": INTEGER, "mute": BOOL, "crf": INTEGER}, ["path", "output_path"]))
def edit_clip(path, output_path, start=0, end=None, width=None, mute=False, crf=20):
    media = source(path, VIDEO)
    span = bounds(media, start, end)
    if not 0 <= crf <= 51 or width is not None and not (16 <= width <= 3840 and width % 2 == 0):
        raise ValueError("Use CRF 0–51 and an even output width between 16 and 3840")
    with output(output_path, {".mp4"}) as dest:
        ff(["-ss", start, "-i", media, "-t", span, "-map", "0:v:0", "-map", "0:a?", "-vf",
            f"scale={width}:-2" if width else "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-crf", crf,
            "-pix_fmt", "yuv420p", "-preset", "veryfast", *(["-an"] if mute else ["-c:a", "aac"]), "-movflags", "+faststart", dest])
    return rendered(output_path)


@tool("Assemble local clips and stills in the given order. start/end are source seconds, seconds controls the hold for stills. Keeps original audio and supplies silence for silent clips.", fields(
      {"clips": listed(CLIP, 1, 128), "output_path": STRING, "width": INTEGER, "height": INTEGER, "fps": INTEGER}, ["clips", "output_path"]))
def assemble(clips, output_path, width=1280, height=720, fps=30):
    dimensions(width, height)
    if not 1 <= fps <= 120:
        raise ValueError("FPS must be between 1 and 120")
    with output(output_path, {".mp4"}) as dest:
        manifest = []
        timeline = []
        cursor = 0.
        for i, item in enumerate(clips):
            part = dest.parent / f"part-{i:04d}.mp4"
            span = normalize(item, part, width, height, fps)
            manifest.append("file " + part.name)
            timeline.append({"source": item["path"], "start": cursor, "end": cursor + span})
            cursor += span
        join = dest.parent / "clips.txt"
        join.write_text("\n".join(manifest) + "\n", encoding="ascii")
        ff(["-f", "concat", "-safe", 1, "-i", join, "-c", "copy", "-movflags", "+faststart", dest])
    return rendered(output_path) | {"timeline": timeline}


def clock(t):
    value = round(t * 1000)
    return f"{value // 3600000:02d}:{value // 60000 % 60:02d}:{value // 1000 % 60:02d},{value % 1000:03d}"


@tool("Write UTF-8 SRT from ordered, nonoverlapping timed cues.", fields({"cues": listed(CUE, 1, 15000), "output_path": STRING}, ["cues", "output_path"]))
def write_subtitles(cues, output_path):
    previous = 0
    rows = []
    for i, cue in enumerate(cues, 1):
        if cue["start"] < previous or round(cue["end"] * 1000) <= round(cue["start"] * 1000):
            raise ValueError(f"Overlapping, empty or unordered caption {i}")
        rows.append(f"{i}\n{clock(cue['start'])} --> {clock(cue['end'])}\n{cue['text'].strip()}\n")
        previous = cue["end"]
    with output(output_path, {".srt"}) as dest:
        dest.write_text("\n".join(rows), encoding="utf-8")
    return {"path": str(Path(output_path).resolve()), "captions": len(cues), "end": previous}


@tool("Burn an SRT or ASS subtitle file into a new MP4. Keeps original audio.", fields({"path": STRING, "subtitles": STRING, "output_path": STRING}, ["path", "subtitles", "output_path"]))
def burn_subtitles(path, subtitles, output_path):
    media, captions = source(path, VIDEO), source(subtitles, {".srt", ".ass"})
    with output(output_path, {".mp4"}) as dest:
        local = dest.parent / ("captions" + captions.suffix.lower())
        shutil.copyfile(captions, local)
        ff(["-i", media, "-vf", "subtitles=" + local.name, "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-map", "0:v:0", "-map", "0:a?", "-c:a", "aac", "-movflags", "+faststart", dest], dest.parent)
    return rendered(output_path)


@tool("Replace the soundtrack with a narration file or mix it under the original picture. Pads short narration and trims long narration to picture length.", fields(
      {"path": STRING, "audio": STRING, "output_path": STRING, "original_volume": NUMBER}, ["path", "audio", "output_path"]))
def dub(path, audio, output_path, original_volume=0):
    media, voice = source(path, VIDEO), source(audio, AUDIO)
    info = probe(media)
    if not 0 <= original_volume <= 1:
        raise ValueError("original_volume must be 0–1")
    mix = original_volume and any(s["codec_type"] == "audio" for s in info["streams"])
    graph = f"[0:a]volume={original_volume}[bed];[1:a]apad[v];[bed][v]amix=inputs=2:duration=longest:normalize=0[a]" if mix else "[1:a:0]apad[a]"
    with output(output_path, {".mp4"}) as dest:
        ff(["-i", media, "-i", voice, "-filter_complex", graph, "-map", "0:v:0", "-map", "[a]",
            "-t", info["duration"], "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", dest])
    return rendered(output_path)


@tool("Find long pauses in a talking-head track and return a cut list. Pass the approved list to assemble to remove pauses.", fields(
      {"path": STRING, "minimum_pause": POSITIVE, "threshold_db": NUMBER, "pad": TIME}, ["path"]))
def detect_pauses(path, minimum_pause=0.7, threshold_db=-38, pad=0.12):
    import subprocess
    p = source(path, VIDEO | AUDIO)
    info = probe(p)
    if not any(s["codec_type"] == "audio" for s in info["streams"]):
        raise ValueError("No audio track to analyze")
    if not -90 <= threshold_db <= -5 or pad * 2 >= minimum_pause:
        raise ValueError("Use -90 to -5 dB and padding shorter than half the minimum pause")
    proc = subprocess.run([binary("ffmpeg"), "-hide_banner", "-nostdin", "-i", str(p), "-vn", "-af",
                        f"silencedetect=n={threshold_db}dB:d={minimum_pause}", "-f", "null", "-"],
                        capture_output=True, timeout=550, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if proc.returncode:
        raise ValueError(proc.stderr.decode(errors="replace")[-1800:])
    log = proc.stderr.decode("utf-8", "replace")
    starts = [float(t) for t in re.findall(r"silence_start: ([\d.]+)", log)]
    stops = [float(t) for t in re.findall(r"silence_end: ([\d.]+)", log)]
    clips, cursor = [], 0.
    for a, b in zip(starts, stops + [info["duration"]]):
        if a + pad > cursor:
            clips.append({"path": str(p), "start": cursor, "end": min(a+pad, info["duration"])})
        cursor = max(cursor, b-pad)
    if cursor < info["duration"]:
        clips.append({"path": str(p), "start": cursor, "end": info["duration"]})
    return {"duration": info["duration"], "clips": clips}


@tool("Encode sequentially numbered PNG animation frames to MP4. Names must be 000001.png, 000002.png etc. Equal dimensions are required.", fields(
      {"directory": STRING, "output_path": STRING, "fps": INTEGER}, ["directory", "output_path", "fps"]))
def render_frames(directory, output_path, fps):
    directory = Path(directory).resolve(strict=True)
    numbered = sorted(f for f in directory.glob("*.png") if re.fullmatch(r"\d{6}\.png", f.name))
    if not numbered or not 1 <= fps <= 120:
        raise ValueError("Supply six-digit PNG frames and FPS 1–120")
    first = int(numbered[0].stem)
    if any(int(p.stem) != first+i for i,p in enumerate(numbered)):
        raise ValueError("Frame sequence contains gaps")
    with output(output_path, {".mp4"}) as dest:
        ff(["-framerate", fps, "-start_number", first, "-i", directory / "%06d.png", "-frames:v", len(numbered), "-vf",
            "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", dest])
    return rendered(output_path)


@tool("Composite a supplied, aligned full-frame replacement using an animated grayscale matte. White selects replacement pixels. The original clip supplies timing and sound.", fields(
      {"path": STRING, "replacement": STRING, "matte": STRING, "output_path": STRING}, ["path", "replacement", "matte", "output_path"]))
def replace_subject(path, replacement, matte, output_path):
    original = source(path, VIDEO)
    info = probe(original)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    w, h = video["width"], video["height"]
    args = ["-i", original]
    for item in [replacement, matte]:
        p = source(item, VIDEO | IMAGE)
        if p.suffix.lower() in IMAGE:
            args += ["-loop", "1"]
        elif probe(p)["duration"] + .05 < info["duration"]:
            raise ValueError("Replacement and matte must cover the original clip")
        args += ["-i", p]
    # RGB masks must cover all three channels for maskedmerge.
    graph = (f"[0:v]format=gbrp,setsar=1[a];[1:v]scale={w}:{h},format=gbrp,setsar=1[b];"
             f"[2:v]scale={w}:{h},format=gray,format=gbrp,setsar=1[m];[a][b][m]maskedmerge,format=yuv420p[v]")
    with output(output_path, {".mp4"}) as dest:
        ff([*args, "-filter_complex", graph, "-map", "[v]", "-map", "0:a?", "-t", info["duration"],
            "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart", dest])
    return rendered(output_path)


# Register audio tools and the result reader for jobs submitted by older installations.
import models

if __name__ == "__main__":
    serve("video-edit")
