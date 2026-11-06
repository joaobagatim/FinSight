"""Focused refusal checks; no Docker, personal configuration or network used."""

import json

import demo
import pytest


def test_foreign_volume_is_refused(monkeypatch):
    def docker(*args):
        if args[:2] == ("ps", "-aq"):
            return ""
        if args[:2] == ("volume", "ls"):
            return demo.VOLUME
        return json.dumps([{"Labels": {"com.docker.compose.project": "finsight"}}])

    monkeypatch.setattr(demo, "docker", docker)
    with pytest.raises(RuntimeError, match="volume ownership"):
        demo.verify_resources()


def test_personal_port_is_refused(monkeypatch):
    container = {
        "Config": {
            "Image": demo.IMAGE,
            "Labels": {
                "com.docker.compose.project": demo.PROJECT,
                "com.docker.compose.service": "postgres",
            },
        },
        "Mounts": [{"Destination": "/var/lib/postgresql", "Name": demo.VOLUME}],
        "HostConfig": {"PortBindings": {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "5433"}]}},
        "State": {"Running": True},
    }

    def docker(*args):
        if args[0] == "ps":
            return "demo-id"
        if args[0] == "volume":
            return ""
        return json.dumps([container])

    monkeypatch.setattr(demo, "docker", docker)
    with pytest.raises(RuntimeError, match="container/port/mount"):
        demo.verify_resources(running=True)


def test_seed_keys_and_dates_survive_repetition(tmp_path):
    from demo_seed import seed_demo

    created = {}
    counts = {"accounts": [], "categories": [], "transactions": []}

    def request(_opener, path, data=None, headers=None):
        if path.endswith("/csrf"):
            return {"csrf_token": "synthetic"}
        resource = path.split("/")[-1].split("?")[0]
        if resource not in counts:
            return None
        if data is None:
            return {"items": counts[resource]}
        key = (
            (headers or {}).get("Idempotency-Key", resource + data["name"])
            if "name" in data
            else headers["Idempotency-Key"]
        )
        if key not in created:
            result = {"id": str(len(created)), **data}
            created[key] = result
            counts[resource].append(result)
        return created[key]

    credentials = {"DEMO_EMAIL": "demo@example.com", "DEMO_PASSWORD": "synthetic-only-value"}
    first = seed_demo(tmp_path, credentials, None, request, demo.save)
    original = (tmp_path / "seed.json").read_bytes()
    assert seed_demo(tmp_path, credentials, None, request, demo.save) == first
    assert (tmp_path / "seed.json").read_bytes() == original
    assert first == {"accounts": 2, "categories": 4, "transactions": 6}
