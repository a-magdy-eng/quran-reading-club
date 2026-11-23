"""Entry point for the desktop launcher (used by PyInstaller and for development)."""
import sys

from app.launcher import main

if __name__ == "__main__":
    sys.exit(main())
