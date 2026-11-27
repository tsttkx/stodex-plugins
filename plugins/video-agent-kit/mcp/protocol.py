"""Minimal newline-delimited MCP stdio transport for this local plugin."""
import base64
import json
import math
import sys
import traceback

TOOLS = {}
STRING = {"type": "string", "minLength": 1}
NUMBER = {"type": "number"}
POSITIVE = {"type": "number", "exclusiveMinimum": 0}
TIME = {"type": "number", "minimum": 0}
INTEGER = {"type": "integer"}
BOOL = {"type": "boolean"}


def listed(items, minimum=1, maximum=100):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}


def fields(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


def choice(*values):
    return {"type": "string", "enum": list(values)}


def tool(description, schema):
    def register(fn):
        TOOLS[fn.__name__] = (fn, {"name": fn.__name__, "description": description, "inputSchema": schema})
        return fn
    return register


def validate(value, schema, key="arguments"):
    kind = schema["type"]
    if kind == "object" and isinstance(value, dict):
        props = schema["properties"]
        if set(schema["required"]) - value.keys() or value.keys() - props.keys():
            raise ValueError(f"{key}: expected {list(props)}, required {schema['required']}")
        for name, item in value.items():
            validate(item, props[name], key + "." + name)
        return
    if kind == "array" and isinstance(value, list) and schema["minItems"] <= len(value) <= schema["maxItems"]:
        for item in value:
            validate(item, schema["items"], key + "[]")
        return
    if kind == "string" and isinstance(value, str) and value.strip() and "\0" not in value and (
            "enum" not in schema or value in schema["enum"]):
        return
    if kind == "boolean" and type(value) is bool:
        return
    if kind in ("integer", "number") and type(value) in (int, float) and math.isfinite(value):
        if (kind != "integer" or type(value) is int) and value >= schema.get("minimum", -math.inf) and value <= schema.get("maximum", math.inf) and value > schema.get("exclusiveMinimum", -math.inf):
            return
    raise ValueError(f"Invalid {key}: expected {kind}")


def picture(path):
    return {"type": "image", "mimeType": "image/jpeg", "data": base64.b64encode(path.read_bytes()).decode("ascii")}


def result(value):
    return {"type": "text", "text": json.dumps(value, ensure_ascii=False, allow_nan=False)}


def serve(server):
    # The Windows ACP can be GBK or cp1252. MCP stdio is always UTF-8.
    for line in sys.stdin.buffer:
        request_id = None
        try:
            req = json.loads(line)
            if not isinstance(req, dict) or "id" not in req:
                continue
            request_id = req["id"]
            event = req.get("method")
            params = req.get("params", {})
            if event == "initialize":
                versions = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
                version = params.get("protocolVersion")
                data = {"protocolVersion": version if version in versions else versions[0], "capabilities": {"tools": {}},
                        "serverInfo": {"name": server, "version": "1.0.0"}}
            elif event == "ping":
                data = {}
            elif event == "tools/list":
                data = {"tools": [info for _, info in TOOLS.values()]}
            elif event == "tools/call":
                try:
                    fn, info = TOOLS[params["name"]]
                    args = params.get("arguments", {})
                    validate(args, info["inputSchema"])
                    value = fn(**args)
                    data = {"content": value if isinstance(value, list) else [result(value)]}
                except Exception as exc:
                    print(type(exc).__name__, str(exc)[:2000], file=sys.stderr, flush=True)
                    data = {"isError": True, "content": [result({"error": str(exc)[:2600]})]}
            else:
                raise KeyError(event)
            response = {"jsonrpc": "2.0", "id": request_id, "result": data}
        except Exception as exc:
            response = {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601 if isinstance(exc, KeyError) else -32600, "message": str(exc)}}
        sys.stdout.buffer.write(json.dumps(response, ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n")
        sys.stdout.buffer.flush()
