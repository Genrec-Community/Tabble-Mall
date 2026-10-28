"""Present so that `pytest` can import `print_agent` without an install step.

pytest prepends the directory holding the topmost `conftest.py` to `sys.path`, and this
file sitting at the root is what puts `print-agent/` there -- so the suite runs from a
clean checkout with nothing but `pytest` and `websockets` available. The alternative,
`pip install -e .`, is a step that would only ever be forgotten once.

Empty of fixtures on purpose. There is no database, no event loop to share and no
server to start: every fixture these tests need is local to the file that uses it, and
a shared one here would be a thing to look up while reading a test that did not
mention it.
"""
