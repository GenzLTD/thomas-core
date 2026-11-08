"""钉版自洽：contracts/gfcc 的 SOURCE.json 与 14 个 JSON 互相一致。具体提交号随 gfcc tag 同步前进。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIN = ROOT / "contracts" / "gfcc"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_source_files_exist_and_versions_match():
    source = _load(PIN / "SOURCE.json")
    assert len(source["commit"]) == 40
    assert source["families"]["l0"]["version"]
    assert source["families"]["signal"]["version"]
    seen = []
    for family in source["families"].values():
        for name in family["files"]:
            path = PIN / name
            assert path.is_file(), name
            body = _load(path)
            assert body["version"] == family["version"], name
            seen.append(name)
    assert len(seen) == 14
    assert len(set(seen)) == 14


def test_invitation_port_and_signal_entry():
    source = _load(PIN / "SOURCE.json")
    invitation = _load(PIN / "invitation.v1.json")
    signal = _load(PIN / "signal.envelope.v1.json")
    assert invitation["port"] == "invitation"
    assert invitation["version"] == source["families"]["l0"]["version"]
    assert signal["entry"] == "POST /v1/signal-ingest"
    assert signal["version"] == source["families"]["signal"]["version"]


def test_signal_refs_resolve():
    signal = _load(PIN / "signal.envelope.v1.json")
    refs = []

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node and isinstance(node["$ref"], str) and not node["$ref"].startswith("#"):
                refs.append(node["$ref"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(signal)
    assert refs, "signal envelope should point at payload files"
    for ref in refs:
        path = (PIN / ref).resolve()
        assert path.is_file(), ref
        assert PIN.resolve() in path.parents
        _load(path)
