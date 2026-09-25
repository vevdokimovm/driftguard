"""Расчёт дрейфа без БД: какие расхождения находятся и как считается отпечаток."""

from app.services.drift import compare, digest, summary

from conftest import make_snapshot


def test_identical_snapshots_have_no_drift():
    assert compare(make_snapshot(), make_snapshot()) == []


def test_file_content_mode_and_owner_are_separate_changes():
    actual = make_snapshot()
    actual["files"]["/srv/app/run.sh"] = {"sha256": "c" * 64, "mode": "0777", "owner": "app:app"}
    keys = [(c.key, c.kind) for c in compare(make_snapshot(), actual)]
    assert keys == [("/srv/app/run.sh [sha256]", "changed"), ("/srv/app/run.sh [mode]", "changed"),
                    ("/srv/app/run.sh [owner]", "changed")]


def test_added_and_removed_files():
    actual = make_snapshot()
    del actual["files"]["/srv/app/app.conf"]
    actual["files"]["/etc/cron.d/backdoor"] = {"sha256": "d" * 64, "mode": "0644", "owner": "root:root"}
    kinds = {c.key: c.kind for c in compare(make_snapshot(), actual)}
    assert kinds == {"/srv/app/app.conf": "removed", "/etc/cron.d/backdoor": "added"}


def test_package_version_added_and_removed():
    actual = make_snapshot(packages={"openssl": "3.0.16", "netcat": "1.10"})
    changes = {c.key: (c.kind, c.expected, c.actual) for c in compare(make_snapshot(), actual)}
    assert changes == {"demo-tool": ("removed", "1.0", None), "netcat": ("added", None, "1.10"),
                       "openssl": ("changed", "3.0.15", "3.0.16")}


def test_ports():
    actual = make_snapshot(ports=["tcp/22", "tcp/9999"])
    changes = [(c.key, c.kind) for c in compare(make_snapshot(), actual)]
    assert changes == [("tcp/22", "added"), ("tcp/8080", "removed"), ("tcp/9999", "added")]


def test_digest_ignores_key_and_port_order():
    a = make_snapshot(ports=["tcp/22", "tcp/8080"])
    b = make_snapshot(ports=["tcp/8080", "tcp/22", "tcp/22"])
    b["packages"] = dict(reversed(list(b["packages"].items())))
    assert digest(a) == digest(b)
    assert digest(a) != digest(make_snapshot())


def test_summary_counts_by_section():
    actual = make_snapshot(ports=[], packages={})
    assert summary(compare(make_snapshot(), actual)) == "packages: 2, ports: 1"
    assert summary([]) == "нет расхождений"
