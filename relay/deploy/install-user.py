#!/usr/bin/env python3
"""Install an immutable committed release. Never start/restart a service here."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

repo = Path(__file__).resolve().parents[1]

def git(*args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()

# Relay may live at a repo root or in a subdirectory (e.g. relay/ in the public
# osslab-manager repo); only this directory's committed tree is installed.
prefix = git('rev-parse', '--show-prefix')
if git('status', '--porcelain', '--', '.'):
    sys.exit('Refusing to install an uncommitted worktree; review and commit first.')
revision = git('rev-parse', 'HEAD')
home = Path.home()
root = home / '.local/share/osslab-relay'
release = root / 'releases' / revision
current = root / 'current'
launcher = home / '.local/bin/osrelay'
unit = home / '.config/systemd/user/osrelay.service'
# Never replace unrelated files or an existing service definition.
for path, expected in ((launcher, current / 'bin/osrelay'),):
    if os.path.lexists(path) and (not path.is_symlink() or path.readlink() != expected):
        sys.exit(f'Refusing to replace unrelated path: {path}')
if os.path.lexists(current) and (not current.is_symlink() or not current.resolve().is_relative_to(root / 'releases')):
    sys.exit(f'Refusing to replace unrelated path: {current}')
unit_source = repo / 'deploy/osrelay.service'
if unit.exists() and unit.read_bytes() != unit_source.read_bytes():
    sys.exit(f'Service differs: review/back up {unit} before upgrading it.')
# git archive exports committed files only, including file modes, into an
# exclusive directory. A partial interrupted export is never selected current.
if not release.exists():
    release.parent.mkdir(parents=True, exist_ok=True)
    staging = release.with_name(revision + '.installing-' + str(os.getpid()))
    staging.mkdir()
    tree = f'{revision}:{prefix}' if prefix else revision
    # <rev>:<prefix> resolves from the top level, so archive from there.
    top = git('rev-parse', '--show-toplevel')
    archive = subprocess.Popen(['git', '-C', top, 'archive', tree], stdout=subprocess.PIPE)
    unpack = subprocess.run(['tar', '-x', '-C', str(staging)], stdin=archive.stdout)
    archive.stdout.close()
    if archive.wait() or unpack.returncode:
        sys.exit(f'Export failed; inspect {staging}')
    staging.rename(release)
launcher.parent.mkdir(parents=True, exist_ok=True)
unit.parent.mkdir(parents=True, exist_ok=True)
if not launcher.is_symlink():
    launcher.symlink_to(current / 'bin/osrelay')
if not unit.exists():
    shutil.copyfile(unit_source, unit)
new_link = root / ('current-' + str(os.getpid()))
new_link.symlink_to(release)
os.replace(new_link, current)
print(f'Installed {revision}. Service unchanged; after checking no active attempts:')
print('systemctl --user daemon-reload')
print('systemctl --user enable --now osrelay.service')
print('For upgrades, gracefully restart osrelay.service after the old runner drains.')
