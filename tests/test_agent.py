"""Агент: сбор файлов, разбор таблицы портов и отправка снимка на сервер."""

import asyncio
import hashlib
import threading

from drift_agent import Collector, Sender, parse_proc_net

PROC_NET_TCP = """\
  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 00000000:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1 1
   1: 0100007F:270F 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 2 1
   2: 0B00007F:9377 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 4 1
   3: 0100007F:1F90 0100007F:D2A4 01 00000000:00000000 00:00000000 00000000     0        0 3 1
"""


def test_files_hash_mode_and_directory_walk(tmp_path):
    conf = tmp_path / "app" / "app.conf"
    conf.parent.mkdir()
    conf.write_text("max_connections = 100\n")
    conf.chmod(0o640)
    files = Collector([str(tmp_path / "app"), str(tmp_path / "missing")]).files()
    assert list(files) == [str(conf)]
    assert files[str(conf)]["sha256"] == hashlib.sha256(b"max_connections = 100\n").hexdigest()
    assert files[str(conf)]["mode"] == "0640"


def test_only_listening_sockets_are_ports():
    assert parse_proc_net(PROC_NET_TCP) == {8080, 9999}


def test_ports_read_from_proc_directory(tmp_path):
    (tmp_path / "tcp").write_text(PROC_NET_TCP)
    assert Collector([], proc_net=str(tmp_path)).ports() == ["tcp/8080", "tcp/9999"]


async def test_agent_snapshot_is_accepted_by_server(app_env, tmp_path):
    """Агент и сервер договариваются о формате: настоящий снимок проходит валидацию API."""
    import uvicorn

    app, _ = app_env
    (tmp_path / "app.conf").write_text("x = 1\n")
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="off")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    while not server.started:
        await asyncio.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        snapshot = Collector([str(tmp_path)]).snapshot("test-host")
        ack = await asyncio.to_thread(Sender(f"http://127.0.0.1:{port}").send, snapshot)
        assert ack["state"] == "OK" and ack["stored"] is True
    finally:
        server.should_exit = True
        thread.join(timeout=5)
