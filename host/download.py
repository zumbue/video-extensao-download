"""Download com yt-dlp, qualidade escolhida e ZIP opcional."""

import math
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from .naming import DownloadRequest, UserError, output_extension
from .reveal import launch_file_manager

QUALITIES = {
    "best": "bv*+ba/b",
    "1080": "bv*[height<=1080]+ba/b[height<=1080]/b[height<=1080]",
    "720": "bv*[height<=720]+ba/b[height<=720]/b[height<=720]",
    "480": "bv*[height<=480]+ba/b[height<=480]/b[height<=480]",
    "360": "bv*[height<=360]+ba/b[height<=360]/b[height<=360]",
    "audio": "bestaudio/best",
}
PREFERRED_EXTENSIONS = (".mp4", ".mp3", ".m4a", ".webm", ".mkv", ".opus", ".ogg")
IGNORED_EXTENSIONS = {".part", ".ytdl", ".jpg", ".jpeg", ".png", ".webp", ".json"}
PARTIAL_EXTENSIONS = {".mp4", ".mp3", ".m4a", ".webm", ".mkv", ".opus", ".ogg", ".part", ".ts"}
# Reencodar um trecho longo trava o FFmpeg no vídeo inteiro. Cortes curtos continuam precisos.
PRECISE_CUT_SECONDS = 180


class BusyError(Exception):
    """Já existe um download rodando."""


class DownloadCancelled(Exception):
    """A pessoa cancelou."""


def precise_cut(start: float | None, end: float | None) -> bool:
    """Cortes curtos e com fim marcado podem reencodar. O resto copia o fluxo."""
    if end is None:
        return False
    begin = 0.0 if start is None else start
    length = end - begin
    return 0 < length <= PRECISE_CUT_SECONDS


def partial_bytes(directory: Path) -> int | None:
    if not directory.is_dir():
        return None
    total = 0
    found = False
    for path in directory.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        if path.suffix.lower() not in PARTIAL_EXTENSIONS and not path.name.endswith(".part"):
            continue
        try:
            total += path.stat().st_size
        except OSError:
            continue
        found = True
    return total if found else None


class ChildTracker:
    """Lembra processos abertos pelo yt-dlp para o cancelamento poder matá-los."""

    def __init__(self):
        self._lock = threading.Lock()
        self._children: list[subprocess.Popen] = []

    def remember(self, process: subprocess.Popen) -> None:
        with self._lock:
            self._children.append(process)

    def stop(self) -> None:
        with self._lock:
            children = list(self._children)
        for process in children:
            terminate_process(process)


def terminate_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name != "nt":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except OSError:
            process.terminate()
    else:
        process.terminate()
    try:
        process.wait(timeout=0.4)
        return
    except subprocess.TimeoutExpired:
        pass
    if os.name != "nt":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            process.kill()
    else:
        process.kill()


@contextmanager
def track_children(tracker: ChildTracker):
    import subprocess as subprocess_module

    original_sub = subprocess_module.Popen
    ytu = None
    original_yt = None
    try:
        import yt_dlp.utils as ytu
        original_yt = ytu.Popen.__init__
    except ImportError:
        ytu = None

    class Tracked(original_sub):
        def __init__(self, *args, **kwargs):
            if os.name != "nt":
                kwargs["start_new_session"] = True
            super().__init__(*args, **kwargs)
            tracker.remember(self)

    def tracked_yt_init(self, *args, **kwargs):
        if os.name != "nt":
            kwargs["start_new_session"] = True
        original_yt(self, *args, **kwargs)
        tracker.remember(self)

    subprocess_module.Popen = Tracked
    if ytu is not None and original_yt is not None:
        ytu.Popen.__init__ = tracked_yt_init
    try:
        yield
    finally:
        subprocess_module.Popen = original_sub
        if ytu is not None and original_yt is not None:
            ytu.Popen.__init__ = original_yt


def format_selector(quality: str) -> str:
    try:
        return QUALITIES[quality]
    except KeyError as exc:
        raise UserError("Qualidade desconhecida.") from exc


def unique_destination(directory: Path, stem: str, extension: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / f"{stem}{extension}"
    index = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{index}{extension}"
        index += 1
    return candidate


def pick_media(directory: Path) -> Path:
    files = [
        path for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() not in IGNORED_EXTENSIONS
    ]
    if not files:
        raise UserError("O download terminou sem arquivo.")
    for extension in PREFERRED_EXTENSIONS:
        matches = [path for path in files if path.suffix.lower() == extension]
        if matches:
            return max(matches, key=lambda path: path.stat().st_size)
    return max(files, key=lambda path: path.stat().st_size)


def js_runtimes() -> dict:
    for name in ("deno", "node", "bun"):
        found = shutil.which(name)
        if found:
            return {name: {"path": found}}
    return {}


def ytdlp_version() -> str | None:
    try:
        import yt_dlp
    except ImportError:
        return None
    return getattr(yt_dlp.version, "__version__", None)


def default_range_factory(start: float, end: float | None):
    """Intervalo do yt-dlp. Fim ausente vai até o final do vídeo."""
    from yt_dlp.utils import download_range_func

    stop = float("inf") if end is None else end
    return download_range_func(None, [(start, stop)])


def media_facts(info: dict) -> dict:
    if info.get("_type") == "playlist":
        info = next((item for item in info.get("entries") or [] if isinstance(item, dict)), {})
    duration = info.get("duration")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        duration_out = None
    elif not math.isfinite(duration) or duration <= 0:
        duration_out = None
    else:
        duration_out = round(float(duration), 3)
    title = info.get("title")
    return {"duration": duration_out, "title": title if isinstance(title, str) else None}


def probe_media(url: str) -> dict:
    import yt_dlp

    options = {
        "quiet": True,
        "no_warnings": True,
        "no_color": True,
        "noplaylist": True,
        "skip_download": True,
        "socket_timeout": 20,
        "retries": 1,
        "extractor_retries": 1,
    }
    runtimes = js_runtimes()
    if runtimes:
        options["js_runtimes"] = runtimes
        options["remote_components"] = ["ejs:github"]
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False) or {}
    return media_facts(info)


def default_runner(url: str, opts: dict) -> None:
    import yt_dlp

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])


@dataclass
class Job:
    id: str
    state: str = "queued"
    progress: float = 0
    message: str = "Na fila."
    path: str | None = None
    name: str | None = None
    error: str | None = None
    downloaded: int | None = None
    total: int | None = None
    speed: float | None = None
    hooked_at: float | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "id": self.id,
                "state": self.state,
                "progress": round(self.progress, 1),
                "message": self.message,
                "path": self.path,
                "name": self.name,
                "error": self.error,
                "downloaded": self.downloaded,
                "total": self.total,
                "speed": None if self.speed is None else round(float(self.speed), 1),
            }

    def update(self, **fields: object) -> None:
        with self.lock:
            if self.state in {"done", "error", "cancelled"}:
                return
            if self.cancel_event.is_set() and fields.get("state") == "running":
                return
            for key, value in fields.items():
                setattr(self, key, value)


class DownloadManager:
    def __init__(self, downloads_dir: Path, runner=None, ffmpeg_ok=None, range_factory=None, on_settled=None, on_start=None):
        self.downloads_dir = Path(downloads_dir)
        self._runner = runner or default_runner
        self._ffmpeg_ok = ffmpeg_ok if ffmpeg_ok is not None else (lambda: shutil.which("ffmpeg") is not None)
        self._range_factory = range_factory or default_range_factory
        self._on_settled = on_settled
        self._on_start = on_start
        self.opener = launch_file_manager
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def busy(self) -> bool:
        with self._lock:
            return any(job.state in {"queued", "running", "cancelling"} for job in self._jobs.values())

    def reveal(self, name: str | None = None) -> Path:
        directory = self.downloads_dir.expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        target = directory
        if isinstance(name, str) and name.strip():
            leaf = Path(name).name
            if leaf and leaf not in {".", ".."} and leaf == name.strip():
                candidate = (directory / leaf).resolve()
                if candidate.parent == directory and candidate.is_file():
                    target = candidate
        self.opener(target)
        return target

    def get(self, job_id: str) -> dict | None:
        job = self._jobs.get(job_id)
        return None if job is None else job.snapshot()

    def library(self) -> dict:
        with self._lock:
            active = next(
                (job.snapshot() for job in self._jobs.values() if job.state in {"queued", "running", "cancelling"}),
                None,
            )
        return {"active": active, "files": self.finished_files()}

    def finished_files(self) -> list[dict]:
        directory = self.downloads_dir.expanduser().resolve()
        if not directory.is_dir():
            return []
        allowed = {".mp4", ".mp3", ".zip", ".webm", ".mkv", ".m4a"}
        rows = []
        for path in directory.iterdir():
            if path.is_symlink() or not path.is_file() or path.name.startswith("."):
                continue
            if path.suffix.lower() not in allowed:
                continue
            stat = path.stat()
            rows.append({"name": path.name, "size": stat.st_size, "mtime": int(stat.st_mtime)})
        rows.sort(key=lambda row: (row["mtime"], row["name"]), reverse=True)
        return rows[:30]

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None:
            return False
        job.cancel_event.set()
        with job.lock:
            if job.state in {"queued", "running"}:
                job.state = "cancelling"
                job.message = "Cancelando..."
        return True

    def start(self, request: DownloadRequest) -> dict:
        if not self._ffmpeg_ok():
            raise UserError("FFmpeg não está instalado.")
        if self._runner is default_runner and ytdlp_version() is None:
            raise UserError("Instale as dependências com ./run.sh.")
        if request.quality not in QUALITIES:
            raise UserError("Qualidade desconhecida.")
        with self._lock:
            if any(job.state in {"queued", "running", "cancelling"} for job in self._jobs.values()):
                raise BusyError("Já existe um download em andamento.")
            job = Job(id=uuid.uuid4().hex[:12])
            self._jobs[job.id] = job
        if self._on_start is not None:
            self._on_start()
        threading.Thread(target=self._worker, args=(job, request), daemon=True).start()
        return job.snapshot()

    def _watch_download(self, job: Job, temporary: Path, tracker: ChildTracker, stop: threading.Event) -> None:
        last_size = None
        last_time = time.monotonic()
        while not stop.wait(0.4):
            if job.cancel_event.is_set():
                tracker.stop()
                return
            size = partial_bytes(temporary)
            now = time.monotonic()
            if size is None:
                continue
            if last_size is not None and now > last_time:
                speed = max(0, size - last_size) / (now - last_time)
            else:
                speed = 0
            last_size = size
            last_time = now
            with job.lock:
                if job.state != "running" or job.message == "Processando...":
                    continue
                if job.hooked_at is not None and now - job.hooked_at < 1.5:
                    continue
            job.update(state="running", message="Baixando...", downloaded=size, speed=speed)

    def _worker(self, job: Job, request: DownloadRequest) -> None:
        temporary = Path(tempfile.mkdtemp(prefix="mde-"))
        tracker = ChildTracker()
        stop_watching = threading.Event()
        watcher = threading.Thread(
            target=self._watch_download,
            args=(job, temporary, tracker, stop_watching),
            daemon=True,
        )
        try:
            job.update(state="running", message="Baixando...", progress=0)
            if job.cancel_event.is_set():
                raise DownloadCancelled()
            watcher.start()
            with track_children(tracker):
                self._runner(request.url, self._options(request, temporary, job))
            if job.cancel_event.is_set():
                raise DownloadCancelled()
            destination = self._store(pick_media(temporary), request)
            job.update(
                state="done",
                progress=100,
                message="Arquivo salvo.",
                path=str(destination),
                name=destination.name,
                error=None,
            )
        except DownloadCancelled:
            job.update(state="cancelled", message="Download cancelado.", error=None)
        except Exception as exc:
            if job.cancel_event.is_set() or exc.__class__.__name__ == "DownloadCancelled":
                job.update(state="cancelled", message="Download cancelado.", error=None)
            else:
                message = str(exc).strip() or "O download falhou."
                for prefix in ("ERROR:", "WARNING:"):
                    message = message.removeprefix(prefix).strip()
                message = message[:400]
                job.update(state="error", message=message, error=message)
        finally:
            stop_watching.set()
            if job.cancel_event.is_set():
                tracker.stop()
            shutil.rmtree(temporary, ignore_errors=True)
            if self._on_settled is not None:
                self._on_settled()

    def _store(self, produced: Path, request: DownloadRequest) -> Path:
        if request.compress:
            destination = unique_destination(self.downloads_dir, request.filename, ".zip")
            with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(produced, arcname=f"{request.filename}{produced.suffix.lower()}")
            return destination
        extension = produced.suffix.lower() or output_extension(request.quality, False)
        destination = unique_destination(self.downloads_dir, request.filename, extension)
        shutil.move(produced, destination)
        return destination

    def _options(self, request: DownloadRequest, temporary: Path, job: Job) -> dict:
        def hook(data: dict) -> None:
            if job.cancel_event.is_set():
                raise DownloadCancelled()
            with job.lock:
                job.hooked_at = time.monotonic()
            status = data.get("status")
            if status == "downloading":
                total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
                done = data.get("downloaded_bytes") or 0
                progress = (done / total * 100) if total else job.progress
                raw_speed = data.get("speed")
                speed = float(raw_speed) if isinstance(raw_speed, (int, float)) and raw_speed >= 0 else None
                job.update(
                    state="running",
                    progress=progress,
                    message="Baixando...",
                    downloaded=int(done),
                    total=int(total) if total else None,
                    speed=speed,
                )
            elif status == "finished":
                job.update(state="running", progress=100, message="Processando...", speed=None)

        options = {
            "quiet": True,
            "no_warnings": True,
            "no_color": True,
            "noplaylist": True,
            "retries": 3,
            "paths": {"home": str(temporary)},
            "outtmpl": {"default": "media.%(ext)s"},
            "format": format_selector(request.quality),
            "progress_hooks": [hook],
            "concurrent_fragment_downloads": 1,
        }
        runtimes = js_runtimes()
        if runtimes:
            options["js_runtimes"] = runtimes
            options["remote_components"] = ["ejs:github"]
        if request.quality == "audio":
            options["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
            options["final_ext"] = "mp3"
        else:
            options["merge_output_format"] = "mp4"
        start = request.start_time
        end = request.end_time
        if end is not None or (start is not None and start > 0):
            options["download_ranges"] = self._range_factory(0.0 if start is None else start, end)
            # Reencodar só um trecho curto. Um início sem fim faria o FFmpeg
            # reprocessar o vídeo inteiro e o cancelamento não o alcançava.
            if precise_cut(start, end):
                options["force_keyframes_at_cuts"] = True
        return options
