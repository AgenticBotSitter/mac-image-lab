"""Test process defaults; production configuration is exercised explicitly."""
import os

os.environ.setdefault("MAC_IMAGE_LAB_ENV", "test")
