from pathlib import Path

from .config import settings


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def workspace_root() -> Path:
    return project_root().parent


def resolve_from_project_root(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (project_root() / path).resolve()


def resolve_from_workspace_root(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (workspace_root() / path).resolve()


def applications_root() -> Path:
    return resolve_from_workspace_root(settings.applications_root)


def resolve_from_applications_root(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path

    normalized = raw_path.strip().replace("\\", "/")
    root_norm = settings.applications_root.strip().replace("\\", "/").strip("/")
    if root_norm and (normalized == root_norm or normalized.startswith(root_norm + "/")):
        return resolve_from_workspace_root(raw_path)

    return (applications_root() / path).resolve()


def is_within_path(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def safe_relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()
