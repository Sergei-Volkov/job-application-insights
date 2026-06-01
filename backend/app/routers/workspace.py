from pathlib import Path
import shutil
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..config import settings
from ..dependencies import get_db, require_write_access
from ..helpers import slugify, today_iso
from ..models import JobApplication
from ..pathing import (
    applications_root,
    is_within_path,
    resolve_from_applications_root,
    resolve_from_workspace_root,
    safe_relative_path,
    workspace_root,
)
from ..schemas import (
    GenerateDocumentsRequest,
    GenerateDocumentsResult,
    WorkspaceFileReadResult,
    WorkspaceFileWriteRequest,
)

router = APIRouter(tags=["workspace"])


def templates_root() -> Path:
    return resolve_from_applications_root(settings.vacancies_template_dir)


def base_cv_template_path() -> Path:
    return resolve_from_applications_root(settings.base_cv_template_path)


def _build_docs_directory(record: JobApplication) -> Path:
    vacancies_root = applications_root() / "vacancies"
    return vacancies_root / f"{slugify(record.company)}_{slugify(record.role)}"


def _render_cover_letter(template_text: str, record: JobApplication, author_name: str) -> str:
    text = template_text
    text = text.replace("[Role Title]", record.role or "Role")
    text = text.replace("[Company]", record.company or "Company")
    text = text.replace(
        "[specific reason tied to company/role]", f"the role focus in {record.company or 'the company'}"
    )
    text = text.replace("[Author Name]", author_name)
    text = text.replace("[Your Name]", author_name)
    return text


def _render_vacancy_notes(template_text: str, record: JobApplication) -> str:
    date_found = (record.date_found or "").strip() or today_iso()
    source_url = (record.link or "").strip()
    source_url_md = f"[{source_url}]({source_url})" if source_url else "n/a"
    return (
        template_text.replace("## Company\n- ", f"## Company\n- {record.company or 'Unknown'}")
        .replace("## Role\n- ", f"## Role\n- {record.role or 'Unknown'}")
        .replace("## Source URL\n- ", f"## Source URL\n- {source_url_md}")
        .replace(
            "## Requirements (copied)\n- ",
            f"## Requirements (copied)\n- {record.notes or 'Copy key requirements from posting.'}",
        )
        .replace(
            "## Key signals to mirror in CV\n- ",
            f"## Key signals to mirror in CV\n- Match profile: {record.match_profile or 'de'}",
        )
        + f"\n\n## Metadata\n- Date found: {date_found}\n- Fit score: {record.fit_score}\n- Fit label: {record.fit or 'n/a'}\n"
    )


def _resolve_workspace_file_path(raw_path: str) -> Path:
    path = resolve_from_workspace_root(raw_path)
    root = applications_root()
    if not is_within_path(path, root):
        raise HTTPException(status_code=400, detail="Only files under applications/ are allowed")
    if path.suffix.lower() not in {".md", ".tex", ".txt", ".csv"}:
        raise HTTPException(status_code=400, detail="Unsupported file extension")
    return path


@router.post(
    "/applications/{application_id}/generate-documents",
    response_model=GenerateDocumentsResult,
    tags=["workspace", "applications"],
    summary="Generate tailored vacancy files for one application",
)
def generate_documents(
    application_id: int,
    payload: GenerateDocumentsRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
) -> GenerateDocumentsResult:
    record = db.query(JobApplication).filter(JobApplication.id == application_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="Application not found")

    template_dir = templates_root()
    if not template_dir.exists() or not template_dir.is_dir():
        raise HTTPException(status_code=500, detail=f"Template directory not found: {template_dir}")

    vacancy_template = template_dir / "vacancy.md"
    cover_letter_template = template_dir / "cover_letter.md"
    notes_template = template_dir / "notes.md"
    cv_template = base_cv_template_path()

    for required in [vacancy_template, cover_letter_template, notes_template, cv_template]:
        if not required.exists() or not required.is_file():
            raise HTTPException(status_code=500, detail=f"Required template file not found: {required}")

    target_dir = _build_docs_directory(record)
    target_dir.mkdir(parents=True, exist_ok=True)

    vacancy_path = target_dir / "vacancy.md"
    cover_letter_path = target_dir / "cover_letter.md"
    notes_path = target_dir / "notes.md"
    cv_path = target_dir / "cv.tex"

    if not payload.overwrite:
        existing_files = [p for p in [vacancy_path, cover_letter_path, notes_path, cv_path] if p.exists()]
        if existing_files:
            names = ", ".join(p.name for p in existing_files)
            raise HTTPException(status_code=409, detail=f"Target files already exist: {names}. Set overwrite=true.")

    vacancy_text = _render_vacancy_notes(vacancy_template.read_text(encoding="utf-8"), record)
    author_name = (
        (payload.author_name.strip() if payload.author_name else None)
        or (payload.your_name.strip() if payload.your_name else None)
        or (settings.generated_document_author.strip() if settings.generated_document_author else None)
        or "Author Name"
    )
    cover_letter_text = _render_cover_letter(
        cover_letter_template.read_text(encoding="utf-8"),
        record,
        author_name,
    )
    notes_text = notes_template.read_text(encoding="utf-8")
    cv_text = cv_template.read_text(encoding="utf-8")

    file_payloads = {
        vacancy_path: vacancy_text,
        cover_letter_path: cover_letter_text,
        notes_path: notes_text,
        cv_path: cv_text,
    }
    temp_paths: list[Path] = []
    backup_paths: dict[Path, Path] = {}

    for target, content in file_payloads.items():
        token = uuid4().hex
        temp_path = target.with_name(f".{target.name}.tmp-{token}")
        temp_path.write_text(content, encoding="utf-8")
        temp_paths.append(temp_path)

        if target.exists():
            backup_path = target.with_name(f".{target.name}.bak-{token}")
            shutil.copy2(target, backup_path)
            backup_paths[target] = backup_path

    workspace = workspace_root()
    try:
        for target, temp_path in zip(file_payloads.keys(), temp_paths):
            temp_path.replace(target)

        record.resume_ref = safe_relative_path(cv_path, workspace)
        record.cover_letter_ref = safe_relative_path(cover_letter_path, workspace)
        db.commit()
    except Exception as exc:
        db.rollback()
        for target in file_payloads:
            backup_path = backup_paths.get(target)
            if backup_path and backup_path.exists():
                backup_path.replace(target)
            elif target.exists():
                target.unlink()
        raise HTTPException(status_code=500, detail="Failed to generate documents") from exc
    finally:
        for temp_path in temp_paths:
            if temp_path.exists():  # pragma: no cover
                temp_path.unlink()
        for backup_path in backup_paths.values():
            if backup_path.exists():
                backup_path.unlink()

    return GenerateDocumentsResult(
        vacancy_dir=safe_relative_path(target_dir, workspace),
        vacancy_path=safe_relative_path(vacancy_path, workspace),
        cv_path=safe_relative_path(cv_path, workspace),
        cover_letter_path=safe_relative_path(cover_letter_path, workspace),
        notes_path=safe_relative_path(notes_path, workspace),
    )


@router.get(
    "/workspace-file",
    response_model=WorkspaceFileReadResult,
    summary="Read one editable file under applications/",
)
def read_workspace_file(
    path: str = Query(..., min_length=1),
    _: None = Depends(require_write_access),
) -> WorkspaceFileReadResult:
    target = _resolve_workspace_file_path(path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return WorkspaceFileReadResult(
        path=safe_relative_path(target, workspace_root()), content=target.read_text(encoding="utf-8")
    )


@router.put(
    "/workspace-file",
    response_model=WorkspaceFileReadResult,
    summary="Write one editable file under applications/",
)
def write_workspace_file(
    payload: WorkspaceFileWriteRequest,
    _: None = Depends(require_write_access),
) -> WorkspaceFileReadResult:
    target = _resolve_workspace_file_path(payload.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload.content, encoding="utf-8")
    return WorkspaceFileReadResult(path=safe_relative_path(target, workspace_root()), content=payload.content)
