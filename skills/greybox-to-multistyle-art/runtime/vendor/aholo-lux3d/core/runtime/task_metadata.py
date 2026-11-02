"""Validate already captured task creation facts; never contact a service."""

import datetime
import re

import lux3d_client
import workflow_contracts


SCHEMA = "lux3d.task-metadata/v1"
TASK_LIST_PATH = "/lux3d/v1/generate/task/list"


def normalize_task_id(value):
    """Keep task identity lossless across Python, JSON and browser consumers."""
    if (
        not isinstance(value, (str, int))
        or isinstance(value, bool)
        or not re.fullmatch(r"[1-9][0-9]{0,18}", str(value))
        or int(value) > 9223372036854775807
    ):
        raise ValueError("taskId must be a positive signed 64-bit decimal integer")
    return str(value)


def _created_iso(value):
    if type(value) is not int or not 0 <= value <= 253402300799999:
        raise ValueError(
            "created must be a representable Unix timestamp in milliseconds"
        )
    epoch = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
    return (epoch + datetime.timedelta(milliseconds=value)).isoformat(
        timespec="milliseconds"
    )


def created_at(record, task_id, region):
    """Validate a stored record and return the provider creation time, never local time."""
    if not isinstance(record, dict) or set(record) != {
        "schema",
        "taskId",
        "region",
        "created",
        "observedAt",
        "source",
    }:
        raise ValueError("Invalid task metadata fields")
    if record["schema"] != SCHEMA:
        raise ValueError("Unsupported task metadata schema")
    if record["taskId"] != normalize_task_id(task_id) or record["region"] != region:
        raise ValueError("Task metadata taskId or region does not match the workflow")
    if not isinstance(region, str) or region not in lux3d_client.REGION_BASE_URLS:
        raise ValueError(
            "Task metadata requires an explicit cn or international region"
        )
    observed = record["observedAt"]
    if not isinstance(observed, str):
        raise ValueError("Task metadata observedAt must include a timezone")
    workflow_contracts.parse_datetime(observed, "Task metadata observedAt")
    source = record["source"]
    if (
        not isinstance(source, dict)
        or set(source) != {"method", "path", "field", "unit", "page", "pageSize"}
        or any(
            source[key] != value
            for key, value in {
                "method": "GET",
                "path": TASK_LIST_PATH,
                "field": "items[].created",
                "unit": "unix-milliseconds",
            }.items()
        )
    ):
        raise ValueError("Invalid task metadata source")
    if type(source["page"]) is not int or source["page"] < 1:
        raise ValueError("Invalid task metadata source page")
    if type(source["pageSize"]) is not int or not 1 <= source["pageSize"] <= 100:
        raise ValueError("Invalid task metadata source pageSize")
    return _created_iso(record["created"])
