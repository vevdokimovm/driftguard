"""Поведение API: приём снимков, эталон, состояния хостов, события, журнал, токены."""

from conftest import make_snapshot


async def send(client, snapshot, headers=None):
    return await client.post("/api/snapshots", json=snapshot, headers=headers or {})


async def host_state(client, name="node-a") -> dict:
    return {h["name"]: h for h in (await client.get("/api/hosts")).json()}[name]


async def test_first_snapshot_becomes_baseline(client):
    ack = (await send(client, make_snapshot())).json()
    assert ack["state"] == "OK" and ack["stored"] is True
    host = await host_state(client)
    assert host["state"] == "OK" and host["baseline_accepted_by"] == "auto"


async def test_identical_snapshot_is_not_stored_again(client):
    await send(client, make_snapshot())
    ack = (await send(client, make_snapshot())).json()
    assert ack["stored"] is False
    host_id = ack["host_id"]
    assert len((await client.get(f"/api/hosts/{host_id}/snapshots")).json()) == 1


async def test_drift_detected_and_resolved(client):
    host_id = (await send(client, make_snapshot())).json()["host_id"]
    ack = (await send(client, make_snapshot(ports=["tcp/8080", "tcp/9999"]))).json()
    assert ack == {"host_id": host_id, "state": "DRIFT", "changes": 1, "stored": True}
    [change] = (await client.get(f"/api/hosts/{host_id}/drift")).json()
    assert change == {"section": "ports", "key": "tcp/9999", "kind": "added", "expected": None, "actual": "tcp/9999"}

    assert (await send(client, make_snapshot())).json()["state"] == "OK"
    kinds = [e["kind"] for e in (await client.get("/api/events")).json()]
    assert kinds == ["drift_resolved", "drift_detected", "baseline_accepted"]


async def test_accept_baseline_clears_drift(client):
    host_id = (await send(client, make_snapshot())).json()["host_id"]
    await send(client, make_snapshot(packages={"openssl": "3.0.16"}))
    assert (await host_state(client))["state"] == "DRIFT"
    accepted = await client.post(f"/api/hosts/{host_id}/baseline")
    assert accepted.status_code == 200
    assert accepted.json()["state"] == "OK" and accepted.json()["changes"] == 0
    assert (await client.get(f"/api/hosts/{host_id}/drift")).json() == []
    audit = [a["action"] for a in (await client.get("/api/audit")).json()]
    assert audit == ["baseline_accepted", "host_registered"]


async def test_without_auto_baseline_host_waits_for_operator(client):
    from app.core.config import settings

    settings.AUTO_BASELINE = False
    try:
        ack = (await send(client, make_snapshot())).json()
        assert ack["state"] == "NO_BASELINE"
        assert (await host_state(client))["state"] == "NO_BASELINE"
        await client.post(f"/api/hosts/{ack['host_id']}/baseline")
        assert (await host_state(client))["state"] == "OK"
    finally:
        settings.AUTO_BASELINE = True


async def test_host_without_fresh_snapshots_is_stale(client):
    from app.core.config import settings

    await send(client, make_snapshot())
    settings.STALE_AFTER_SECONDS = -1
    try:
        assert (await host_state(client))["state"] == "STALE"
    finally:
        settings.STALE_AFTER_SECONDS = 60


async def test_delete_host(client):
    host_id = (await send(client, make_snapshot())).json()["host_id"]
    await send(client, make_snapshot(ports=[]))
    assert (await client.delete(f"/api/hosts/{host_id}")).status_code == 204
    assert (await client.get("/api/hosts")).json() == []
    assert (await client.get("/api/events")).json() == []


async def test_unknown_host_is_404(client):
    assert (await client.get("/api/hosts/99/drift")).status_code == 404
    assert (await client.post("/api/hosts/99/baseline")).status_code == 404
    assert (await client.delete("/api/hosts/99")).status_code == 404
    assert (await client.get("/api/events?host_id=99")).status_code == 404


async def test_invalid_snapshot_is_422(client):
    assert (await send(client, make_snapshot(hostname="bad name!"))).status_code == 422
    assert (await send(client, make_snapshot(ports=["tcp/70000"]))).status_code == 422
    bad_file = make_snapshot(files={"/etc/x": {"sha256": "zz", "mode": "0644", "owner": "root:root"}})
    assert (await send(client, bad_file)).status_code == 422


async def test_tokens_are_separate_for_agents_and_client(client):
    from app.core.config import settings

    settings.API_TOKEN, settings.AGENT_TOKEN = "client-secret", "agent-secret"
    try:
        assert (await send(client, make_snapshot())).status_code == 401
        assert (await send(client, make_snapshot(), {"X-API-Token": "client-secret"})).status_code == 401
        assert (await send(client, make_snapshot(), {"X-Agent-Token": "agent-secret"})).status_code == 200
        assert (await client.get("/api/hosts", headers={"X-Agent-Token": "agent-secret"})).status_code == 401
        assert (await client.get("/api/hosts", headers={"X-API-Token": "client-secret"})).status_code == 200
        assert (await client.get("/api/health")).status_code == 200
    finally:
        settings.API_TOKEN = settings.AGENT_TOKEN = ""


async def test_limit_is_bounded(client):
    assert (await client.get("/api/audit?limit=100000")).status_code == 422
