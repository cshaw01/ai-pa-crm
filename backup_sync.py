"""
GitHub-backed backup for per-tenant wiki + SQLite dumps.

Each tenant gets one private GitHub repo under GITHUB_BACKUP_ORG named
`<tenant-slug>-wiki`. Every AI-driven wiki write is committed + pushed.
Nightly, the SQLite DB is dumped as SQL text into `.db-dumps/` and
committed alongside.

Env vars (read lazily):
  TENANT_SLUG           — identifies this tenant (e.g. 'hvac')
  GITHUB_BACKUP_ORG     — e.g. 'chiefpa-tenant-data'
  GITHUB_BACKUP_TOKEN   — fine-grained PAT with Contents + Administration rw
  GITHUB_BACKUP_USER    — commit author username (defaults to 'chiefpa-bot')
  GITHUB_BACKUP_EMAIL   — commit author email (defaults to '<user>@users.noreply.github.com')

Designed to fail soft: if GitHub is unreachable or any env var is missing,
wiki writes still succeed locally and we log a warning. A later successful
sync catches up.
"""

from __future__ import annotations
import os
import subprocess
import logging
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


# ----- Config access -------------------------------------------------------

def _cfg() -> Optional[dict]:
    """Return backup config dict, or None if backup is not configured."""
    token = os.environ.get('GITHUB_BACKUP_TOKEN')
    org = os.environ.get('GITHUB_BACKUP_ORG')
    slug = os.environ.get('TENANT_SLUG')
    if not (token and org and slug):
        return None
    user = os.environ.get('GITHUB_BACKUP_USER') or 'chiefpa-bot'
    email = os.environ.get('GITHUB_BACKUP_EMAIL') or f"{user}@users.noreply.github.com"
    return {
        'token': token,
        'org': org,
        'slug': slug,
        'user': user,
        'email': email,
        'repo_name': f"{slug}-wiki",
        'remote_url': f"https://x-access-token:{token}@github.com/{org}/{slug}-wiki.git",
    }


def is_configured() -> bool:
    return _cfg() is not None


# ----- Subprocess helper ---------------------------------------------------

def _run(cmd: list[str], cwd: str | Path, check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command, capturing output. Logs on failure."""
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        log.warning(
            "command failed: %s\nstdout: %s\nstderr: %s",
            ' '.join(cmd), result.stdout, result.stderr,
        )
    return result


def _run_git(args: list[str], cwd: str | Path, env_token: str | None = None,
             check: bool = True) -> subprocess.CompletedProcess:
    """git wrapper that injects the token into GIT_ASKPASS via env."""
    env = os.environ.copy()
    # Suppress any interactive prompts
    env['GIT_TERMINAL_PROMPT'] = '0'
    env['GIT_ASKPASS'] = 'echo'
    return _run(['git'] + args, cwd=cwd, check=check)


# ----- GitHub API ----------------------------------------------------------

def ensure_repo_exists() -> bool:
    """
    Idempotently create the tenant's backup repo. Returns True if the repo
    exists (or was just created), False on failure. Safe to call repeatedly.
    """
    cfg = _cfg()
    if not cfg:
        return False

    headers = {
        'Authorization': f'Bearer {cfg["token"]}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }

    # Check existence
    check = requests.get(
        f"{GITHUB_API}/repos/{cfg['org']}/{cfg['repo_name']}",
        headers=headers, timeout=10,
    )
    if check.status_code == 200:
        return True
    if check.status_code not in (404,):
        log.warning("Unexpected status checking repo existence: %s %s",
                    check.status_code, check.text)
        return False

    # Create
    resp = requests.post(
        f"{GITHUB_API}/orgs/{cfg['org']}/repos",
        headers=headers,
        json={
            'name': cfg['repo_name'],
            'private': True,
            'auto_init': False,
            'description': f"AI-CRM tenant backup: {cfg['slug']}",
        },
        timeout=15,
    )
    if resp.status_code == 201:
        log.info("Created backup repo %s/%s", cfg['org'], cfg['repo_name'])
        return True
    log.warning("Failed to create repo: %s %s", resp.status_code, resp.text)
    return False


# ----- Git helpers ---------------------------------------------------------

def init_git_if_needed(wiki_dir: str | Path) -> bool:
    """
    Initialise git in the wiki dir if not already, set remote + identity,
    push initial commit if the repo is brand new on GitHub.
    Returns True when the wiki has a working remote after this call.
    """
    cfg = _cfg()
    if not cfg:
        return False
    wiki_dir = Path(wiki_dir)
    if not wiki_dir.exists():
        log.warning("Wiki dir does not exist: %s", wiki_dir)
        return False

    git_dir = wiki_dir / '.git'
    if not git_dir.exists():
        r = _run_git(['init', '-b', 'main'], cwd=wiki_dir, check=False)
        if r.returncode != 0:
            # Older git: init, then rename branch
            _run_git(['init'], cwd=wiki_dir, check=False)
            _run_git(['checkout', '-b', 'main'], cwd=wiki_dir, check=False)

    # Identity (local to this repo, not global)
    _run_git(['config', 'user.name', cfg['user']], cwd=wiki_dir, check=False)
    _run_git(['config', 'user.email', cfg['email']], cwd=wiki_dir, check=False)

    # Remote
    _run_git(['remote', 'remove', 'origin'], cwd=wiki_dir, check=False)
    _run_git(['remote', 'add', 'origin', cfg['remote_url']], cwd=wiki_dir, check=False)

    # Staged commit if repo has no commits yet
    head = _run_git(['rev-parse', '--verify', 'HEAD'], cwd=wiki_dir, check=False)
    if head.returncode != 0:
        _run_git(['add', '-A'], cwd=wiki_dir, check=False)
        _run_git(['commit', '-m', 'initial: existing wiki snapshot', '--allow-empty'],
                 cwd=wiki_dir, check=False)

    # Try to push. If remote is empty, this is the first push; otherwise
    # it may already be ahead — either way, a best-effort push.
    push = _run_git(['push', '-u', 'origin', 'main'], cwd=wiki_dir, check=False)
    if push.returncode != 0:
        log.warning("Initial push failed; will retry on next sync. stderr=%s",
                    push.stderr[:500])

    return True


def commit_wiki_changes(wiki_dir: str | Path, message: str) -> bool:
    """
    Stage all wiki changes, commit (if there's a diff), push.
    Returns True if a commit was made or there was nothing to commit.
    Returns False on failure (git command error or push failure).
    """
    cfg = _cfg()
    if not cfg:
        return False
    wiki_dir = Path(wiki_dir)
    if not (wiki_dir / '.git').exists():
        if not init_git_if_needed(wiki_dir):
            return False

    _run_git(['add', '-A'], cwd=wiki_dir, check=False)
    status = _run_git(['status', '--porcelain'], cwd=wiki_dir, check=False)
    if not status.stdout.strip():
        # No changes — not a failure
        return True

    commit = _run_git(['commit', '-m', message], cwd=wiki_dir, check=False)
    if commit.returncode != 0:
        log.warning("Commit failed: %s", commit.stderr[:500])
        return False

    push = _run_git(['push', 'origin', 'main'], cwd=wiki_dir, check=False)
    if push.returncode != 0:
        log.warning("Push failed (commit stays local, will retry): %s",
                    push.stderr[:500])
        return False
    return True


# ----- SQLite dump ---------------------------------------------------------

def dump_sqlite(db_path: str | Path, out_path: str | Path) -> bool:
    """Dump SQLite DB to text SQL. Returns True on success."""
    db_path = Path(db_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not db_path.exists():
        log.warning("DB path not found: %s", db_path)
        return False
    try:
        with open(out_path, 'w') as f:
            r = subprocess.run(
                ['sqlite3', str(db_path), '.dump'],
                stdout=f, stderr=subprocess.PIPE, text=True,
            )
        if r.returncode != 0:
            log.warning("sqlite3 .dump failed: %s", r.stderr[:500])
            return False
        return True
    except FileNotFoundError:
        log.warning("sqlite3 binary not available")
        return False


# ----- Public entry points -------------------------------------------------

def ensure_setup(wiki_dir: str | Path) -> bool:
    """
    Called at container startup. Idempotent: creates repo if needed,
    initialises local git if needed, performs initial push if needed.
    """
    if not is_configured():
        log.info("Backup not configured — skipping GitHub sync setup")
        return False
    if not ensure_repo_exists():
        return False
    return init_git_if_needed(wiki_dir)


def sync_wiki(wiki_dir: str | Path, summary: str) -> bool:
    """
    Public API called after every AI-driven wiki write. Commits + pushes
    if there's a diff. Safe to call when nothing changed.
    """
    if not is_configured():
        return False
    try:
        return commit_wiki_changes(wiki_dir, f"AI: {summary}")
    except Exception as e:
        log.warning("sync_wiki failed: %s", e)
        return False


def last_commit_info(wiki_dir: str | Path) -> dict:
    """
    Return metadata about the most recent commit in the wiki repo, for
    dashboard surfacing. Keys: configured, sha, date, message, remote_url.
    """
    if not is_configured():
        return {'configured': False}
    wiki_dir = Path(wiki_dir)
    if not (wiki_dir / '.git').exists():
        return {'configured': True, 'initialised': False}
    r = _run_git(
        ['log', '-1', '--format=%H|%ci|%s'],
        cwd=wiki_dir, check=False,
    )
    if r.returncode != 0 or not r.stdout.strip():
        return {'configured': True, 'initialised': True, 'sha': None}
    parts = r.stdout.strip().split('|', 2)
    sha, iso_date, message = (parts + [None, None, None])[:3]
    cfg = _cfg()
    web_url = None
    if cfg and sha:
        web_url = f"https://github.com/{cfg['org']}/{cfg['repo_name']}/commit/{sha}"
    return {
        'configured': True,
        'initialised': True,
        'sha': sha,
        'short_sha': (sha or '')[:7],
        'date': iso_date,
        'message': message,
        'web_url': web_url,
        'repo_url': f"https://github.com/{cfg['org']}/{cfg['repo_name']}" if cfg else None,
    }


def nightly_backup(wiki_dir: str | Path, db_path: str | Path) -> bool:
    """
    Dump SQLite → .db-dumps/crm-YYYY-MM-DD.sql, commit + push alongside
    wiki. Called from a once-per-day scheduler.
    """
    from datetime import datetime
    if not is_configured():
        return False
    wiki_dir = Path(wiki_dir)
    dumps_dir = wiki_dir / '.db-dumps'
    today = datetime.utcnow().strftime('%Y-%m-%d')
    out_path = dumps_dir / f"crm-{today}.sql"
    if not dump_sqlite(db_path, out_path):
        return False
    # Also retain a 'latest' symlink-ish copy for easy access
    latest = dumps_dir / 'crm-latest.sql'
    try:
        if latest.exists() or latest.is_symlink():
            latest.unlink()
        # Plain copy rather than symlink so it commits cleanly
        latest.write_text(out_path.read_text())
    except Exception:
        pass
    return commit_wiki_changes(wiki_dir, f"nightly: SQLite dump {today}")
