import tarfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath


TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".py",
    ".json",
    ".csv",
    ".log",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
    ".css",
    ".js",
    ".ts",
}
TEXT_PREVIEW_LIMIT = 12000


@dataclass
class PreviewEntry:
    name: str
    path: str
    is_dir: bool
    size_bytes: int = 0
    modified_at: str = "-"
    children: list["PreviewEntry"] = field(default_factory=list)


@dataclass
class FilePreview:
    file_name: str
    file_path: str
    file_size_bytes: int
    file_modified_at: str
    preview_kind: str
    entries: list[PreviewEntry] = field(default_factory=list)
    text_preview: str = ""
    preview_message: str = ""


@dataclass
class ArchiveMember:
    path: str
    is_dir: bool
    size_bytes: int
    modified_at: str


def format_bytes(size_bytes: int) -> str:
    size = float(max(0, size_bytes))
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    return f"{size:.1f} {units[unit_index]}"


def build_file_preview(file_path: str) -> FilePreview:
    submission_file = _resolve_submission_file(file_path)
    stat = submission_file.stat()

    if _is_archive_file(submission_file):
        return FilePreview(
            file_name=submission_file.name,
            file_path=str(submission_file),
            file_size_bytes=int(stat.st_size),
            file_modified_at=_format_timestamp(stat.st_mtime),
            preview_kind="archive",
            entries=_build_tree(_load_archive_entries(submission_file)),
            preview_message="Archive contents loaded.",
        )

    if _is_text_file(submission_file):
        return FilePreview(
            file_name=submission_file.name,
            file_path=str(submission_file),
            file_size_bytes=int(stat.st_size),
            file_modified_at=_format_timestamp(stat.st_mtime),
            preview_kind="text",
            text_preview=_read_text_preview(submission_file),
            preview_message="Text preview loaded.",
        )

    return FilePreview(
        file_name=submission_file.name,
        file_path=str(submission_file),
        file_size_bytes=int(stat.st_size),
        file_modified_at=_format_timestamp(stat.st_mtime),
        preview_kind="generic",
        preview_message="Binary file selected. Metadata preview only.",
    )


def validate_submission_file(file_path: str | Path):
    _resolve_submission_file(file_path)


def _resolve_submission_file(file_path: str | Path) -> Path:
    submission_file = Path(file_path).expanduser().resolve()
    if not submission_file.exists() or not submission_file.is_file():
        raise ValueError("Selected file does not exist.")
    return submission_file


def _is_archive_file(file_path: Path) -> bool:
    return zipfile.is_zipfile(file_path) or tarfile.is_tarfile(file_path)


def _is_text_file(file_path: Path) -> bool:
    if file_path.suffix.lower() in TEXT_EXTENSIONS:
        return True

    try:
        with file_path.open("rb") as handle:
            sample = handle.read(2048)
    except Exception:
        return False

    if not sample:
        return True

    if b"\x00" in sample:
        return False

    try:
        decoded = sample.decode("utf-8")
    except UnicodeDecodeError:
        return False

    control_characters = sum(1 for character in decoded if ord(character) < 32 and character not in "\n\r\t")
    return control_characters == 0


def _read_text_preview(file_path: Path) -> str:
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"Could not read text preview: {exc}"

    if len(text) <= TEXT_PREVIEW_LIMIT:
        return text
    return text[:TEXT_PREVIEW_LIMIT] + "\n\n[Preview truncated]"


def _load_archive_entries(archive_file: Path) -> list[ArchiveMember]:
    if zipfile.is_zipfile(archive_file):
        return _zip_members(archive_file)

    if tarfile.is_tarfile(archive_file):
        return _tar_members(archive_file)

    raise ValueError("Unsupported archive format.")


def _zip_members(archive_file: Path) -> list[ArchiveMember]:
    members: list[ArchiveMember] = []
    with zipfile.ZipFile(archive_file) as archive:
        for info in archive.infolist():
            path = info.filename.rstrip("/")
            if not path:
                continue
            members.append(
                ArchiveMember(
                    path=path,
                    is_dir=info.is_dir(),
                    size_bytes=0 if info.is_dir() else int(info.file_size),
                    modified_at=_format_zip_datetime(info.date_time),
                )
            )
    return members


def _tar_members(archive_file: Path) -> list[ArchiveMember]:
    members: list[ArchiveMember] = []
    with tarfile.open(archive_file) as archive:
        for info in archive.getmembers():
            path = info.name.rstrip("/")
            if not path:
                continue
            members.append(
                ArchiveMember(
                    path=path,
                    is_dir=info.isdir(),
                    size_bytes=0 if info.isdir() else int(info.size),
                    modified_at=_format_timestamp(info.mtime),
                )
            )
    return members


def _build_tree(members: list[ArchiveMember]) -> list[PreviewEntry]:
    roots: list[PreviewEntry] = []
    node_map: dict[str, PreviewEntry] = {}

    for member in members:
        normalized_parts = [part for part in PurePosixPath(member.path).parts if part not in {"", "."}]
        if not normalized_parts:
            continue

        for index, part in enumerate(normalized_parts):
            current_path = "/".join(normalized_parts[: index + 1])
            parent_path = "/".join(normalized_parts[:index])
            is_leaf = index == len(normalized_parts) - 1
            node = node_map.get(current_path)

            if node is None:
                node = PreviewEntry(
                    name=part,
                    path=current_path,
                    is_dir=not is_leaf or member.is_dir,
                )
                node_map[current_path] = node
                if parent_path:
                    node_map[parent_path].children.append(node)
                else:
                    roots.append(node)

            if is_leaf:
                node.is_dir = member.is_dir
                node.size_bytes = member.size_bytes
                node.modified_at = member.modified_at

    _sort_entries(roots)
    return roots


def _sort_entries(entries: list[PreviewEntry]):
    entries.sort(key=lambda entry: (not entry.is_dir, entry.name.lower()))
    for entry in entries:
        _sort_entries(entry.children)


def _format_timestamp(timestamp: float | int | None) -> str:
    if not timestamp:
        return "-"
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def _format_zip_datetime(date_time: tuple[int, int, int, int, int, int]) -> str:
    try:
        return datetime(*date_time).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "-"
