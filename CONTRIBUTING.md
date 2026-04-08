# Contributing to Tack

Thanks for considering a contribution. Here's how to get involved.

## Quick Setup

```bash
git clone https://github.com/Tackworks/tack.git
cd tack
pip install fastapi uvicorn
python server.py
```

Open `http://localhost:8795` and you're running.

## How to Contribute

1. **Check existing issues** before opening a new one.
2. **Fork and branch.** Create a feature branch from `main`.
3. **Keep it small.** One feature or fix per PR. Easier to review, easier to merge.
4. **Test your changes.** Start the server, click around, hit the API. Make sure nothing broke.
5. **Open a PR** with a clear description of what changed and why.

## What We're Looking For

- Bug fixes
- Performance improvements
- New agent framework integration guides
- UI improvements
- Documentation improvements

## What We're NOT Looking For

- External dependencies (we stay single-file + FastAPI + Uvicorn)
- Database migrations away from SQLite
- Authentication/authorization systems (use a reverse proxy)
- Breaking API changes

## Code Style

- Single file (`server.py`) is intentional. Don't split it.
- Standard library over third-party when possible.
- Keep it readable. If a function needs a comment to explain, simplify the function.

## Questions?

Open an issue or email tackworks@proton.me.
