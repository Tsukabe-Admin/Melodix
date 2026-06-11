# 󰓎 Melodix

Melodix is a premium, modern, and highly customized Terminal User Interface (TUI) music player for Linux, built using Python's modern **Textual** framework and powered by the **mpv** audio engine via IPC sockets. It is designed to match system monitors like `btop` with a rich **Gruvbox dark** theme, rounded panel layouts, transparent background integration, and a custom procedural audio visualizer.

![Melodix Preview](https://cdn.discordapp.com/attachments/662288171240783895/1514714910565732533/image.png?ex=6a2c5fb0&is=6a2b0e30&hm=ea9a8cadf4d9b25186794157f7738887ce8bf516594ec6b3ff7ad9ff3cd165c4&) *(Placeholder for preview)*

---

## ✨ Features

- **Terminal Transparency Integration**: Complete `ansi_default` background architecture, allowing your native terminal wallpaper/opacity to shine directly through the panels.
- **btop Aesthetic**: Dense grid layouts, color-coded sections (Blue for Library, Yellow for Queue, Orange for Controls), and rounded corner styles (`border: round`).
- **Interactive File Library**: Tree-based navigation starting in `~/Music` by default. Hitting `Enter` on any audio file instantly appends it to the active queue.
- **Procedural Spectrum Visualizer**:
  - Vertical color gradients matching the btop graph look.
  - Textured gradient animations using shaded block characters (`░`, `▒`, `▓`, `█`).
  - Dynamic diagonal highlights (`╱`) and white glow sheens.
- **Robust IPC Backend**: Controls a background-spawned `mpv` process asynchronously using standard JSON-RPC command sockets.
- **Keyboard & Mouse Friendly**: Complete hotkeys for mouse-free operation, plus clickable transport and volume controls.
- **Fully Packaged**: Modern PEP-517 setup via `pyproject.toml` for standard system installations.

---

## 🎹 Keyboard Shortcuts

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

## 🚀 Installation & Setup

### Prerequisites

Ensure you have python (>= 3.9), `mpv`, and `ffmpeg` installed on your system.

```bash
# Arch Linux
sudo pacman -S mpv ffmpeg python

# Debian/Ubuntu
sudo apt install mpv ffmpeg python3
```

### Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/yourusername/melodix.git
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

---

## 🛠 Architecture

- **`main.py`**: The entrypoint and Textual App controller. Manages UI mounts, event loops, reactive properties, and links keys to player actions.
- **`player.py`**: The background controller. Spawns `mpv --idle` and connects via standard UNIX socket IPC. Sends serialized JSON commands and reads messages in an independent background thread.
- **`visualizer.py`**: Renders the spectrum graph using overlapping mathematical wave expressions scaled in real-time by volume and pause state.
- **`styles.css`**: Textual CSS styling sheet describing panel layouts, Gruvbox theme tokens, and transparency settings.
# Melodix
# Melodix
