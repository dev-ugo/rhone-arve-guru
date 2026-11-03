"""The six confirmed source series and their original catalog units."""

from datetime import timedelta

SERIES = (
    (2606, "flow"),
    (2606, "temperature"),
    (2170, "flow"),
    (2170, "temperature"),
    (2170, "height"),
    (2170, "turbidity"),
)
UNITS = {"flow": "m3/s", "temperature": "°C", "height": "m", "turbidity": "BSTU"}
# An operational freshness criterion, not a calibrated safety threshold.
FRESHNESS = timedelta(minutes=30)
