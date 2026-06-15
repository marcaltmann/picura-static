#!/usr/bin/env bash
#
# Build the site and publish dist/ to the gh-pages branch as a single
# throwaway commit. The publish happens from a disposable git repo inside
# dist/, force-pushed each time, so:
#   - image binaries never accumulate in main's history (main stays text-only)
#   - gh-pages has no history to bloat (one orphan commit, replaced every deploy)
#
# Requires a configured git remote (default: origin) pointing at the GitHub
# repo, with Pages set to serve from the gh-pages branch.
#
# Env overrides:
#   DEPLOY_BRANCH  target branch   (default: gh-pages)
#   DEPLOY_REMOTE  git remote name (default: origin)
#   DEPLOY_URL     push URL        (default: the remote's URL)

set -euo pipefail

BRANCH="${DEPLOY_BRANCH:-gh-pages}"
REMOTE="${DEPLOY_REMOTE:-origin}"

repo_root="$(git rev-parse --show-toplevel)"
url="${DEPLOY_URL:-$(git -C "$repo_root" remote get-url "$REMOTE")}"

# Fresh build into dist/.
cd "$repo_root"
uv run python build.py

cd dist
# Skip Jekyll processing on GitHub Pages (serve files as-is).
touch .nojekyll

# Publish from a throwaway repo so main's index and branches are untouched.
rm -rf .git
git init -q
git add -A
git -c user.name='picura-static deploy' -c user.email='deploy@localhost' \
    commit -q -m "Deploy $(date -u +%Y-%m-%dT%H:%M:%SZ)"
git push -q --force "$url" "HEAD:$BRANCH"
rm -rf .git

echo "Deployed dist/ → ${REMOTE}/${BRANCH}"
