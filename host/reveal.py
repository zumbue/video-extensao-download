"""Abre a pasta do download no gerenciador de arquivos."""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def launch_file_manager(path: Path) -> None:
    path = path.resolve()
    if sys.platform == "win32":
        if path.is_file():
            subprocess.Popen(["explorer", f"/select,{path}"])
        else:
            os.startfile(path)  # type: ignore[attr-defined]
        return
    if sys.platform == "darwin":
        command = ["open", "-R", str(path)] if path.is_file() else ["open", str(path)]
        subprocess.Popen(command, start_new_session=True)
        return
    if path.is_file():
        for program, flag in (("dolphin", "--select"), ("nautilus", "--select")):
            executable = shutil.which(program)
            if executable:
                subprocess.Popen([executable, flag, str(path)], start_new_session=True)
                return
        path = path.parent
    opener = shutil.which("xdg-open")
    if opener is None:
        raise OSError("xdg-open não está instalado.")
    subprocess.Popen([opener, str(path)], start_new_session=True)
