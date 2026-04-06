# Spotifactory Copilot Instructions

## Project Overview
Spotifactory is a Python project that provides a menu system with dual rendering backends: a simulated GUI (tkinter) for development and an actual OLED display driver for Raspberry Pi hardware. The codebase bridges desktop development with embedded systems.

## Architecture

### Core Components
- **Menu System** ([src/spotifactory/menu/menu.py](src/spotifactory/menu/menu.py)): Abstract menu model with `Menu` and `MenuItem` classes supporting nested menus, callbacks, and scroll handling.
- **Display Renderers**: Pluggable renderer pattern with two implementations:
  - `DisplaySim` ([src/spotifactory/menu/renderer_sim.py](src/spotifactory/menu/renderer_sim.py)): tkinter-based simulator for development
  - `DisplayOLED` ([src/spotifactory/menu/renderer_oled.py](src/spotifactory/menu/renderer_oled.py)): Real SSD1306 hardware driver via Adafruit libraries
- **Input System** ([src/spotifactory/menu/input_buttons.py](src/spotifactory/menu/input_buttons.py)): GPIO-based button input (RPi only) mapping board pins to actions (Up/Down/Back/Select)
- **Simulated Menu** ([src/spotifactory/menu/simulated_menu.py](src/spotifactory/menu/simulated_menu.py)): Full integration example demonstrating menu + display + key bindings

### Data Flow
1. User input → Button handler → Menu state changes (move_up/move_down/select)
2. Menu state → Renderer (display.draw_text with selected flag)
3. Renderer updates display (canvas.update or display.show)

## Key Conventions & Patterns

### Menu Structure Pattern
- Menus are immutable after creation (items list doesn't change)
- Navigation via `move_up()`, `move_down()`, `select()`, `go_back()`
- `select()` returns the next menu (for submenus) or None (callbacks only)
- Scrolling is automatic with `scroll_offset` tracking for large menus

### Renderer Interface Contract
All renderers implement:
```python
def clear()          # Erase all content
def draw_text(x, y, text, selected=False)  # Draw with optional selection highlight
def update()         # Flush to physical/visual display
```

### Optional Dependencies
- Extras are optional to keep non-RPi installs lightweight
- GPIO/OLED code only runs when hardware is available
- tkinter must be system-installed (not via pip)

## Development Workflows

### Setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .  # Editable install
```

### Run Simulator
```bash
cd src/spotifactory/menu
python simulated_menu.py
```
Or use the task: `Run simulated_menu.py` (configured in workspace)

### Testing
```bash
pytest  # Runs tests/ directory
```

### Install GUI Extras
```bash
pip install .[gui]  # Includes Pillow
pip install .[rpi]  # Includes Adafruit libraries for hardware
pip install .[dev]  # Testing/linting tools
```

## Integration Points

### Spotipy Integration (Not Yet Implemented)
- Project depends on `spotipy>=2.22.0` but code doesn't use it yet
- Future work: Replace placeholder `main.py` with actual Spotify API integration
- Expect authentication callbacks and playback control handlers

### Cross-Platform Rendering
- Desktop: tkinter simulator works on macOS/Linux/Windows
- RPi: Requires `Adafruit-Blinka` and `adafruit-circuitpython-ssd1306`
- Always test with simulator before assuming hardware will work

## Testing & Quality

- Test file pattern: `tests/test_*.py`
- Use `pytest` with assertions
- Type hints are optional but recommended (project supports mypy)
- Code style: black formatter configured

## File Locations Quick Reference
- Package root: `src/spotifactory/`
- Menu system: `src/spotifactory/menu/`
- Tests: `tests/`
- Config: `pyproject.toml` (dependencies and build metadata)
