"""
Backward-compatible wrapper.

This repository now has two separate monitors:
- sibelius_monitor.py (Bachtrack / Sibelius events)
- gmail_monitor.py (IMAP / Gmail subject keyword)

This file keeps the old entrypoint working by running both.
"""

from gmail_monitor import main as gmail_main
from sibelius_monitor import main as sibelius_main


def main() -> None:
    sibelius_main()
    gmail_main()


if __name__ == "__main__":
    main()