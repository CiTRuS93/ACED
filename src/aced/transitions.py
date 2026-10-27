"""The sole registry for four development stages and orthogonal run controls."""

from dataclasses import dataclass

from .models import Step


@dataclass(frozen=True)
class Transition:
    step: Step
    scope: str | None = None


DEFAULT_SCOPES = {
    Step.HYPOTHESIZE: "research",
    Step.IMPLEMENT: "implementation",
    Step.EXPERIMENT: "preparation_canary",
    Step.DECIDE: "decision",
}

TRANSITIONS: dict[tuple[Step, str], Transition] = {
    (Step.HYPOTHESIZE, "accepted"): Transition(Step.IMPLEMENT, "implementation"),
    (Step.IMPLEMENT, "accepted"): Transition(Step.EXPERIMENT, "preparation_canary"),
    (Step.EXPERIMENT, "main_authorized"): Transition(Step.EXPERIMENT, "main_exposure"),
    (Step.EXPERIMENT, "accepted"): Transition(Step.DECIDE, "decision"),
    (Step.DECIDE, "disposition_authorized"): Transition(Step.DECIDE, "disposition"),
    (Step.DECIDE, "next_hypothesis"): Transition(Step.HYPOTHESIZE, "research"),
    (Step.DECIDE, "repair"): Transition(Step.IMPLEMENT, "implementation"),
    (Step.DECIDE, "finish"): Transition(Step.DECIDE),
}
for _step in Step:
    TRANSITIONS[(_step, "unsuccessful")] = Transition(Step.DECIDE, "decision")
    TRANSITIONS[(_step, "stop")] = Transition(_step, "reconcile")
    for _event in (
        "waiting",
        "blocked",
        "retry",
        "correction",
        "hold",
        "resume",
        "observation",
        "prepared",
        "authorized",
        "approval_wait",
        "denied",
        "launched",
        "launch_unknown",
        "task_observed",
        "result_saved",
        "evidence_wait",
        "rejected",
        "cancelled",
        "fenced",
        "stop_delivered",
        "settled",
        "stopped",
        "budget_exhausted",
        "wake",
        "reconcile",
        "task_prepared",
        "task_reserved",
        "task_dispatch_intent",
        "dispatch_authorized",
        "task_started",
        "task_output_saved",
        "cancel_intent",
        "correction_required",
        "stop_required",
        "stop_delivery",
        "unlaunched_task_cancelled",
        "reconciliation_required",
        "reproposed",
    ):
        TRANSITIONS[(_step, _event)] = Transition(_step)


class TransitionError(ValueError):
    pass


def _entry(step: Step, event: str) -> Transition:
    try:
        return TRANSITIONS[(step, event)]
    except KeyError:
        raise TransitionError(f"forbidden transition: {step} + {event}") from None


def transition(step: Step, event: str) -> Step:
    return _entry(step, event).step


def scope_for(step: Step, event: str | None = None) -> str:
    """Return the initial scope or the scope selected by a consequential event."""
    if event is None:
        return DEFAULT_SCOPES[step]
    item = _entry(step, event)
    return item.scope or DEFAULT_SCOPES[item.step]
