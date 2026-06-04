"""Session/config persistence.

Config lives at $XDG_CONFIG_HOME/openlibing-cli/config.json (default
~/.config/openlibing-cli/config.json) with mode 0600. The ticket is
treated as a secret — file is chmod'd after write.
"""

import json
import os
from pathlib import Path


def default_config_path():
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "openlibing-cli" / "config.json"


class Config:
    def __init__(self, path=None):
        self.path = Path(path) if path else default_config_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data = {}
        self._load()

    # -- io ---------------------------------------------------------------

    def _load(self):
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text())
            except json.JSONDecodeError:
                self._data = {}
        self._data.setdefault("env", "prod")

    def save(self):
        self.path.write_text(json.dumps(self._data, indent=2))
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    # -- dict-like --------------------------------------------------------

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value
        self.save()

    def unset(self, key):
        self._data.pop(key, None)
        self.save()

    def to_dict(self):
        return dict(self._data)
