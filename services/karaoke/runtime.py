"""A request lease survives disconnects until the actual CPU work finishes."""

import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
import threading
from pathlib import Path

import psutil


logger = logging.getLogger(__name__)


class Workspaces:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for path in self.root.iterdir():
            if not path.is_dir() or path.is_symlink() or not re.fullmatch(r"run-[a-z0-9_]+", path.name):
                continue
            try:
                owner = json.loads((path / "owner.json").read_text())
                alive = psutil.pid_exists(owner["pid"]) and abs(psutil.Process(owner["pid"]).create_time() - owner["created"]) < 0.01
                if not alive:
                    shutil.rmtree(path)
            except (OSError, ValueError, KeyError, psutil.Error):
                continue  # Never delete a directory whose ownership cannot be verified.
        self.directory = Path(tempfile.mkdtemp(prefix="run-", dir=self.root))
        (self.directory / "owner.json").write_text(json.dumps({"pid": os.getpid(), "created": psutil.Process().create_time()}))

    def create(self) -> Path:
        return Path(tempfile.mkdtemp(prefix="request-", dir=self.directory))

    def close(self):
        shutil.rmtree(self.directory, ignore_errors=True)


class Admission:
    def __init__(self):
        self._lock = threading.Lock()
        self.tasks = set()

    def acquire(self):
        return Lease(self) if self._lock.acquire(blocking=False) else None


class Lease:
    def __init__(self, admission: Admission):
        self.admission = admission
        self.workspace: Path | None = None
        self._mutex = threading.Lock()
        self._request_done = False
        self._computing = 0
        self._released = False

    def _release_if_done(self):
        with self._mutex:
            if self._released or not self._request_done or self._computing:
                return
            self._released = True
        try:
            if self.workspace:
                shutil.rmtree(self.workspace, ignore_errors=True)
        finally:
            self.admission._lock.release()

    def request_finished(self):
        with self._mutex:
            self._request_done = True
        self._release_if_done()

    async def compute(self, function):
        with self._mutex:
            self._computing += 1
        task = asyncio.create_task(asyncio.to_thread(function))
        self.admission.tasks.add(task)

        def finished(completed):
            self.admission.tasks.discard(completed)
            if not completed.cancelled():
                completed.exception()  # Consume exceptions if the caller already disconnected.
            with self._mutex:
                self._computing -= 1
            self._release_if_done()

        task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def drain(self):
        if self.admission.tasks:
            await asyncio.gather(*list(self.admission.tasks), return_exceptions=True)
