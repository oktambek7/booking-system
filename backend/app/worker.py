"""Stand-alone background worker.

    python -m app.worker          # run the notification and catalogue loops until stopped
    python -m app.worker --once   # run each job one time and exit (for a cron-style job)

Use it when the API runs on several instances: set RUN_BACKGROUND_JOBS=false on the web
services and run exactly one worker. Several workers are still safe (see app/jobs.py).
"""
import asyncio
import logging
import signal
import sys
from . import jobs
from .config import settings
from .migrate import assert_schema_current, upgrade_to_head

logger = logging.getLogger("parda.worker")

def prepare() -> None:
    settings.assert_production_ready()
    if settings.auto_migrate:
        upgrade_to_head()
    else:
        assert_schema_current()

def run_once() -> tuple[dict, list[str]]:
    """Run every job once. Returns (results, names of failed jobs); one failure never stops the others."""
    selected = {"notifications": jobs.notification_cycle, "cinematica": jobs.cinematica_refresh}
    if settings.tmdb_read_token:
        selected["tmdb"] = jobs.tmdb_refresh
    results, failed = {}, []
    for name, job in selected.items():
        try:
            results[name] = job()
        except Exception as exc:
            logger.exception("%s job failed", name)
            results[name] = f"failed: {type(exc).__name__}: {exc}"
            failed.append(name)
    return results, failed

async def run_forever() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:      # Windows: Ctrl+C surfaces as KeyboardInterrupt instead
            pass
    tasks = jobs.start_all()
    logger.info("Parda worker started with %s job loop(s)", len(tasks))
    try:
        await stop.wait()
    finally:
        await jobs.stop_all(tasks)
        logger.info("Parda worker stopped")

def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    prepare()
    if "--once" in argv:
        results, failed = run_once()
        print(results)
        return 1 if failed else 0
    try:
        asyncio.run(run_forever())
    except KeyboardInterrupt:
        pass
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
