"""Time conversion utilities."""


def time_to_minutes(time_str: str) -> int:
    """Convert 'HH:MM' to minutes since midnight."""
    h, m = map(int, time_str.split(":"))
    return h * 60 + m


def minutes_to_time(minutes: int, day_start: int = 0) -> str:
    """Convert minutes to 'HH:MM' format."""
    total = minutes + day_start
    return f"{total // 60:02d}:{total % 60:02d}"
