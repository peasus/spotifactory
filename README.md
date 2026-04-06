# spotifactory

A Python project scaffold for Spotifactory.

## Quick start

- Create a virtual env: `python -m venv .venv`
- Activate it: `source .venv/bin/activate`
- Install editable package: `pip install -e .`
- Run tests: `pytest`

## GUI & platform-specific dependencies

This project includes both a simple simulated GUI (uses `tkinter`) and code that runs on Raspberry Pi hardware (uses Adafruit libraries).

- tkinter: This is part of the Python standard library (the Tk/Tcl GUI binding) and is generally not installed via pip. If your Python build includes tkinter you can use the simulator; otherwise install the platform package:
	- Debian/Ubuntu: `sudo apt install python3-tk`
	- Fedora: `sudo dnf install python3-tkinter`
	- macOS: install a Python that includes Tcl/Tk or use Homebrew to install `tcl-tk` and ensure your Python is built/linked against it.
	- Windows: Python from python.org usually includes tkinter; if missing reinstall Python with Tcl/Tk support.

- Pillow: the project uses Pillow for image handling. Install the GUI extras to ensure Pillow is available:

	```bash
	pip install .[gui]
	# or, directly
	pip install Pillow
	```

- Raspberry Pi / hardware extras: components that talk to GPIO and the SSD1306 OLED are optional and grouped under the `rpi` extras. To install them:

	```bash
	pip install .[rpi]
	# or
	pip install Adafruit-Blinka adafruit-circuitpython-ssd1306
	```

Note: extras are optional to keep the package install lightweight on non-RPi systems.

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
