param(
    [string]$Host = "127.0.0.1",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

Push-Location $PSScriptRoot
try {
    & python -m uvicorn backend.app.main:app `
        --host $Host `
        --port $Port `
        --reload `
        --reload-include "*.py" `
        --reload-include "*.md" `
        --reload-include "*.tex" `
        --reload-include ".env"
}
finally {
    Pop-Location
}
