"""
Application configuration management for IronSight.

Handles settings storage, API key management, and device preferences.
Settings are persisted to ~/.ironsight/config.json.
"""

import json
import os
from pathlib import Path
from typing import Optional


class Config:
    """Manages application settings with JSON file persistence."""

    _APP_DIR = Path.home() / ".ironsight"
    _CONFIG_FILE = _APP_DIR / "config.json"
    _CLIPS_DIR = _APP_DIR / "clips"
    _DB_PATH = _APP_DIR / "ironsight.db"

    _defaults = {
        "camera_index": 0,
        "camera_fps": 30,
        "camera_resolution": [1280, 720],
        "clip_pre_seconds": 2.0,    # seconds before impact in clip
        "clip_post_seconds": 2.0,   # seconds after impact in clip
        "device_mode": "auto",      # "auto", "usb", "mock"
        "mock_preset": "consistent_player",
        "anthropic_api_key": "",
        "auto_analyze_shots": False,
        "auto_analyze_interval": 5,  # analyze every Nth shot
        "ui_theme": "dark",
        "show_dispersion": True,
        "show_trajectory_trails": True,
        "max_trail_shots": 20,
    }

    _instance: Optional["Config"] = None
    _settings: dict

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._settings = {}
            cls._instance._load()
        return cls._instance

    def _load(self):
        """Load settings from disk, merging with defaults."""
        self._APP_DIR.mkdir(parents=True, exist_ok=True)
        self._CLIPS_DIR.mkdir(parents=True, exist_ok=True)

        if self._CONFIG_FILE.exists():
            try:
                with open(self._CONFIG_FILE) as f:
                    saved = json.load(f)
                # Merge: defaults first, then saved values override
                self._settings = {**self._defaults, **saved}
            except (json.JSONDecodeError, IOError):
                self._settings = dict(self._defaults)
        else:
            self._settings = dict(self._defaults)

    def save(self):
        """Persist current settings to disk."""
        self._APP_DIR.mkdir(parents=True, exist_ok=True)
        with open(self._CONFIG_FILE, "w") as f:
            json.dump(self._settings, f, indent=2)

    def get(self, key: str, default=None):
        """Get a setting value."""
        return self._settings.get(key, default)

    def set(self, key: str, value):
        """Set a setting value and save."""
        self._settings[key] = value
        self.save()

    @classmethod
    def get_api_key(cls) -> str:
        """Get Anthropic API key from config or environment."""
        instance = cls()
        # Environment variable takes priority
        env_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if env_key:
            return env_key
        return instance.get("anthropic_api_key", "")

    @classmethod
    def get_clips_dir(cls) -> Path:
        """Get the directory for saving video clips."""
        instance = cls()
        instance._CLIPS_DIR.mkdir(parents=True, exist_ok=True)
        return instance._CLIPS_DIR

    @classmethod
    def get_db_path(cls) -> Path:
        """Get the SQLite database file path."""
        instance = cls()
        instance._APP_DIR.mkdir(parents=True, exist_ok=True)
        return instance._DB_PATH

    @classmethod
    def get_app_dir(cls) -> Path:
        """Get the application data directory."""
        instance = cls()
        instance._APP_DIR.mkdir(parents=True, exist_ok=True)
        return instance._APP_DIR
