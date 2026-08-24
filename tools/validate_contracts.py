#!/usr/bin/env python3
"""校验 contracts/*.json：可解析、version 一致、所有 $ref 可解析。

G1 冻结闸门。当前只认同目录文件引用（如 roles.v1.json#/role_enum），
不拉 http(s) $schema。故意改掉被引用键时必须失败。

用法（仓库根）：
    python tools/validate_contracts.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Iterable, List, Tuple

DEFAULT_CONTRACTS_DIR = Path(__file__).resolve().parent.parent / "contracts"


def walk_refs(obj: Any) -> Iterable[str]:
    if isinstance(obj, dict):
        ref = obj.get("$ref")
        if isinstance(ref, str):
            yield ref
        for value in obj.values():
            yield from walk_refs(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from walk_refs(item)


def unescape_pointer_token(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def resolve_pointer(doc: Any, pointer: str) -> Any:
    if pointer in ("", "/"):
        return doc
    if not pointer.startswith("/"):
        raise KeyError(f"JSON pointer must start with /: {pointer!r}")
    current = doc
    for raw in pointer.lstrip("/").split("/"):
        token = unescape_pointer_token(raw)
        if isinstance(current, dict):
            if token not in current:
                raise KeyError(token)
            current = current[token]
        elif isinstance(current, list):
            current = current[int(token)]
        else:
            raise KeyError(token)
    return current


def load_contracts(root: Path) -> dict[str, Any]:
    files = sorted(root.glob("*.json"))
    if not files:
        raise SystemExit(f"no contracts found in {root}")
    docs: dict[str, Any] = {}
    versions: set[str] = set()
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"FAIL {path.name}: invalid JSON: {exc}") from exc
        version = data.get("version")
        if not version:
            raise SystemExit(f"FAIL {path.name}: missing version")
        versions.add(str(version))
        docs[path.name] = data
        print(f"OK {path.name} version={version}")
    if len(versions) != 1:
        raise SystemExit(f"FAIL version drift: {sorted(versions)}")
    print(f"all {len(docs)} contracts at {versions.pop()}")
    return docs


def check_refs(docs: dict[str, Any]) -> List[Tuple[str, str, str]]:
    failures: List[Tuple[str, str, str]] = []
    resolved = 0
    for source, data in docs.items():
        for ref in walk_refs(data):
            if ref.startswith(("http://", "https://")):
                failures.append((source, ref, "external $ref not allowed"))
                continue
            file_part, hash_sign, fragment = ref.partition("#")
            target_name = file_part or source
            if target_name not in docs:
                failures.append((source, ref, f"missing file {target_name}"))
                continue
            pointer = f"/{fragment}" if hash_sign and fragment and not fragment.startswith("/") else fragment
            try:
                resolve_pointer(docs[target_name], pointer)
            except (KeyError, ValueError, IndexError, TypeError) as exc:
                failures.append((source, ref, f"pointer not found: {exc}"))
                continue
            resolved += 1
            print(f"OK $ref {source} → {ref}")
    print(f"resolved {resolved} $ref")
    return failures


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_CONTRACTS_DIR
    docs = load_contracts(root)
    failures = check_refs(docs)
    if failures:
        for source, ref, reason in failures:
            print(f"FAIL {source}: $ref {ref!r} ({reason})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
