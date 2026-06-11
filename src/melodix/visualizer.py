import math
import random
from textual.widget import Widget
from rich.text import Text

# Gruvbox palette for the visualizer
_LOW  = "#8ec07c"   # aqua   – quiet
_MID  = "#fabd2f"   # yellow – medium
_HIGH = "#fb4934"   # red    – loud
_EMPTY = "#3c3836"  # bg1    – inactive bar cell


class AudioVisualizer(Widget):
    """Full-height multi-row block spectrum — btop graph aesthetic."""

    def __init__(self, num_bars: int = 80, **kwargs):
        super().__init__(**kwargs)
        self.num_bars = num_bars
        self.heights: list[float] = [0.0] * num_bars
        self.targets: list[float] = [0.0] * num_bars
        self.is_playing = False
        self.volume_ratio = 1.0
        self.phase = 0.0

    def on_mount(self) -> None:
        self.set_interval(0.05, self._tick)

    def _tick(self) -> None:
        if self.is_playing:
            self.phase = (self.phase + 0.11) % (2 * math.pi * 100)  # prevent float drift
            for i in range(self.num_bars):
                w1 = math.sin(self.phase       + i * 0.30)
                w2 = math.cos(self.phase * 0.5 - i * 0.18)
                w3 = math.sin(self.phase * 1.3 + i * 0.65) * 0.55
                w4 = math.cos(self.phase * 0.2 + i * 0.12) * 0.35
                raw = (w1 + w2 + w3 + w4 + 3.25) / 6.5
                raw += random.uniform(-0.06, 0.06)
                self.targets[i] = max(0.0, min(1.0, raw * self.volume_ratio))
        else:
            for i in range(self.num_bars):
                self.targets[i] = max(0.0, self.targets[i] - 0.06)

        for i in range(self.num_bars):
            self.heights[i] = self.heights[i] * 0.6 + self.targets[i] * 0.4
            self.heights[i] = max(0.0, min(1.0, self.heights[i]))

        self.refresh()

    def set_state(self, is_playing: bool, volume: float) -> None:
        self.is_playing = is_playing
        self.volume_ratio = max(0.0, min(1.0, volume / 100.0))

    def render(self) -> Text:
        text = Text(no_wrap=True, overflow="crop")
        h = max(1, self.size.height)
        w = max(4, self.size.width)
        num_display = min(self.num_bars, w // 2)

        for row in range(h - 1, -1, -1):
            threshold = row / h if h > 1 else 0.0
            for i in range(num_display):
                src = int(i * self.num_bars / num_display)
                bar_h = self.heights[src]

                # Diagonal sheen highlight calculation
                sheen_val = (i - row * 2) % 25
                is_sheen = sheen_val in (0, 1)
                is_sheen_soft = sheen_val in (2, 24)

                if bar_h >= threshold and bar_h > 0:
                    # Vertical color gradient (btop style)
                    cell_ratio = row / h if h > 1 else 0.0
                    if cell_ratio < 0.4:
                        color = _LOW
                    elif cell_ratio < 0.75:
                        color = _MID
                    else:
                        color = _HIGH

                    # Textured gradient based on depth from top of bar
                    dist_from_top = bar_h - threshold
                    if dist_from_top < 0.15:
                        ch = "░"
                    elif dist_from_top < 0.35:
                        ch = "▒"
                    elif dist_from_top < 0.6:
                        ch = "▓"
                    else:
                        ch = "█"

                    # Apply reflection sheen highlight on the bar itself
                    if is_sheen:
                        style = "bold #ffffff on #504945"
                        ch = "█"
                    elif is_sheen_soft:
                        style = f"bold #ebdbb2"
                    else:
                        style = f"bold {color}"

                    text.append(ch, style=style)
                else:
                    # Empty cells / Transparent background representation
                    if is_sheen:
                        text.append("╱", style="bold #504945")
                    elif is_sheen_soft:
                        text.append("·", style="bold #3c3836")
                    else:
                        text.append(" ", style=_EMPTY)

                text.append(" ")

            if row > 0:
                text.append("\n")

        return text
