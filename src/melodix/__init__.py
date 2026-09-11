"""Melodix — btop-style terminal music player for Linux."""
import logging

__version__ = "1.0.0"

# Library best practice: don't configure logging, but stay quiet by default.
logging.getLogger(__name__).addHandler(logging.NullHandler())
