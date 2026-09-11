# Melodix

Melodix is a premium, modern, and highly customized Terminal User Interface (TUI) music player for Linux, built using Python's modern **Textual** framework and powered by the **mpv** audio engine via IPC sockets. It is designed to match system monitors like `btop` with a rich **Gruvbox dark** theme, rounded panel layouts, transparent background integration, and a custom procedural audio visualizer.

<!-- Preview screenshot: add docs/preview.png and uncomment below -->
<!-- ![Melodix Preview](docs/preview.png) --> 
---

##  Features

- **Terminal Transparency Integration**: Complete `ansi_default` background architecture, allowing your native terminal wallpaper/opacity to shine directly through the panels.
- **Interactive File Library**: Tree-based navigation starting in `~/Music` by default. Hitting `Enter` on any audio file instantly appends it to the active queue.
- **Procedural Spectrum Visualizer**:
  - Vertical color gradients matching the btop graph look.
  - Textured gradient animations using shaded block characters (`░`, `▒`, `▓`, `█`).
  - Dynamic diagonal highlights (`╱`) and white glow sheens.
- **Robust IPC Backend**: Controls a background-spawned `mpv` process asynchronously using standard JSON-RPC command sockets.
- **Keyboard & Mouse Friendly**: Complete hotkeys for mouse-free operation, plus clickable transport and volume controls.
- **Fully Packaged**: Modern PEP-517 setup via `pyproject.toml` for standard system installations.

---

## Keyboard Shortcuts

| Hotkey | Action |
| :--- | :--- |
| `Space` | Play / Pause |
| `Left` / `Right` | Seek backward / forward 5 seconds |
| `Up` / `Down` | Increase / decrease volume by 5% |
| `N` | Next track in queue |
| `P` | Previous track in queue |
| `S` | Toggle Shuffle mode |
| `R` | Toggle Repeat mode (`none` 󰓛 -> `track` 󰑘 -> `all` 󰑖) |
| `M` | Mute / Unmute audio |
| `F` | Focus File Browser |
| `L` | Focus Active Queue |
| `A` | Add selected directory to Queue |
| `Delete` | Remove selected track from Queue |
| `Q` | Quit Melodix Player |

---

## Installation & Setup

### Prerequisites

Ensure you have python (>= 3.10), `mpv`, and `ffmpeg` installed on your system.

```bash
# Arch Linux
sudo pacman -S mpv ffmpeg python

# Debian/Ubuntu
sudo apt install mpv ffmpeg python3
```

### Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/Tsukabe-Admin/melodix.git
   cd melodix
   ```
2. Build and install locally:
   ```bash
   pip install .
   ```
   *Alternatively, you can install it in edit/developer mode:*
   ```bash
   pip install -e .
   ```

3. Launch it directly:
   ```bash
   melodix
   ```
   `python -m melodix` works too.

---

## Development

Install the dev extras (pytest, pytest-asyncio, ruff):

```bash
pip install -e ".[dev]"
pytest          # 70+ unit and headless-integration tests (mpv tests auto-skip)
ruff check .    # lint
```

The tests redirect `HOME` to a temporary directory, so they never touch your
real config or playlists.

### Project layout

| Module | Responsibility |
| :--- | :--- |
| `main.py` | `MelodixApp`: queue state machine, actions, keybindings, entry point |
| `player.py` | mpv subprocess + JSON-IPC socket, property cache, reader thread |
| `downloader.py` | yt-dlp subprocess + stdout state machine (video/playlist → MP3) |
| `models.py` | `Track` type, `make_track()`, `format_time()`, audio extensions |
| `theme.py` | Gruvbox palette shared by every module that emits Rich markup |
| `browser.py` | Filtered library `DirectoryTree` |
| `widgets.py` | Reusable widgets (e.g. `PlaylistItem`) |
| `playlists.py` / `config.py` | Persistent JSON stores (playlists, settings) |
| `playlists_screen.py`, `add_to_playlist.py`, `youtube_screen.py`, `change_root_screen.py` | Modal screens |

### Runtime files

| Path | Contents |
| :--- | :--- |
| `~/.config/melodix/config.json` | Volume, shuffle/repeat mode, browser root |
| `~/.config/melodix/playlists/*.json` | Saved playlists |
| `~/.cache/melodix/melodix.log` | Diagnostic log (warnings/errors) |

If Melodix misbehaves, that log is the first place to look.
