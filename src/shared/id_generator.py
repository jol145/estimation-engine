from __future__ import annotations

import ulid


def generate_calculation_id() -> str:
    """Generate a unique calculation ID with 'calc_' prefix."""
    return f"calc_{ulid.ULID()}"
