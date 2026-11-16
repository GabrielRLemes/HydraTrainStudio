"""Validate portable project paths without contacting a referenced network share."""
import ntpath
import stat
from pathlib import Path, PureWindowsPath


def reserved_name(name):
    if hasattr(ntpath, "isreserved"):
        return ntpath.isreserved(name)
    return PureWindowsPath(name).is_reserved()


def plain_path(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return path
    if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))):
        raise ValueError(f"Vínculo ou arquivo especial não permitido: {path.name}")
    return path


def project_path(root, value, *, nested=False):
    if not isinstance(value, str):
        raise ValueError("Caminho de projeto inválido.")
    parts = value.replace(chr(92), "/").split("/")
    if (not nested and len(parts) != 1) or any(
        not p or p in (".", "..") or p.endswith((" ", ".")) or reserved_name(p)
        or any(ord(c) < 32 or c in '<>:"|?*' for c in p) for p in parts
    ):
        raise ValueError("Caminho fora do projeto ou nome inválido.")
    path = plain_path(Path(root))
    for part in parts:
        path = plain_path(path / part)
    return path


def folder_files(root, recursive, exclude):
    pending = [plain_path(root)]
    while pending:
        folder = pending.pop()
        if folder == exclude:
            continue
        for entry in folder.iterdir():
            try:
                path = plain_path(entry)
            except ValueError:
                continue
            if path.is_file():
                yield path
            elif recursive and path.is_dir():
                pending.append(path)
