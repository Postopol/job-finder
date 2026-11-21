"""Command line: serve, collect, check-sources, reparse."""
from __future__ import annotations

import argparse
import copy
import json
import logging
import sqlite3
import sys
from pathlib import Path

from . import archive, collector, db
from .http import PoliteClient
from .sources import REGISTRY

log = logging.getLogger(__name__)


def project_root() -> Path:
    """Directory with pyproject.toml above the package; CWD when installed elsewhere."""
    root = Path(__file__).resolve().parent.parent
    return root if (root / "pyproject.toml").is_file() else Path.cwd()


def default_db_path() -> Path:
    return project_root() / "data" / "jobs.db"


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request is noise


def _check_source_name(name: str | None) -> bool:
    if name is not None and name not in REGISTRY:
        print(f"Неизвестный источник: {name}. Есть: {', '.join(REGISTRY)}", file=sys.stderr)
        return False
    return True


def _read_settings(path: Path) -> dict:
    """Settings for check-sources without writing anything (no file → defaults)."""
    settings = copy.deepcopy(db.DEFAULT_SETTINGS)
    if not path.is_file():
        return settings
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        finally:
            conn.close()
    except sqlite3.Error as e:
        log.warning("не удалось прочитать настройки из %s (%s), беру значения по умолчанию",
                    path, e)
        return settings
    settings.update({k: json.loads(v) for k, v in rows})
    return settings


def cmd_serve(args) -> int:
    import uvicorn

    from .web.app import create_app

    url = f"http://127.0.0.1:{args.port}"
    print(f"Job Finder: {url}  (база {args.db})", flush=True)
    uvicorn.run(create_app(args.db), host="127.0.0.1", port=args.port, log_level="info")
    return 0


def cmd_collect(args) -> int:
    if not _check_source_name(args.source):
        return 2
    conn = db.connect(args.db)
    try:
        results = collector.collect(conn, sources=REGISTRY, client_factory=PoliteClient,
                                    only=args.source)
    finally:
        conn.close()
    if not results:
        if collector.is_running(args.db):
            print("Сбор уже идёт", file=sys.stderr)
            return 1
        print("Ничего не запущено: все источники выключены")
        return 0
    for r in results:
        state = ("ok" + (f" ({r.error})" if r.error else "")) if r.ok else f"ошибка: {r.error}"
        print(f"{r.source:<14} {state} · получено {r.fetched}, новых {r.new}, "
              f"пропущено {r.skipped}, запросов {r.requests}")
    return 0 if any(r.ok for r in results) else 1


def _first_only():
    """wants() for check-sources: one detail request per source is enough to test parsing."""
    state = {"left": 1}

    def wants(job) -> bool:
        if state["left"]:
            state["left"] -= 1
            return True
        return False
    return wants


def cmd_check_sources(args) -> int:
    if not _check_source_name(args.source):
        return 2
    exists = args.db.is_file()  # never create the DB (or its lock) for a dry check
    with collector.file_lock(args.db if exists else None) as acquired:
        if not acquired:
            print("Сбор уже идёт — проверь источники позже", file=sys.stderr)
            return 1
        base = _read_settings(args.db)
        base["max_pages"] = 1
        names = [args.source] if args.source else list(REGISTRY)
        for name in names:
            client = None
            try:
                client = PoliteClient()
                jobs = REGISTRY[name].fetch(client, set(), _first_only(), copy.deepcopy(base))
                line = f"ok · вакансий {len(jobs)}"
                if getattr(client, "blocked", None):
                    line += f" · сайт ограничил доступ (HTTP {client.blocked})"
            except Exception as exc:
                line = f"ошибка: {collector._error_text(exc)}"
            finally:
                requests = getattr(client, "requests", 0)
                if client is not None:
                    client.close()
            print(f"{name:<14} {line} · запросов {requests}", flush=True)
    return 0


def cmd_reparse(args) -> int:
    if not _check_source_name(args.source):
        return 2
    conn = db.connect(args.db)
    try:
        count = archive.reparse(conn, args.source, sources=REGISTRY)
    finally:
        conn.close()
    print(f"Перепарсено вакансий: {count}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobfinder", description="Сборщик удалённых IT-вакансий")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, func, help_text, source=True):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--db", type=Path, default=None,
                       help="путь к базе (по умолчанию data/jobs.db в корне проекта)")
        if source:
            p.add_argument("--source", metavar="NAME", default=None, help="только этот источник")
        p.set_defaults(func=func)
        return p

    serve = add("serve", cmd_serve, "запустить веб-интерфейс на 127.0.0.1", source=False)
    serve.add_argument("--port", type=int, default=8000)
    add("collect", cmd_collect, "собрать вакансии сейчас")
    add("check-sources", cmd_check_sources, "проверить источники вживую, ничего не сохраняя")
    add("reparse", cmd_reparse, "перепарсить сохранённые ответы без сети")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.db is None:
        args.db = default_db_path()
    _setup_logging()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
