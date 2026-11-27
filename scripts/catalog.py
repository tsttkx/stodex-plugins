"""Build the Stodex catalog from declarative submissions without loading plugin code."""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IDENTIFIER = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")
VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def load_json(path, limit):
    require(path.is_file() and not path.is_symlink(), f"{path}: expected a regular file")
    require(path.stat().st_size <= limit, f"{path}: file exceeds {limit} bytes")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"{path}: duplicate JSON key {key}")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)


def native_entry(folder):
    prefix = folder.relative_to(ROOT).as_posix()
    require(folder.is_dir() and not folder.is_symlink(), f"{prefix}: expected a plugin directory")
    require(IDENTIFIER.fullmatch(folder.name) and len(folder.name) <= 64, f"{prefix}: invalid plugin identifier")
    obj = load_json(folder / "plugin.json", 300_000)
    require(isinstance(obj, dict) and obj.get("name") == folder.name, f"{prefix}: invalid manifest name")
    native = obj.get("format") == "stodex-plugin-v2"
    fields = {"format", "name", "displayName", "version", "description", "resources"}
    if native:
        require(folder.parent == ROOT / "plugins", f"{prefix}: executable bundles belong in the official directory")
        fields.update(("servers", "files"))
        assets = obj.get("files")
        servers = obj.get("servers")
        require(isinstance(assets, dict) and 0 < len(assets) <= 32, "declare the Python modules and checksums")
        require(isinstance(servers, dict) and 0 < len(servers) <= 8, "declare the local MCP servers")
        require(all(IDENTIFIER.fullmatch(name) and len(name) <= 24 and file in assets for name, file in servers.items()), "invalid server entrypoint")
        require(not (folder / "mcp").is_symlink() and (folder / "mcp").is_dir(), "missing MCP directory")
        for name, checksum in assets.items():
            require(re.fullmatch(r"mcp/[a-z][a-z0-9_]{0,63}\.py", name), "invalid module path")
            file = folder / name
            require(not file.is_symlink() and file.is_file() and file.stat().st_size <= 1_000_000, f"invalid module: {name}")
            require(hashlib.sha256(file.read_bytes()).hexdigest() == checksum, f"checksum mismatch: {name}")
        require(set(assets) == {f"mcp/{x.name}" for x in (folder / "mcp").iterdir()}, "undeclared MCP file")
    require(set(obj) == fields and (native or obj["format"] == "stodex-plugin-v1"), f"{prefix}: invalid format or fields")
    for item in folder.iterdir():
        if native and item.name == "mcp":
            continue
        require(item.is_file() and not item.is_symlink() and (item.name in ("plugin.json", "icon.png") or
                re.fullmatch(r"README(?:\.[\w-]+)?\.md|LICENSE(?:\.\w+)?", item.name, re.I)), f"{prefix}/{item.name}: unsupported file")
    icon = folder / "icon.png"
    if icon.exists():
        require(icon.stat().st_size <= 200_000 and icon.read_bytes()[:8] == bytes.fromhex("89504e470d0a1a0a"), "invalid icon")
    require(text(obj["displayName"]) and text(obj["description"]), f"{prefix}: provide a name and description")
    require(text(obj["version"]) and VERSION.fullmatch(obj["version"]), f"{prefix}: use a semantic version")
    rows = obj["resources"]
    require(isinstance(rows, list) and 0 < len(rows) <= 100, f"{prefix}: expected 1–100 resources")
    names = set()
    for row in rows:
        require(isinstance(row, dict) and set(row) == {"kind", "name", "description", "content"},
                f"{prefix}: invalid resource declaration")
        require(row["kind"] in ("skill", "prompt", "agent"), f"{prefix}: unsupported resource kind")
        name = row["name"]
        require(text(name) and len(name.encode("utf-16-le")) // 2 <= 64 and
                all(part and part.isalnum() for part in re.split("[-_]", name)),
                f"{prefix}: invalid resource name")
        key = (row["kind"], name.lower()) if native else name.lower()
        require(key not in names, f"{prefix}: duplicate resource {name}")
        names.add(key)
        require(text(row["description"]) and text(row["content"]), f"{prefix}: empty instructions for {name}")
    return {key: obj[key] for key in ("name", "displayName", "version", "description")} | {"source": "./" + prefix} | ({"icon": "./" + prefix + "/icon.png"} if icon.exists() else {})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "build"))
    args = parser.parse_args()
    entries = []
    for category in ("plugins", "community"):
        parent = ROOT / category
        require(not parent.is_symlink(), f"{category}: directory cannot be a symbolic link")
        if parent.exists():
            entries.extend(native_entry(item) for item in sorted(parent.iterdir()))
    require(len(entries) == len({x["name"] for x in entries}), "plugin IDs must be unique across both directories")
    index = {"name": "stodex-plugins", "owner": {"name": "tsttkx", "url": "https://github.com/tsttkx"},
             "description": "Stodex 官方和社区插件", "plugins": entries}
    if args.action == "build":
        (ROOT / "marketplace.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(entries)} Stodex plugins")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError) as error:
        sys.exit(str(error))
