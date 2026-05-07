from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database — override via DATABASE_URL env var.
    # Use absolute path format for non-SQLite, e.g.:
    #   postgresql+psycopg2://user:pass@host/db
    database_url: str = "sqlite:///./app.db"

    # Path to the tracker CSV that seeds the DB on first startup.
    csv_path: str = "data/job_applications_sample.csv"

    # Comma-separated fallback skill list shown when notes contain no gap markers.
    default_missing_skills: str = "Kubernetes,Redis,GraphQL,Cypress,Terraform,CI/CD"

    # Comma-separated allowed CORS origins.
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    cors_allow_credentials: bool = False

    # Optional API key for write/execute endpoints.
    # When empty, write endpoints remain open (convenient for local development).
    write_api_key: str = ""

    # Discovery integration: path to the existing finder script and CV file.
    discovery_script_path: str = "discovery/job_finder.py"
    # CV path has no default — set DISCOVERY_CV_PATH in your .env or environment.
    discovery_cv_path: str = ""
    discovery_api_base_url: str = "http://127.0.0.1:8000"
    discovery_log_max_chars: int = 3000

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, v: object) -> object:
        # Allow passing origins as a comma-separated string via env var:
        # CORS_ORIGINS="http://localhost:3000,https://myapp.example.com"
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
