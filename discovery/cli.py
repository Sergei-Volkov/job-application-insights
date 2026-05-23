from job_discovery_engine.cli import main  # noqa: E402

# Thin wrapper kept for backward compatibility with existing local scripts.
# Canonical discovery implementation lives in the external job_discovery_engine package.

if __name__ == "__main__":
    raise SystemExit(main())
