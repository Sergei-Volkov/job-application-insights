from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database connection string.
    database_url: str = "sqlite:///./app.db"

    # Fallback skill list used when notes contain no gap markers.
    default_missing_skills: str = ""

    # Allowed CORS origins.
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    cors_allow_credentials: bool = False

    # Optional API key for write and execute endpoints.
    write_api_key: str = ""

    # Require X-API-Key for write and execute endpoints.
    require_write_key: bool = False

    # Default author for generated documents.
    generated_document_author: str = ""

    # Discovery script settings.
    discovery_script_path: str = "discovery/cli.py"
    discovery_cv_path: str = ""
    discovery_api_base_url: str = "http://127.0.0.1:8000"
    discovery_log_max_chars: int = 3000
    discovery_default_profile: str = "de"
    discovery_runner_mode: str = "module"

    # Workspace-relative path root used by document generation and file editing.
    applications_root: str = "applications"

    # Relative paths under applications_root (or absolute paths when needed).
    vacancies_template_dir: str = "vacancies/_template"
    base_cv_template_path: str = "resumes/CV.tex"

    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
