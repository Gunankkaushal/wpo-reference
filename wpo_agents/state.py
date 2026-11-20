"""Graph state for the nightly supervisor and for Manager Copilot."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class NightlyState(TypedDict, total=False):
    run_id: str
    plan_date: str
    started_at: str
    status: str  # running | published | failed_compliance

    # stage 1 · forecast_demand
    # `demand` is the hand-off to stage 2. In production this rides the
    # forecast-queue (Service Bus, edges E05/E06); here it is graph state.
    demand: list[dict]
    absences: dict[str, list[dict]]
    forecast_notes: dict[str, str]
    forecast_retries: int

    # stage 2 · optimize_roster
    candidate_roster: dict[str, list[dict]]
    unfilled: list[dict]
    excluded_workers: list[str]
    optimizer_iterations: int

    # stage 3 · compliance
    compliance: dict[str, Any]

    # stage 4 · writeback
    published_sites: list[str]

    events: Annotated[list[str], operator.add]


class CopilotState(TypedDict, total=False):
    question: str
    site_id: str | None
    ignore_hours: bool
    open: bool
    roster_record: dict
    answer: str
