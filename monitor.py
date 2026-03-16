"""
Backward-compatible wrapper.

This repository now has two separate monitors:
- bachtrack_monitor.py (Bachtrack listeners, incl. Sibelius)
- gmail_monitor.py (IMAP / Gmail subject keyword)

This file keeps the old entrypoint working by running both.
"""

from gmail_monitor import main as gmail_main
from bachtrack_monitor import main as bachtrack_main


def main() -> None:
    bachtrack_main()
    gmail_main()


if __name__ == "__main__":
    main()