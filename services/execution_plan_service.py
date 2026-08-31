"""Generate a step-by-step farming execution plan for a selected crop."""

from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger(__name__)
Task = dict[str, Any]


def _valid_crop_name(crop_name: str) -> bool:
    """Return whether a crop name is a usable non-empty string."""
    return isinstance(crop_name, str) and bool(crop_name.strip())


def _valid_duration(duration_days: int) -> bool:
    """Return whether a duration is a positive whole-number day count."""
    return isinstance(duration_days, int) and not isinstance(duration_days, bool) and duration_days > 0


def generate_land_preparation_tasks(crop_name: str) -> list[Task]:
    """Generate tasks for preparing the field before planting."""
    if not _valid_crop_name(crop_name):
        logger.warning("Invalid crop name for land preparation")
        return []
    return [{
        "day": 1,
        "task": "Land Preparation",
        "description": "Prepare the field and remove weeds",
    }]


def generate_seeding_tasks(crop_name: str) -> list[Task]:
    """Generate the crop seeding task."""
    if not _valid_crop_name(crop_name):
        logger.warning("Invalid crop name for seeding")
        return []
    return [{
        "day": 7,
        "task": "Seed Sowing",
        "description": "Sow quality seeds",
    }]


def generate_fertilizer_schedule(crop_name: str) -> list[Task]:
    """Generate the initial fertilizer application task."""
    if not _valid_crop_name(crop_name):
        logger.warning("Invalid crop name for fertilizer schedule")
        return []
    return [{
        "day": 15,
        "task": "Apply Fertilizer",
        "description": "Apply recommended fertilizer",
    }]


def generate_irrigation_schedule(crop_name: str, duration_days: int) -> list[Task]:
    """Generate irrigation reminders every seven days during crop growth."""
    if not _valid_crop_name(crop_name) or not _valid_duration(duration_days):
        logger.warning("Invalid crop or duration for irrigation schedule")
        return []
    return [
        {
            "day": day,
            "task": "Irrigation",
            "description": f"Irrigate the {crop_name.strip()} crop",
        }
        for day in range(7, duration_days + 1, 7)
    ]


def generate_harvest_schedule(crop_name: str, duration_days: int) -> list[Task]:
    """Generate the harvest task for the crop's expected duration."""
    if not _valid_crop_name(crop_name) or not _valid_duration(duration_days):
        logger.warning("Invalid crop or duration for harvest schedule")
        return []
    return [{
        "day": duration_days,
        "task": "Harvest",
        "description": f"Harvest the {crop_name.strip()} crop",
    }]


def generate_execution_plan(crop_name: str, duration_days: int) -> list[Task]:
    """Combine all cultivation schedules and sort tasks by day."""
    if not _valid_crop_name(crop_name) or not _valid_duration(duration_days):
        logger.warning("Invalid crop or duration for execution plan")
        return []

    tasks = (
        generate_land_preparation_tasks(crop_name)
        + generate_seeding_tasks(crop_name)
        + generate_fertilizer_schedule(crop_name)
        + generate_irrigation_schedule(crop_name, duration_days)
        + generate_harvest_schedule(crop_name, duration_days)
    )
    return sorted(tasks, key=lambda task: task["day"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    plan = generate_execution_plan("Tomato", 120)
    for task in plan:
        print(task)
