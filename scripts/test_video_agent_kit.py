"""Exercise the shipped stdio services with real FFmpeg and native speech output."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.request import urlopen


@contextmanager
def service(path, profile):
    with subprocess.Popen([sys.executable, "-I", "-B", "-u", str(path)], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, encoding="utf-8", env={**os.environ, "STODEX_MEDIA_MODELS": str(profile)}) as process:
        number = 0

        def rpc(method, params):
            nonlocal number
            number += 1
            process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": number, "method": method, "params": params}) + "\n")
            process.stdin.flush()
            reply = json.loads(process.stdout.readline())
            assert reply["id"] == number
            return reply["result"]

        def call(name, **arguments):
            reply = rpc("tools/call", {"name": name, "arguments": arguments})
            if reply.get("isError"):
                raise ValueError(reply["content"][0]["text"])
            return [json.loads(x["text"]) if x["type"] == "text" else x for x in reply["content"]]

        try:
            assert rpc("initialize", {"protocolVersion": "2025-06-18"})["protocolVersion"] == "2025-06-18"
            yield rpc("tools/list", {})["tools"], call
        finally:
            process.stdin.close()


def main():
    modules = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "plugins/video-agent-kit/mcp"
    with TemporaryDirectory() as temp:
        folder = Path(temp)
        profile = folder / "models.json"
        profile.write_text(json.dumps({k: {"mode": "local"} for k in ["video", "transcription", "speech"]}), encoding="utf-8")
        with service(modules / "runtime.py", profile) as (runtime_tools, runtime), service(modules / "video_edit.py", profile) as (video_tools, video):
            env = runtime("check_environment")[0]
            assert env["can_edit"]
            assert env["models"]["video"] == {"source": "stodex_model_settings", "tool": "call_model", "action": "list", "query": "video"}
            names = {tool["name"] for tool in video_tools}
            assert "generate_video" not in names and "video_result" in names
            (folder / "index.html").write_text("<h1>Stodex</h1>", encoding="utf-8")
            preview = runtime("preview_site", directory=temp)[0]
            with urlopen(preview["url"], timeout=5) as page:
                assert page.read() == b"<h1>Stodex</h1>"
            assert runtime("stop_preview", preview=preview["preview"])[0]["stopped"]
            def dest(name):
                return str(folder / name)
            subprocess.run([env["ffmpeg"], "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                            "testsrc2=size=320x180:rate=24:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", dest("source.mp4")], check=True)
            video("edit_clip", path=dest("source.mp4"), output_path=dest("cut.mp4"), start=0.5, end=2.5)
            seq = video("assemble", clips=[{"path": dest("cut.mp4")}, {"path": dest("source.mp4"), "start": 0, "end": 1}],
                        width=320, height=180, fps=24, output_path=dest("sequence.mp4"))[0]
            assert len(seq["timeline"]) == 2
            video("write_subtitles", cues=[{"start": 0.2, "end": 2.5, "text": "Video Agent Kit"}], output_path=dest("captions.srt"))
            video("burn_subtitles", path=dest("sequence.mp4"), subtitles=dest("captions.srt"), output_path=dest("captioned.mp4"))
            voice = video("narrate", text="Stodex video test.", output_path=dest("voice.wav"))[0]
            assert voice["duration"] > 0
            video("dub", path=dest("captioned.mp4"), audio=dest("voice.wav"), output_path=dest("finished.mp4"))
            info = video("probe_media", path=dest("finished.mp4"))[0]
            assert 2.9 < info["duration"] < 3.25 and {s["codec_name"] for s in info["streams"]} == {"h264", "aac"}, info
            evidence = video("extract_frames", path=dest("finished.mp4"), timestamps=[0.25, 2.6])
            assert [x["mimeType"] for x in evidence if "mimeType" in x] == ["image/jpeg", "image/jpeg"]
            print(json.dumps({"tools": [len(video_tools), len(runtime_tools)], "codecs": ["h264", "aac"], "duration": info["duration"], "frames": 2, "speech": voice["duration"]}))


if __name__ == "__main__":
    main()
