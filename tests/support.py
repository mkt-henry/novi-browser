"""Temporary homes inherit Windows ACLs, including restricted execution tokens."""
import os
import shutil
import tempfile
import uuid
from pathlib import Path

# Unit tests never ask GitHub for a newer version.
os.environ.setdefault('NOVI_BROWSER_NO_UPDATE_CHECK', '1')
# ...and never write into the developer's real agent folders.
os.environ.setdefault('NOVI_BROWSER_NO_GUIDE_INSTALL', '1')


class TemporaryDirectory:
    def __init__(self):
        self.name = str(Path(tempfile.gettempdir()) / ('novi-test-' + uuid.uuid4().hex))
        Path(self.name).mkdir(mode=0o777 if os.name == 'nt' else 0o700)

    def cleanup(self):
        shutil.rmtree(self.name)

    def __enter__(self):
        return self.name

    def __exit__(self, *args):
        self.cleanup()
