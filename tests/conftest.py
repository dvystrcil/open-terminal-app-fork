import os

# open_terminal.env reads the key once, at first import, and open_terminal.main
# refuses to load without one. Set it before any test module is collected.
os.environ.setdefault("OPEN_TERMINAL_API_KEY", "test-key")
