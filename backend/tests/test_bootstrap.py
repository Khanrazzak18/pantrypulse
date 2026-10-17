"""The deploy-time bootstrap: migrate on every start; seed, backtest, forecast and allocate once.

Each data step runs only when its own data is missing, so a run that died halfway is finished by the
next one, and a database that already has data is left alone. One runner at a time (a Postgres
advisory lock), so two tasks starting together cannot seed twice.
"""

import threading
import time

import pytest
from sqlalchemy import text

from scripts import bootstrap as b


@pytest.fixture
def world(monkeypatch):
    """Fake steps and fake 'is the data there' probes, so no real data is generated."""
    state = {"users": False, "backtest": False, "forward": False}
    calls: list[str] = []

    def step(name, flag):
        def run():
            calls.append(name)
            time.sleep(0.05)
            state[flag] = True

        return run

    monkeypatch.setattr(b, "has_users", lambda engine: state["users"])
    monkeypatch.setattr(
        b, "has_run", lambda engine, kind: state["backtest" if kind == "backtest" else "forward"]
    )
    steps = b.Steps(
        seed=step("seed", "users"),
        backtest=step("backtest", "backtest"),
        refresh=step("refresh", "forward"),
    )
    return state, calls, steps


def test_an_empty_database_is_seeded_then_backtested_then_forecast_and_allocated_in_order(
    engine, world
):
    state, calls, steps = world
    done = b.bootstrap(engine, steps, migrate=lambda: calls.append("migrate"))
    assert calls == ["migrate", "seed", "backtest", "refresh"]
    assert done == {"seed": True, "backtest": True, "refresh": True}


def test_a_database_that_already_has_everything_is_left_alone_but_still_migrated(engine, world):
    state, calls, steps = world
    state.update(users=True, backtest=True, forward=True)
    done = b.bootstrap(engine, steps, migrate=lambda: calls.append("migrate"))
    assert calls == ["migrate"]
    assert done == {"seed": False, "backtest": False, "refresh": False}


def test_running_it_twice_does_the_data_work_once(engine, world):
    state, calls, steps = world
    b.bootstrap(engine, steps, migrate=lambda: None)
    b.bootstrap(engine, steps, migrate=lambda: None)
    assert calls == ["seed", "backtest", "refresh"]


def test_a_run_that_died_after_seeding_is_finished_by_the_next_one(engine, world):
    state, calls, steps = world
    state["users"] = True  # the seed finished; the backtest never ran
    b.bootstrap(engine, steps, migrate=lambda: None)
    assert calls == ["backtest", "refresh"]


def test_two_tasks_starting_together_seed_exactly_once(engine, world):
    state, calls, steps = world
    threads = [
        threading.Thread(target=b.bootstrap, args=(engine, steps), kwargs={"migrate": lambda: None})
        for _ in range(2)
    ]
    [t.start() for t in threads]
    [t.join(timeout=20) for t in threads]
    assert calls == ["seed", "backtest", "refresh"]


def test_a_failing_step_stops_the_run_releases_the_lock_and_lets_a_retry_continue(engine, world):
    state, calls, steps = world

    def broken():
        calls.append("backtest-failed")
        raise RuntimeError("out of memory")

    failing = b.Steps(seed=steps.seed, backtest=broken, refresh=steps.refresh)
    with pytest.raises(RuntimeError, match="out of memory"):
        b.bootstrap(engine, failing, migrate=lambda: None)
    assert calls == ["seed", "backtest-failed"]  # refresh did not run after the failure
    b.bootstrap(engine, steps, migrate=lambda: None)  # the lock is free again
    assert calls[-2:] == ["backtest", "refresh"]


def test_migrations_wait_for_the_lock_so_only_one_task_migrates_at_a_time(engine, settings):
    holder = engine.connect()
    holder.execute(text("SELECT pg_advisory_lock(:k)"), {"k": b.LOCK_KEY})
    finished = threading.Event()
    thread = threading.Thread(
        target=lambda: (b.run_migrations(settings.test_database_url), finished.set())
    )
    thread.start()
    assert not finished.wait(0.7), "migrations ran while another task held the lock"
    holder.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": b.LOCK_KEY})
    holder.close()
    assert finished.wait(30)
    thread.join()


def test_migrating_a_database_that_is_already_current_changes_nothing(engine, settings):
    before = _tables(engine)
    b.run_migrations(settings.test_database_url)
    assert _tables(engine) == before


def _tables(engine):
    with engine.connect() as conn:
        return sorted(
            r[0]
            for r in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))
        )


def test_the_real_probes_see_users_and_runs(engine, people):
    assert b.has_users(engine)
    assert not b.has_run(engine, "backtest")


def test_an_empty_users_table_means_the_database_needs_seeding(engine):
    with engine.begin() as conn:
        n = conn.execute(text("SELECT count(*) FROM users")).scalar()
    if n == 0:
        assert not b.has_users(engine)


def test_the_command_line_accepts_only_migrate_or_all(capsys):
    assert b.main(["nonsense"]) == 2
    assert "migrate" in capsys.readouterr().err


def test_the_service_start_command_only_migrates_and_never_seeds(monkeypatch):
    ran = []
    monkeypatch.setattr(b, "run_migrations", lambda url: ran.append("migrate"))
    monkeypatch.setattr(b, "bootstrap", lambda *a, **k: ran.append("BOOTSTRAP"))
    assert b.main(["migrate"]) == 0
    assert ran == ["migrate"]
