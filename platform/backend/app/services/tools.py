from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

from ..models import ToolConfig
from ..security import decrypt_secret


PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
BLOCKED_HEADERS = {"host", "content-length", "connection", "transfer-encoding"}


def _render(value: Any, arguments: dict[str, Any]) -> Any:
    if isinstance(value, str):
        matches = list(PLACEHOLDER.finditer(value))
        if len(matches) == 1 and matches[0].span() == (0, len(value)):
            return arguments.get(matches[0].group(1), "")
        return PLACEHOLDER.sub(lambda item: str(arguments.get(item.group(1), "")), value)
    if isinstance(value, list):
        return [_render(item, arguments) for item in value]
    if isinstance(value, dict):
        return {key: _render(item, arguments) for key, item in value.items()}
    return value


def validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    missing = [name for name in required if arguments.get(name) in (None, "")]
    if missing:
        raise ValueError(f"缺少必填参数：{', '.join(missing)}")
    unknown = set(arguments) - set(properties)
    if unknown and properties:
        raise ValueError(f"包含未定义参数：{', '.join(sorted(unknown))}")
    type_map = {"string": str, "number": (int, float), "integer": int, "boolean": bool, "array": list, "object": dict}
    for name, value in arguments.items():
        expected = properties.get(name, {}).get("type")
        python_type = type_map.get(expected)
        if python_type and (isinstance(value, bool) and expected in {"number", "integer"} or not isinstance(value, python_type)):
            raise ValueError(f"参数 {name} 必须是 {expected}")


async def _resolved_addresses(hostname: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        return [ipaddress.ip_address(hostname)]
    except ValueError:
        records = await asyncio.to_thread(socket.getaddrinfo, hostname, None, type=socket.SOCK_STREAM)
        return list({ipaddress.ip_address(record[4][0]) for record in records})


async def validate_target(url: str, *, allow_private_network: bool) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("工具地址必须是有效的 HTTP/HTTPS URL")
    if parsed.username or parsed.password:
        raise ValueError("工具地址不能在 URL 中携带账号密码")
    addresses = await _resolved_addresses(parsed.hostname)
    if not allow_private_network and any(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        for address in addresses
    ):
        raise ValueError("目标解析到内网或保留地址；如确需访问企业内网，请显式开启内网访问")


def _extract_path(payload: Any, path: str) -> Any:
    current = payload
    for part in path.split(".") if path else []:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


async def execute_http_tool(
    tool: ToolConfig,
    arguments: dict[str, Any],
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    if tool.kind != "http":
        raise ValueError("当前执行器只支持 HTTP 工具")
    config = tool.config or {}
    validate_arguments(config.get("parameters", {}), arguments)
    url = str(_render(config.get("url", ""), arguments))
    await validate_target(url, allow_private_network=bool(config.get("allow_private_network", False)))
    headers = {
        str(key): str(_render(value, arguments))
        for key, value in config.get("headers", {}).items()
        if str(key).lower() not in BLOCKED_HEADERS
    }
    secret = decrypt_secret(tool.secret_encrypted)
    auth_type = config.get("auth_type", "none")
    if secret and auth_type == "bearer":
        headers["Authorization"] = f"Bearer {secret}"
    elif secret and auth_type == "api_key":
        headers[str(config.get("auth_header") or "X-API-Key")] = secret
    method = str(config.get("method", "GET")).upper()
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        raise ValueError("不支持的 HTTP 方法")
    query = _render(config.get("query", {}), arguments)
    body = _render(config.get("body"), arguments)
    timeout = min(max(float(config.get("timeout_seconds", 15)), 1), 60)
    owns_client = client is None
    active_client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)
    try:
        response = await active_client.request(method, url, headers=headers, params=query or None, json=body)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        payload: Any = response.json() if "json" in content_type else response.text
        selected = _extract_path(payload, str(config.get("response_path", "")))
        rendered = selected if config.get("response_path") else payload
        serialized = json.dumps(rendered, ensure_ascii=False, default=str) if not isinstance(rendered, str) else rendered
        if len(serialized) > 100_000:
            serialized = serialized[:100_000] + "…"
        return {"status_code": response.status_code, "data": rendered, "content": serialized}
    finally:
        if owns_client:
            await active_client.aclose()
