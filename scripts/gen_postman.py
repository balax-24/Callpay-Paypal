"""Generate docs/callpay.postman_collection.json from the API's OpenAPI schema.

Run from services/api:  .venv/Scripts/python ../../scripts/gen_postman.py
"""

import json
import pathlib
import sys

sys.path.insert(0, ".")
from app.main import app  # noqa: E402

spec = app.openapi()
folders: dict[str, list] = {}


def example(schema: dict) -> dict:
    ref = schema.get("$ref")
    if ref:
        schema = spec["components"]["schemas"][ref.split("/")[-1]]
    out = {}
    for name, prop in schema.get("properties", {}).items():
        if "default" in prop:
            out[name] = prop["default"]
        elif prop.get("type") == "array":
            out[name] = []
        elif prop.get("type") == "integer":
            out[name] = 1
        else:
            out[name] = f"<{name}>"
    return out


for path, methods in sorted(spec["paths"].items()):
    folder = path.strip("/").split("/")[0] or "root"
    for method, op in methods.items():
        url_path = [p if not p.startswith("{") else ":" + p[1:-1] for p in path.strip("/").split("/")]
        req = {
            "method": method.upper(),
            "header": [{"key": "Content-Type", "value": "application/json"}],
            "url": {"raw": "{{baseUrl}}" + path.replace("{", ":").replace("}", ""), "host": ["{{baseUrl}}"], "path": url_path},
            "description": (op.get("description") or op.get("summary") or "").strip(),
        }
        body = op.get("requestBody", {}).get("content", {}).get("application/json")
        if body:
            req["body"] = {"mode": "raw", "raw": json.dumps(example(body["schema"]), indent=2)}
        folders.setdefault(folder, []).append({"name": f"{method.upper()} {path}", "request": req})

collection = {
    "info": {
        "name": "CallPay API",
        "description": "AI phone agent with PayPal checkout, payouts, refunds and disputes. Generated from OpenAPI.",
        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    },
    "variable": [{"key": "baseUrl", "value": "http://localhost:8090/api"}],
    "item": [{"name": k, "item": v} for k, v in folders.items()],
}
out = pathlib.Path(__file__).resolve().parents[1] / "docs" / "callpay.postman_collection.json"
out.write_text(json.dumps(collection, indent=2))
print(f"wrote {out} ({sum(len(v) for v in folders.values())} requests)")
