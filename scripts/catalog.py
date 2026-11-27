"""Build the Stodex catalog from declarative submissions without loading plugin code."""

import argparse
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
    for item in folder.iterdir():
        require(item.is_file() and not item.is_symlink() and
                (item.name == "plugin.json" or re.fullmatch(r"README(?:\.[\w-]+)?\.md|LICENSE(?:\.\w+)?", item.name, re.I)),
                f"{prefix}/{item.name}: unsupported package file")
    obj = load_json(folder / "plugin.json", 300_000)
    require(isinstance(obj, dict) and set(obj) == {"format", "name", "displayName", "version", "description", "resources"},
            f"{prefix}: unexpected or missing manifest fields")
    require(obj["format"] == "stodex-plugin-v1" and obj["name"] == folder.name, f"{prefix}: invalid format or name")
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
        require(name.lower() not in names, f"{prefix}: duplicate resource {name}")
        names.add(name.lower())
        require(text(row["description"]) and text(row["content"]), f"{prefix}: empty instructions for {name}")
    return {key: obj[key] for key in ("name", "displayName", "version", "description")} | {"source": "./" + prefix}


def check_reviews():
    obj = load_json(ROOT / "external.json", 2_000_000)
    require(isinstance(obj, dict) and set(obj) == {"format", "plugins"} and type(obj["format"]) is int and
            obj["format"] == 1 and isinstance(obj["plugins"], list), "external.json: invalid format")
    seen = set()
    for row in obj["plugins"]:
        fields = {"market", "repository", "directory", "name", "revision", "description", "chinese", "requirements", "verified"}
        require(isinstance(row, dict) and fields <= row.keys() <= fields | {"version"}, "external.json: invalid fields")
        require(row["market"] in ("zcode", "claude", "openai", "community"), "external.json: unknown market")
        require(text(row["name"]) and re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}", row["name"]), "invalid external name")
        require(text(row["repository"]) and re.fullmatch(r"[\w.-]+/[\w.-]+", row["repository"], re.ASCII) and
                not {".", ".."}.intersection(row["repository"].split("/")), "invalid GitHub repository")
        directory = row["directory"]
        require(isinstance(directory, str) and (not directory or all(
            part not in ("", ".", "..") and re.fullmatch(r"[\w.-]+", part) for part in directory.split("/"))),
            "invalid upstream directory")
        require(text(row["revision"]) and re.fullmatch("[a-f0-9]{40}", row["revision"]), "use an immutable Git commit")
        require(text(row["description"]) and text(row["chinese"]) and ("version" not in row or text(row["version"])),
                "provide plugin descriptions and a nonempty version when supplied")
        require(isinstance(row["requirements"], list) and all(text(x) for x in row["requirements"]), "invalid prerequisites")
        proof = row["verified"]
        require(isinstance(proof, dict) and set(proof) == {"client", "steps", "result"} and text(proof["client"]) and
                isinstance(proof["steps"], list) and len(proof["steps"]) >= 2 and all(text(x) for x in proof["steps"]) and
                text(proof["result"]), "record the Stodex client, concrete test steps and result")
        key = row["market"], row["name"]
        require(key not in seen, f"duplicate external listing: {key}")
        seen.add(key)
    return len(seen)


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
    reviews = check_reviews()
    index = {"name": "stodex-plugins", "owner": {"name": "tsttkx", "url": "https://github.com/tsttkx"},
             "description": "Stodex 官方和社区插件", "plugins": entries}
    if args.action == "build":
        (ROOT / "marketplace.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(entries)} Stodex plugins, {reviews} reviewed external plugins")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError) as error:
        sys.exit(str(error))
