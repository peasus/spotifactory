# spotifactory

A Python project scaffold for Spotifactory.

## Quick start

- Create a virtual env: `python -m venv .venv`
- Activate it: `source .venv/bin/activate`
- Install editable package: `pip install -e .`
- Run tests: `pytest`

## GitHub

To create a GitHub repo and push, either use the `gh` CLI or create a new repo on github.com and add the remote:

Using `gh` (if installed and authenticated):

```
cd spotifactory
gh repo create yourusername/spotifactory --public --source=. --remote=origin --push
```

Or manually:

```
git remote add origin https://github.com/<your-username>/spotifactory.git
git push -u origin main
```
