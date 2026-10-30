"""Download com yt-dlp, qualidade escolhida e ZIP opcional."""

import math
import shutil
import tempfile
import threading
import uuid
import zipfile
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


class BusyError(Exception):
    """Já existe um download rodando."""


class DownloadCancelled(Exception):
    """A pessoa cancelou."""


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
            }

    def update(self, **fields: object) -> None:
        with self.lock:
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
            return any(job.state in {"queued", "running"} for job in self._jobs.values())

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

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None:
            return False
        job.cancel_event.set()
        return True

    def start(self, request: DownloadRequest) -> dict:
        if not self._ffmpeg_ok():
            raise UserError("FFmpeg não está instalado.")
        if self._runner is default_runner and ytdlp_version() is None:
            raise UserError("Instale as dependências com ./run.sh.")
        if request.quality not in QUALITIES:
            raise UserError("Qualidade desconhecida.")
        with self._lock:
            if any(job.state in {"queued", "running"} for job in self._jobs.values()):
                raise BusyError("Já existe um download em andamento.")
            job = Job(id=uuid.uuid4().hex[:12])
            self._jobs[job.id] = job
        if self._on_start is not None:
            self._on_start()
        threading.Thread(target=self._worker, args=(job, request), daemon=True).start()
        return job.snapshot()

    def _worker(self, job: Job, request: DownloadRequest) -> None:
        temporary = Path(tempfile.mkdtemp(prefix="mde-"))
        try:
            job.update(state="running", message="Baixando...", progress=0)
            if job.cancel_event.is_set():
                raise DownloadCancelled()
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
            status = data.get("status")
            if status == "downloading":
                total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
                done = data.get("downloaded_bytes") or 0
                progress = (done / total * 100) if total else job.progress
                job.update(state="running", progress=progress, message="Baixando...")
            elif status == "finished":
                job.update(state="running", progress=100, message="Processando...")

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
            # Sem cópia de fluxo, o FFmpeg descarta o pedaço até o tempo exato.
            options["force_keyframes_at_cuts"] = True
        return options
