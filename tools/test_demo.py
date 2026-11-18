"""Focused refusal checks; no Docker, personal configuration or network used."""

import json
from uuid import uuid4

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


@pytest.fixture
def seed_api(tmp_path):
    created = {}
    counts = {
        name: [] for name in ("accounts", "categories", "transactions", "goals", "allocations")
    }
    state = {
        "counts": counts,
        "lose_response": False,
        "contexts": 0,
        "allocation_posts": 0,
        "day": "2026-11-16",
    }

    def request(_opener, path, data=None, headers=None, *, with_etag=False):
        if path.endswith("/csrf"):
            return {"csrf_token": "synthetic"}
        resource = path.split("/")[-1].split("?")[0]
        if resource == "allocation-context":
            assert with_etag
            state["contexts"] += 1
            return {"funding": {"as_of": state["day"]}}, '"' + "a" * 64 + '"'
        if resource not in counts:
            return None
        if data is None:
            return {"items": counts[resource]}
        key = (
            (headers or {}).get("Idempotency-Key", resource + data["name"])
            if "name" in data
            else headers["Idempotency-Key"]
        )
        if resource in {"goals", "allocations"}:
            plan = json.loads((tmp_path / "seed.json").read_text())["goal_seed"]
            intent = plan if resource == "goals" else plan["allocation"]
            assert intent["key"] == key and intent["body"] == data
            if resource == "allocations":
                state["allocation_posts"] += 1
                assert headers["If-Match"] == intent["etag"]
        if key not in created:
            result = {"id": str(len(created)), **data}
            created[key] = result
            counts[resource].append(result)
            if resource == "allocations" and state["lose_response"]:
                state["lose_response"] = False
                raise RuntimeError("Synthetic lost allocation response")
        return created[key]

    return state, request


def test_seed_keys_and_dates_survive_repetition(tmp_path, seed_api):
    from demo_seed import seed_demo

    state, request = seed_api
    legacy = {
        "anchor": "2026-11-06",
        "opening": "2026-10-07",
        "keys": [str(uuid4()) for _ in range(8)],
        "categories": {},
    }
    demo.save(tmp_path / "seed.json", legacy)
    credentials = {"DEMO_EMAIL": "demo@example.com", "DEMO_PASSWORD": "synthetic-only-value"}
    first = seed_demo(tmp_path, credentials, None, request, demo.save)
    original = (tmp_path / "seed.json").read_bytes()
    plan = json.loads(original)
    assert all(plan[key] == legacy[key] for key in ("anchor", "opening", "keys"))
    csv = tmp_path / "import-example.csv"
    assert csv.read_text(encoding="utf-8").splitlines() == [
        "Date;Description;Amount",
        "2026-11-04;Entrada CSV fictícia;250.00",
        "2026-11-05;Saída CSV fictícia;-50.00",
    ]
    csv.write_text("User edited synthetic CSV", encoding="utf-8")
    state["day"] = "2026-11-17"
    assert seed_demo(tmp_path, credentials, None, request, demo.save) == first
    assert (tmp_path / "seed.json").read_bytes() == original
    assert csv.read_text(encoding="utf-8") == "User edited synthetic CSV"
    assert state["contexts"] == 1 and state["allocation_posts"] == 1
    assert first == {
        "accounts": 2,
        "categories": 4,
        "transactions": 6,
        "goals": 1,
        "allocations": 1,
    }


def test_lost_reservation_response_reuses_exact_intent_on_later_day(tmp_path, seed_api):
    from demo_seed import seed_demo

    state, request = seed_api
    state["lose_response"] = True
    credentials = {"DEMO_EMAIL": "demo@example.com", "DEMO_PASSWORD": "synthetic-only-value"}
    with pytest.raises(RuntimeError, match="lost allocation response"):
        seed_demo(tmp_path, credentials, None, request, demo.save)
    intent = json.loads((tmp_path / "seed.json").read_text())["goal_seed"]["allocation"]
    assert "id" not in intent and len(state["counts"]["allocations"]) == 1
    state["day"] = "2026-11-17"
    result = seed_demo(tmp_path, credentials, None, request, demo.save)
    saved = json.loads((tmp_path / "seed.json").read_text())["goal_seed"]["allocation"]
    assert {k: v for k, v in saved.items() if k != "id"} == intent
    assert result["allocations"] == 1 and state["contexts"] == 1


def test_seed_lock_refuses_concurrent_command_and_releases_after_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "LOCAL", tmp_path)
    lock = tmp_path / "seed.lock"
    lock.write_text("", encoding="utf-8")

    def verify(**_kwargs):
        assert lock.exists()
        raise RuntimeError("Synthetic resource failure before API")

    monkeypatch.setattr(demo, "verify_resources", verify)
    with pytest.raises(FileExistsError):
        demo.seed()
    assert lock.exists()  # Another command's lock is never removed.
    lock.unlink()
    with pytest.raises(RuntimeError, match="Synthetic resource failure"):
        demo.seed()
    assert not lock.exists()
