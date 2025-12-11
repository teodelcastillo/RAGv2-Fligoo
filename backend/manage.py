#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
from pathlib import Path

# Try to load .env file if it exists (for local development)
# This is optional and won't fail if python-dotenv is not installed
try:
    from dotenv import load_dotenv
    # Look for .env in the backend directory or parent directory
    base_dir = Path(__file__).resolve().parent
    env_file = base_dir / '.env'
    if not env_file.exists():
        env_file = base_dir.parent / '.env'
    if env_file.exists():
        load_dotenv(env_file)
except ImportError:
    # python-dotenv not installed, skip .env loading
    # Environment variables should be set manually or via system
    pass


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'main.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
