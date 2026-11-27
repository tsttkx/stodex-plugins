"""Environment and localhost site previews used by Stodex video workflows."""
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import mimetypes
import os
from pathlib import Path
import platform
import shutil
import sys
from threading import Thread
from urllib.parse import unquote, urlsplit
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from media import binary, CONFIG, config, run
from protocol import BOOL, STRING, fields, serve, tool

previews = {}


@tool("Check local editing tools, Python and audio settings. List available video models through the Stodex call_model tool.", fields({}))
def check_environment():
    import json
    local = config()
    ffmpeg = binary("ffmpeg", False)
    ffprobe = binary("ffprobe", False)
    model_file = os.getenv("STODEX_MEDIA_MODELS")
    settings = json.loads(Path(model_file).read_text("utf-8")) if model_file and Path(model_file).is_file() else {}
    modes = {key: {"mode": settings.get(key, {}).get("mode", "local"), "model": settings.get(key, {}).get("model", "")}
             for key in ("speech", "transcription")}
    modes["video"] = {"source": "stodex_model_settings", "tool": "call_model", "action": "list", "query": "video"}
    return {"python": sys.version.split()[0], "platform": platform.system(), "workspace": str(Path.cwd()), "ffmpeg": ffmpeg,
            "ffprobe": ffprobe, "can_edit": bool(ffmpeg and ffprobe), "tool_settings": str(CONFIG),
            "local_asr": {"faster_whisper": importlib.util.find_spec("faster_whisper") is not None,
                          "whisper_cli": local.get("whisper_cli") or shutil.which("whisper-cli")},
            "system_speech": "Windows SAPI" if os.name == "nt" else shutil.which("say") or shutil.which("espeak-ng") or shutil.which("espeak"),
            "models": modes}


class PreviewHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, directory, **kwargs):
        self.directory = directory
        super().__init__(*args, **kwargs)

    def respond(self, head):
        # Serve the selected build directory only. Block traversal, symlinks escaping
        # the build, dotfiles, directory listings and non-loopback Host headers.
        if self.headers.get("Host", "").split(":")[0].lower() not in ("127.0.0.1", "localhost"):
            return self.send_error(403)
        parts = unquote(urlsplit(self.path).path).replace("\\", "/").strip("/").split("/")
        if any(part.startswith(".") or ":" in part or "\0" in part for part in parts):
            return self.send_error(404)
        candidate = self.directory.joinpath(*parts).resolve()
        if candidate.is_dir():
            candidate = (candidate / "index.html").resolve()
        if not candidate.is_relative_to(self.directory) or not candidate.is_file():
            return self.send_error(404)
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(candidate.stat().st_size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if not head:
            with candidate.open("rb") as src:
                shutil.copyfileobj(src, self.wfile)

    def do_GET(self):
        self.respond(False)

    def do_HEAD(self):
        self.respond(True)

    def log_message(self, *args):
        pass


@tool("Open a built static website or web game on a loopback URL for visual review. Serve only a dedicated output directory containing index.html. Stays available while this MCP server is running.", fields({"directory": STRING}, ["directory"]))
def preview_site(directory):
    p = Path(directory).expanduser().resolve(strict=True)
    if not p.is_dir() or not (p/"index.html").is_file() or p in (Path.home(), Path(p.anchor)) or any((p/n).exists() for n in (".git", ".env", "node_modules", "package.json")):
        raise ValueError("Select a static output directory containing index.html, for example app/dist")
    for identifier, (folder, server) in previews.items():
        if folder == p:
            return {"preview": identifier, "url": f"http://127.0.0.1:{server.server_port}/"}
    if len(previews) >= 8:
        raise ValueError("Close an existing preview before opening another")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(PreviewHandler, directory=p))
    Thread(target=server.serve_forever, daemon=True).start()
    identifier = uuid.uuid4().hex
    previews[identifier] = (p, server)
    return {"preview": identifier, "url": f"http://127.0.0.1:{server.server_port}/"}


@tool("Stop a preview served by this runtime.", fields({"preview": STRING}, ["preview"]))
def stop_preview(preview):
    stored = previews.pop(preview, None)
    if stored:
        stored[1].shutdown()
        stored[1].server_close()
    return {"stopped": bool(stored)}


if __name__ == "__main__":
    try:
        serve("runtime")
    finally:
        for _, server in previews.values():
            server.shutdown()
            server.server_close()
