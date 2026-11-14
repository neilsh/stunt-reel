"""``init`` and ``mise run seed`` print one line about seeding target/, and never fail on it."""

from __future__ import annotations

import contextlib
import errno
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from stunt_reel import dataroot
from stunt_reel.dataroot import cache_root
from stunt_reel.target_seed import SeedOutcome

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import worktree_init  # noqa: E402
from worktree_init import Line  # noqa: E402


def _text(lines: list[Line]) -> str:
    """*lines* as ``init`` prints them."""
    return "\n".join(map(str, lines))


def test_seed_line_formats_each_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worktree_init, "_rustc_vv", lambda: "rustc 1.99.1\n")
    monkeypatch.setattr(worktree_init, "_worktrees", lambda _repo: [])
    for outcome, line in [
        (SeedOutcome("seeded", r"from E:\a"), r"  + target/ seeded from E:\a"),
        (
            SeedOutcome("skipped", "volume does not clone blocks"),
            "  - target/ not seeded: volume does not clone blocks",
        ),
        (SeedOutcome("failed", "robocopy exit 8"), "  ! seed: robocopy exit 8"),
    ]:
        monkeypatch.setattr(worktree_init, "seed", lambda *_args, o=outcome, **_kwargs: o)
        assert _text(worktree_init._seed_target()) == line


def test_seed_line_without_rustc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worktree_init, "_rustc_vv", lambda: None)
    assert _text(worktree_init._seed_target()) == "  - target/ not seeded: rustc not on PATH"


def test_seed_line_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_repo: Path) -> list[object]:
        raise RuntimeError("git missing")

    monkeypatch.setattr(worktree_init, "_worktrees", boom)
    monkeypatch.setattr(worktree_init, "_rustc_vv", lambda: "rustc 1.99.1\n")
    assert _text(worktree_init._seed_target()) == "  ! seed: RuntimeError: git missing"


def test_seed_command_is_wired(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(worktree_init, "_seed_target", lambda: [Line("-", "target/ not seeded: x")])
    assert worktree_init.main(["seed"]) == 0
    assert "not seeded: x" in capsys.readouterr().out


def test_seed_uses_the_cargo_home_mise_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Python must judge donors by the very path mise hands cargo, not a second derivation."""
    seen: list[Path] = []

    def fake_seed(*_args: object, cargo_home: Path, **_kwargs: object) -> SeedOutcome:
        seen.append(cargo_home)
        return SeedOutcome("skipped", "x")

    monkeypatch.setattr(worktree_init, "_rustc_vv", lambda: "rustc 1.99.1\n")
    monkeypatch.setattr(worktree_init, "_worktrees", lambda _repo: [])
    monkeypatch.setattr(worktree_init, "seed", fake_seed)
    monkeypatch.setenv("STUNT_CARGO_HOME", str(tmp_path / "home"))
    worktree_init._seed_target()
    assert seen == [tmp_path / "home"]


def test_seed_command_fails_when_the_seed_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """init carries on after a failed seed; ``mise run seed`` on its own reports it by status."""
    monkeypatch.setattr(worktree_init, "_rustc_vv", lambda: "rustc 1.99.1\n")
    monkeypatch.setattr(worktree_init, "_worktrees", lambda _repo: [])
    for outcome, status in [
        (SeedOutcome("failed", "robocopy exit 8"), 1),
        (SeedOutcome("skipped", "volume does not clone blocks"), 0),
        (SeedOutcome("seeded", "from E:/a"), 0),
    ]:
        monkeypatch.setattr(worktree_init, "seed", lambda *_args, o=outcome, **_kwargs: o)
        assert worktree_init.main(["seed"]) == status, outcome
    assert "! seed: robocopy exit 8" in capsys.readouterr().out


def test_seed_warns_when_the_cargo_home_is_not_the_shared_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """mise's fallback names the cache through this checkout's link: same files, other path."""
    monkeypatch.setattr(worktree_init, "_rustc_vv", lambda: None)
    shared = cache_root() / "cargo"
    monkeypatch.setenv("STUNT_CARGO_HOME", str(shared).replace("\\", "/"))
    assert _text(worktree_init._seed_target()) == "  - target/ not seeded: rustc not on PATH"
    monkeypatch.setenv("STUNT_CARGO_HOME", str(tmp_path / ".cache" / "cargo"))
    lines = _text(worktree_init._seed_target()).splitlines()
    assert lines[1] == (
        f"  ! CARGO_HOME {tmp_path / '.cache' / 'cargo'} is not {shared}: "
        "every dependency rebuilds here"
    )


def test_concurrent_ensures_seed_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The gate starts four cargo lanes at once; only the first seeds, the rest find it built."""
    monkeypatch.setattr(worktree_init, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(worktree_init, "ensure_hooks_path", lambda _repo: [])
    monkeypatch.setattr(worktree_init, "_rustc_vv", lambda: "rustc 1.99.1\n")
    monkeypatch.setattr(worktree_init, "_worktrees", lambda _repo: [])
    calls: list[Path] = []

    def slow_seed(checkout: Path, **_kwargs: object) -> SeedOutcome:
        calls.append(checkout)
        time.sleep(0.2)
        (checkout / "target" / "debug").mkdir(parents=True)
        return SeedOutcome("seeded", "from elsewhere")

    monkeypatch.setattr(worktree_init, "seed", slow_seed)
    threads = [threading.Thread(target=worktree_init._ensure) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert calls == [tmp_path]


def test_ensure_is_quiet_when_nothing_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A built target/ and a set hooks path cost a few stats and print nothing."""
    (tmp_path / "target" / "debug").mkdir(parents=True)
    monkeypatch.setattr(worktree_init, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        worktree_init, "ensure_hooks_path", lambda _repo: [Line("=", "core.hooksPath .githooks")]
    )

    def no_seed() -> list[Line]:
        raise AssertionError("a built target/ is never seeded")

    monkeypatch.setattr(worktree_init, "_seed_target", no_seed)
    assert worktree_init._ensure() == 0
    assert capsys.readouterr().out == ""


def test_ensure_reports_what_it_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(worktree_init, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        worktree_init,
        "ensure_hooks_path",
        lambda _repo: [Line("+", "core.hooksPath -> .githooks", news=True)],
    )
    monkeypatch.setattr(
        worktree_init, "_seed_target", lambda: [Line("+", "target/ seeded from E:\a", news=True)]
    )
    assert worktree_init.main(["ensure"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "  + core.hooksPath -> .githooks",
        "  + target/ seeded from E:\a",
    ]


def _bare_init(
    monkeypatch: pytest.MonkeyPatch, checkout: Path, *, corpus: bool = True
) -> list[str]:
    """Point init at *checkout* with ensure and uv stubbed; returns the calls made."""
    calls: list[str] = []
    if corpus:
        game = checkout.parent / "data" / "corpus" / "stisldem"
        game.mkdir(parents=True, exist_ok=True)
        (game / "PLAYONE.EXE").write_bytes(b"MZ")
    monkeypatch.setattr(worktree_init, "REPO_ROOT", checkout)
    monkeypatch.setattr(dataroot, "REPO_ROOT", checkout)
    monkeypatch.setenv(dataroot.DATA_ENV, str(checkout.parent / "data"))
    dataroot.data_root.cache_clear()

    def record(name: str) -> Callable[..., int]:
        def call(*_args: object, **_kwargs: object) -> int:
            calls.append(name)
            return 0

        return call

    monkeypatch.setattr(worktree_init, "_ensure", record("ensure"))
    monkeypatch.setattr(worktree_init, "_uv_sync", record("sync"))
    return calls


def test_init_reports_legacy_links_and_keeps_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An old linked worktree keeps its links until reap unlinks them (ADR 0018, ADR 0036)."""
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    shared = tmp_path / "shared"
    shared.mkdir()
    dataroot.create_link(checkout / ".cache", shared)
    calls = _bare_init(monkeypatch, checkout)
    assert worktree_init._init(migrate=False) == 0
    assert calls == ["ensure", "sync"]
    assert dataroot.is_link(checkout / ".cache")
    assert "  ~ .cache is a link from the old layout; reap unlinks it" in capsys.readouterr().out
    dataroot.remove_link(checkout / ".cache")


def test_init_creates_no_links(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    checkout = tmp_path / "checkout"
    (checkout / "corpus").mkdir(parents=True)
    _bare_init(monkeypatch, checkout)
    assert worktree_init._init(migrate=False) == 0
    assert worktree_init._reparse_points(checkout) == []


def test_ensure_survives_a_hooks_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every cargo task depends on ensure, so a git that will not run must not stop them."""
    (tmp_path / "target" / "debug").mkdir(parents=True)
    monkeypatch.setattr(worktree_init, "REPO_ROOT", tmp_path)

    def no_git(_repo: Path) -> list[str]:
        raise dataroot.SharedDataError("git is not on PATH")

    monkeypatch.setattr(worktree_init, "ensure_hooks_path", no_git)
    assert worktree_init.main(["ensure"]) == 0
    assert "  ! hooks: git is not on PATH" in capsys.readouterr().out


def test_ensure_skips_the_hooks_path_outside_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "target" / "debug").mkdir(parents=True)
    monkeypatch.setattr(worktree_init, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(dataroot, "REPO_ROOT", tmp_path)

    def never(_repo: Path) -> list[str]:
        raise AssertionError("outside git there is no hooks path to set")

    monkeypatch.setattr(worktree_init, "ensure_hooks_path", never)
    assert worktree_init._ensure() == 0
    assert capsys.readouterr().out == ""


def test_ensure_tags_a_target_it_creates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cargo writes CACHEDIR.TAG only into a target/ it creates, and ensure creates it first."""
    monkeypatch.setattr(worktree_init, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(worktree_init, "ensure_hooks_path", lambda _repo: [])
    monkeypatch.setattr(worktree_init, "_seed_target", lambda: [Line("-", "target/ not seeded: x")])
    assert worktree_init._ensure() == 0
    tag = (tmp_path / "target" / "CACHEDIR.TAG").read_text(encoding="utf-8")
    assert tag.startswith("Signature: 8a477f597d28d172789f06886806bc55")


def test_ensure_makes_the_scratch_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A shell redirect into build/scratch/ fails in a fresh worktree unless something makes it."""
    monkeypatch.setattr(worktree_init, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(worktree_init, "ensure_hooks_path", lambda _repo: [])
    monkeypatch.setattr(worktree_init, "_seed_target", list)
    assert worktree_init._ensure() == 0
    assert (tmp_path / "build" / "scratch").is_dir()


def test_ensure_carries_on_when_the_lock_times_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(worktree_init, "REPO_ROOT", tmp_path)

    def stuck(path: Path) -> contextlib.AbstractContextManager[None]:
        raise TimeoutError(f"{path} still locked")

    monkeypatch.setattr(worktree_init, "exclusive", stuck)
    assert worktree_init._ensure() == 0
    out = capsys.readouterr().out
    assert "  ! ensure: " in out
    assert "core.hooksPath not checked" in out


def test_seed_command_takes_the_ensure_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``mise run seed`` beside a cargo lane's ensure must not seed into one staging directory."""
    monkeypatch.setattr(worktree_init, "REPO_ROOT", tmp_path)
    events: list[str] = []

    @contextlib.contextmanager
    def held(path: Path) -> Iterator[None]:
        events.append(f"lock {path.name}")
        yield
        events.append("unlock")

    monkeypatch.setattr(worktree_init, "exclusive", held)

    def seed() -> list[Line]:
        events.append("seed")
        return [Line("-", "target/ not seeded: x")]

    monkeypatch.setattr(worktree_init, "_seed_target", seed)
    assert worktree_init.main(["seed"]) == 0
    assert events == ["lock .ensure.lock", "seed", "unlock"]


def test_init_fails_without_game_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A fresh machine finds out at init, not at its first capture."""
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    _bare_init(monkeypatch, checkout, corpus=False)
    assert worktree_init._init(migrate=False) == 1
    assert "corpus is missing" in capsys.readouterr().out


def test_init_warns_about_data_at_an_old_link_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    checkout = tmp_path / "checkout"
    frames = checkout / "build" / "parity" / "captures" / "vault-ctry" / "frames"
    frames.mkdir(parents=True)
    (frames / "meta.json").write_text("{}", encoding="utf-8")
    _bare_init(monkeypatch, checkout)
    assert worktree_init._init(migrate=False) == 0
    out = capsys.readouterr().out
    assert "build/parity/captures holds data the data root does not read" in out


def test_ensure_tags_a_target_another_lane_just_made(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate's cargo lanes run ensure at once, so target/ can appear between check and create."""
    (tmp_path / "target").mkdir()
    monkeypatch.setattr(worktree_init, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(worktree_init, "ensure_hooks_path", lambda _repo: [])
    monkeypatch.setattr(worktree_init, "_seed_target", lambda: [Line("-", "target/ not seeded: x")])
    assert worktree_init._ensure() == 0
    assert (tmp_path / "target" / "CACHEDIR.TAG").is_file()
    assert worktree_init._ensure() == 0


def test_ensure_survives_a_lock_that_cannot_be_taken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(worktree_init, "REPO_ROOT", tmp_path)

    def no_locks(_path: Path) -> contextlib.AbstractContextManager[None]:
        raise OSError(errno.ENOLCK, "No locks available")

    monkeypatch.setattr(worktree_init, "exclusive", no_locks)
    assert worktree_init._ensure() == 0
    assert "  ! ensure: " in capsys.readouterr().out


def test_ensure_survives_a_git_that_will_not_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "target" / "debug").mkdir(parents=True)
    monkeypatch.setattr(worktree_init, "REPO_ROOT", tmp_path)

    def broken(_repo: Path) -> list[str]:
        raise PermissionError("git.exe: access denied")

    monkeypatch.setattr(worktree_init, "primary_checkout", lambda: tmp_path)
    monkeypatch.setattr(worktree_init, "ensure_hooks_path", broken)
    assert worktree_init._ensure() == 0
    assert "  ! hooks: git.exe: access denied" in capsys.readouterr().out


def test_seed_reports_a_lock_that_cannot_be_taken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``exclusive`` raises any lock failure but contention; seed reports it, as ensure does."""
    monkeypatch.setattr(worktree_init, "REPO_ROOT", tmp_path)

    def no_locks(_path: Path) -> contextlib.AbstractContextManager[None]:
        raise OSError(errno.ENOLCK, "No locks available")

    monkeypatch.setattr(worktree_init, "exclusive", no_locks)
    assert worktree_init.main(["seed"]) == 1
    assert "  ! seed: " in capsys.readouterr().out


def test_ensure_checks_the_hooks_path_once_per_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A no-op ensure costs a few stats: git runs again only after target/ goes (ADR 0036)."""
    (tmp_path / "target" / "debug").mkdir(parents=True)
    monkeypatch.setattr(worktree_init, "REPO_ROOT", tmp_path)
    calls: list[Path] = []

    def hooks(repo: Path) -> list[Line]:
        calls.append(repo)
        return [Line("=", "core.hooksPath .githooks")]

    monkeypatch.setattr(worktree_init, "ensure_hooks_path", hooks)
    worktree_init._ensure()
    worktree_init._ensure()
    assert calls == [tmp_path]
    worktree_init._ensure(report=True)
    assert calls == [tmp_path, tmp_path]


def test_ensure_checks_again_after_a_hooks_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "target" / "debug").mkdir(parents=True)
    monkeypatch.setattr(worktree_init, "REPO_ROOT", tmp_path)
    calls: list[Path] = []

    def hooks(repo: Path) -> list[Line]:
        calls.append(repo)
        return [Line("!", "could not set core.hooksPath: locked", news=True)]

    monkeypatch.setattr(worktree_init, "ensure_hooks_path", hooks)
    worktree_init._ensure()
    worktree_init._ensure()
    assert len(calls) == 2
