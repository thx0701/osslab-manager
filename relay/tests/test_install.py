"""Exercise immutable installation in a disposable home and Git checkout."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='relay-install-')
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.home = self.root / 'home'
        self.home.mkdir()
        shutil.copytree(ROOT, self.repo, ignore=shutil.ignore_patterns('.git', '__pycache__', '*.egg-info'))
        self.git('init', '-q')
        self.git('add', '.')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture')

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], text=True).strip()

    def install(self):
        return subprocess.run([sys.executable, str(self.repo / 'deploy/install-user.py')],
                              env={**os.environ, 'HOME': str(self.home)}, capture_output=True, text=True)

    def test_clean_release_is_fixed_and_install_is_idempotent(self):
        revision = self.git('rev-parse', 'HEAD')
        first = self.install()
        self.assertEqual(first.returncode, 0, first.stderr)
        current = self.home / '.local/share/osslab-relay/current'
        self.assertEqual(current.resolve().name, revision)
        second = self.install()
        self.assertEqual(second.returncode, 0, second.stderr)
        (self.repo / 'osrelay/cli.py').write_text('raise Exception("checkout changed")\n')
        run = subprocess.run([str(self.home / '.local/bin/osrelay'), '--help'], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('Durable local', run.stdout)
        self.assertNotEqual(self.install().returncode, 0)
        self.assertEqual(current.resolve().name, revision)

    def test_installs_from_a_subdirectory_of_a_larger_repo(self):
        # The public osslab-manager repo carries Relay under relay/.
        mono = self.root / 'mono'
        (mono / 'docs').mkdir(parents=True)
        (mono / 'SKILL.md').write_text('skill\n')
        shutil.copytree(ROOT, mono / 'relay', ignore=shutil.ignore_patterns('.git', '__pycache__', '*.egg-info'))
        run = lambda *a: subprocess.check_output(['git', '-C', str(mono), *a], text=True).strip()
        run('init', '-q'); run('add', '.')
        run('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'mono')
        result = subprocess.run([sys.executable, str(mono / 'relay/deploy/install-user.py')],
                                env={**os.environ, 'HOME': str(self.home)}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        release = (self.home / '.local/share/osslab-relay/current').resolve()
        self.assertEqual(release.name, run('rev-parse', 'HEAD'))
        self.assertTrue((release / 'bin/osrelay').is_file())
        self.assertFalse((release / 'SKILL.md').exists())
        help_run = subprocess.run([str(self.home / '.local/bin/osrelay'), '--help'], capture_output=True, text=True)
        self.assertEqual(help_run.returncode, 0, help_run.stderr)
        # Uncommitted changes outside relay/ do not block; inside relay/ they do.
        (mono / 'SKILL.md').write_text('edited\n')
        self.assertEqual(subprocess.run([sys.executable, str(mono / 'relay/deploy/install-user.py')],
                                        env={**os.environ, 'HOME': str(self.home)}, capture_output=True).returncode, 0)
        (mono / 'relay/README.md').write_text('edited\n')
        self.assertNotEqual(subprocess.run([sys.executable, str(mono / 'relay/deploy/install-user.py')],
                                           env={**os.environ, 'HOME': str(self.home)}, capture_output=True).returncode, 0)

    def test_unrelated_launcher_is_preserved(self):
        launcher = self.home / '.local/bin/osrelay'
        launcher.parent.mkdir(parents=True)
        launcher.write_text('unrelated\n')
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(launcher.read_text(), 'unrelated\n')
        self.assertFalse((self.home / '.local/share/osslab-relay/current').exists())

    def test_different_service_is_preserved(self):
        unit = self.home / '.config/systemd/user/osrelay.service'
        unit.parent.mkdir(parents=True)
        unit.write_text('unrelated\n')
        self.assertNotEqual(self.install().returncode, 0)
        self.assertEqual(unit.read_text(), 'unrelated\n')


if __name__ == '__main__':
    unittest.main()
