"""Bounded JSON provenance; diagnostic redaction is explicit and irreversible."""

import math
from urllib.parse import urlsplit, urlunsplit

from pydantic import JsonValue

MAX_PAYLOAD_BYTES = 1_048_576
MAX_NODES = 20_000
MAX_DEPTH = 16
MAX_STRING_LENGTH = 16_384
SECRET_KEYS = ("password", "passwd", "secret", "token", "authorization", "api_key", "apikey", "credential")
ENDPOINT_KEYS = frozenset({"pool", "endpoint", "url", "uri", "pool_url", "pool_address", "pool_endpoint", "api_url", "api_endpoint"})


def _secret_key(key: str) -> bool:
    name = key.casefold()
    return any(secret in name for secret in SECRET_KEYS) or name == "auth" or name.startswith("auth_") or name.endswith("_auth")


def safe_endpoint(value: str) -> str:
    explicit_scheme = "://" in value
    parsed = urlsplit(value if explicit_scheme else "//" + value)
    host = parsed.hostname
    if not host or any(char.isspace() or ord(char) < 32 for char in host):
        raise ValueError("endpoint has no host")
    authority = host if ":" not in host else f"[{host}]"
    if parsed.port is not None:
        authority += f":{parsed.port}"
    result = urlunsplit((parsed.scheme, authority, parsed.path, "", ""))
    return result if explicit_scheme else result.removeprefix("//")


def safe_payload(value: object) -> JsonValue:
    remaining = MAX_NODES

    def walk(item: object, depth: int, endpoint_field: bool = False) -> JsonValue:
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > MAX_DEPTH:
            raise ValueError("payload_structure_limit")
        if isinstance(item, dict):
            result: dict[str, JsonValue] = {}
            for key, child in item.items():
                name = str(key)
                if len(name) > MAX_STRING_LENGTH:
                    raise ValueError("payload_string_limit")
                if _secret_key(name):
                    walk(child, depth + 1)  # Validate limits even for values omitted from evidence.
                    result[name] = "[REDACTED]"
                else:
                    result[name] = walk(child, depth + 1, name.casefold() in ENDPOINT_KEYS)
            return result
        if isinstance(item, list):
            return [walk(v, depth + 1, endpoint_field) for v in item]
        if isinstance(item, str):
            if len(item) > MAX_STRING_LENGTH:
                raise ValueError("payload_string_limit")
            if endpoint_field:
                try:
                    return safe_endpoint(item)
                except ValueError:
                    return "[REDACTED_ENDPOINT]"
            return item
        if item is None or isinstance(item, (bool, int)):
            return item
        if isinstance(item, float):
            return item if math.isfinite(item) else {"non_finite_numeric": str(item)}
        raise ValueError("payload_non_json_type")

    return walk(value, 0)
