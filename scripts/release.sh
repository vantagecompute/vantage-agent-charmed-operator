#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'USAGE'
Usage: scripts/release.sh <version>

Bumps pyproject.toml, commits the release, tags v<version>, and pushes the
commit and tag. Pushing the tag triggers the Charmhub publishing workflow.

Example:
  just release 0.1.0
USAGE
}

if [[ $# -ne 1 || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 1
fi

version="${1#v}"
tag="v${version}"

if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]]; then
    echo "ERROR: version must look like 1.2.3, optionally with a suffix" >&2
    exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
    echo "ERROR: working tree must be clean before releasing" >&2
    git status --short >&2
    exit 1
fi

if git rev-parse "$tag" >/dev/null 2>&1; then
    echo "ERROR: tag already exists: $tag" >&2
    exit 1
fi

sed -i -E "s/^version = \".*\"/version = \"${version}\"/" pyproject.toml

uv lock

git add pyproject.toml uv.lock
git commit -m "release: vantage-agent ${version}"
git tag -a "$tag" -m "vantage-agent ${version}"
git push origin HEAD "$tag"

echo "Released ${tag}. The Charmhub publish workflow will run from the pushed tag."
