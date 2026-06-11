set shell := ["bash", "-euo", "pipefail", "-c"]

uv_run := "uv run --frozen"

default:
    @just --list

# Pack the charm locally.
pack:
    charmcraft pack --use-lxd

# Regenerate uv.lock.
lock:
    uv lock

# Install the charm Python environment.
env: lock
    uv sync --extra dev

# Run unit tests.
test:
    {{uv_run}} --extra dev pytest tests -q

# Bump pyproject.toml, commit, tag, and push the publishing tag.
release version:
    ./scripts/release.sh {{version}}

# Show the charm version currently recorded in pyproject.toml.
version:
    @sed -n 's/^version = "\([^"]*\)".*/\1/p' pyproject.toml
