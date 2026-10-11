"""Small helpers for tests that walk the API's OpenAPI document."""


def resolve(schema, spec):
    if "$ref" in schema:
        node = spec
        for part in schema["$ref"].lstrip("#/").split("/"):
            node = node[part]
        return resolve(node, spec)
    return schema


def sample(schema, spec, depth=0):
    """A plausible valid value for a schema (good enough to get past validation)."""
    schema = resolve(schema, spec)
    for key in ("anyOf", "oneOf"):
        if key in schema:
            options = [o for o in schema[key] if o.get("type") != "null"]
            return sample(options[0], spec, depth) if options else None
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object":
        return {
            k: sample(v, spec, depth + 1)
            for k, v in schema.get("properties", {}).items()
            if k in schema.get("required", [])
        }
    if kind == "array":
        return [sample(schema.get("items", {}), spec, depth + 1)] if depth < 4 else []
    if kind == "integer":
        return 1
    if kind == "number":
        return 1.5
    if kind == "boolean":
        return True
    if schema.get("format") == "date":
        return "2026-10-05"
    return "x"
