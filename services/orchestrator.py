"""Conversation orchestration (Detailed Build Specification section 10).

Coordinates: deterministic guardrail pre-check -> AI planning call ->
policy/plan validation -> approved retrieval and read-only queries ->
bounded evidence assembly -> AI answer drafting with verification ->
rendering payload -> diagnostic and audit persistence.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from models.ai_contracts import (
    AnswerDraft,
    LLMAuthenticationError,
    LLMConnectionError,
    LLMError,
    LLMNotConfiguredError,
    PlanningResponse,
)
from models.diagnostic import DiagnosticRecord
from models.evidence import ChartSpec, SlideEvidence
from services import audit_service
from services.analysis_service import is_analytical, run_analysis
from services.answer_service import (
    ComposedAnswer,
    build_evidence_package,
    compose_answer,
    render_answer_text,
)
from services.catalogue import get_catalogue
from services.chart_service import build_chart_spec
from services.context_service import ConversationContext, apply_updates
from services.engine import EngineResult, run_plan
from services.llm_provider import get_llm_provider
from services.policy import PlanValidationError
from services.query_executor import QueryExecutionError
from services.query_planner import guardrail_message, plan_request
from services.review_service import comparison_label, quarter_label
from services.settings import get_llm_settings, load_yaml


@dataclass
class QueryOutput:
    engine_result: EngineResult
    chart_spec: ChartSpec | None


@dataclass
class OrchestratorResult:
    status: str                      # SUCCESS, BLOCKED, NO_RESULT, ERROR
    intent: str
    answer_text: str
    draft: AnswerDraft | None = None
    query_outputs: list[QueryOutput] = field(default_factory=list)
    slides: list[SlideEvidence] = field(default_factory=list)
    guardrail_category: str | None = None
    alternative: str | None = None
    evidence_package: object | None = None
    analysis_titles: list[str] = field(default_factory=list)
    diagnostic_id: str | None = None
    duration_ms: int = 0
    used_fallback: bool = False
    warnings: list[str] = field(default_factory=list)
    period_label: str = ""


def _standard_message(key: str, **kwargs) -> str:
    messages = load_yaml("guardrails.yaml").get("standard_messages", {})
    text = messages.get(key, "").strip()
    return text.format(**kwargs) if kwargs else text


def _diagnostic_title(intent: str, outputs: list[QueryOutput],
                      slides: list[SlideEvidence], question: str) -> str:
    cat = get_catalogue()
    if outputs:
        er = outputs[0].engine_result
        plan = er.validated.plan
        op_labels = {
            "aggregate": "", "compare": "movement", "trend": "trend",
            "rank": "ranking", "share_of_total": "share of total",
            "contribution_to_movement": "contribution to movement",
            "list_changes": "changes", "pivot": "",
        }
        measure = (cat.measure_label(er.validated.dataset, plan.measures[0])
                   if plan.measures else
                   plan.attributes[0].replace("_", " ").title() if plan.attributes
                   else "Result")
        parts = [measure]
        if op_labels.get(plan.operation):
            parts.append(op_labels[plan.operation])
        if plan.group_by:
            parts.append("by " + ", ".join(
                cat.dimension_label(er.validated.dataset, g) for g in plan.group_by[:2]))
        periods = " vs ".join(quarter_label(r) for r in plan.review_ids[:2]) \
            if len(plan.review_ids) <= 2 else \
            f"{quarter_label(plan.review_ids[0])} to {quarter_label(plan.review_ids[-1])}"
        return f"{' '.join(parts)} - {periods}"
    if slides:
        return f"Report: {slides[0].title} - {slides[0].quarter_label}"
    return question[:80]


def _filters_label(outputs: list[QueryOutput]) -> str:
    if not outputs:
        return ""
    plan = outputs[0].engine_result.validated.plan
    if not plan.filters:
        return "No filters were applied."
    parts = [f"{f.field.replace('_', ' ')} = {f.value}" for f in plan.filters]
    return "Filters: " + "; ".join(str(p) for p in parts) + "."


def _result_json(outputs: list[QueryOutput]) -> dict | None:
    if not outputs:
        return None
    er = outputs[0].engine_result
    df = er.shaped.df
    return {
        "columns": list(df.columns),
        "rows": df.where(df.notna(), None).values.tolist(),
        "summary": er.shaped.summary,
    }


def handle_question(question: str, session_id: str, context: ConversationContext,
                    settings=None, provider=None,
                    deep_analysis: bool | None = None) -> OrchestratorResult:
    """Answer one question.

    `deep_analysis` forces the analysis battery on (True) or off (False);
    None auto-detects from the question's phrasing.
    """
    t0 = time.perf_counter()
    settings = settings or get_llm_settings()
    audit_service.ensure_session(session_id, context.current_review_id,
                                 context.to_payload())
    audit_service.log_message(session_id, "user", question)

    def finalize(result: OrchestratorResult, plan_dicts: list[dict] | None = None,
                 in_library: bool = False) -> OrchestratorResult:
        result.duration_ms = int((time.perf_counter() - t0) * 1000)
        outputs = result.query_outputs
        record = DiagnosticRecord(
            diagnostic_id=audit_service.new_diagnostic_id(),
            session_id=session_id,
            created_at=audit_service.created_at_now(),
            title=_diagnostic_title(result.intent, outputs, result.slides, question),
            user_question=question,
            primary_review_id=context.current_review_id,
            comparison_review_ids=[r for o in outputs[:1]
                                   for r in o.engine_result.validated.plan.review_ids[1:]],
            intent=result.intent,
            query_plan=(outputs[0].engine_result.validated.plan.model_dump()
                        if outputs else (plan_dicts[0] if plan_dicts else None)),
            compiled_query=outputs[0].engine_result.compiled.sql if outputs else None,
            query_parameters=outputs[0].engine_result.compiled.parameters if outputs else None,
            result=_result_json(outputs),
            chart_spec=(outputs[0].chart_spec.model_dump()
                        if outputs and outputs[0].chart_spec else None),
            evidence={
                "guardrail_category": result.guardrail_category,
                "periods": {
                    "primary": context.current_review_id,
                    "comparisons": [r for o in outputs[:1]
                                    for r in o.engine_result.validated.plan.review_ids[1:]],
                },
                "sources": [o.engine_result.validated.table for o in outputs],
                "filters": [f.model_dump() for o in outputs[:1]
                            for f in o.engine_result.validated.plan.filters],
                "group_by": [g for o in outputs[:1]
                             for g in o.engine_result.validated.plan.group_by],
                "slide_citations": [
                    {"review_id": s.review_id, "slide_number": s.slide_number,
                     "title": s.title} for s in result.slides],
                "warnings": result.warnings,
            },
            answer_text=result.answer_text,
            status=result.status,
            query_hash=audit_service.query_hash(
                outputs[0].engine_result.validated.plan.model_dump() if outputs else None),
            duration_ms=result.duration_ms,
        )
        audit_service.save_diagnostic(record, in_library=in_library)
        result.diagnostic_id = record.diagnostic_id
        audit_service.log_message(session_id, "assistant", result.answer_text,
                                  intent=result.intent,
                                  diagnostic_id=record.diagnostic_id)
        return result

    # 1. AI Call 1 - planning ---------------------------------------------
    try:
        planning = plan_request(question, context.to_payload(),
                                settings=settings, provider=provider)
    except LLMNotConfiguredError as exc:
        audit_service.log_model_call("planning", None, "NOT_CONFIGURED",
                                     schema_name="PlanningResponse")
        return finalize(OrchestratorResult(
            status="ERROR", intent="UNSUPPORTED",
            answer_text=f"{exc}\n\n{_standard_message('not_configured')}"))
    except LLMAuthenticationError as exc:
        # Credential/billing problems are configuration issues, not
        # interpretation failures: show the adapter's specific guidance.
        audit_service.log_model_call("planning", None, "AUTH_ERROR",
                                     schema_name="PlanningResponse",
                                     error_category=type(exc).__name__)
        return finalize(OrchestratorResult(
            status="ERROR", intent="UNSUPPORTED",
            answer_text=str(exc)))
    except LLMConnectionError as exc:
        audit_service.log_model_call("planning", None, "CONNECTION_ERROR",
                                     schema_name="PlanningResponse",
                                     error_category=type(exc).__name__)
        return finalize(OrchestratorResult(
            status="ERROR", intent="UNSUPPORTED",
            answer_text=f"{exc}\n\n{_standard_message('connection_failed')}"))
    except LLMError as exc:
        audit_service.log_model_call("planning", None, "ERROR",
                                     schema_name="PlanningResponse",
                                     error_category=type(exc).__name__)
        from models.ai_contracts import (
            LLMInvalidResponseError,
            LLMRateLimitError,
            LLMTimeoutError,
        )
        if isinstance(exc, LLMRateLimitError):
            message_key = "rate_limited"
        elif isinstance(exc, LLMTimeoutError):
            message_key = "timeout"
        elif isinstance(exc, LLMInvalidResponseError):
            message_key = "invalid_response"
        else:
            message_key = "model_failure"
        return finalize(OrchestratorResult(
            status="ERROR", intent="UNSUPPORTED",
            answer_text=_standard_message(message_key)))

    audit_service.log_model_call("planning", planning.metadata, "SUCCESS",
                                 retry_count=planning.retry_count,
                                 schema_name="PlanningResponse",
                                 output_value=planning.response.model_dump())
    response: PlanningResponse = planning.response

    # 3. Policy enforcement ------------------------------------------------
    if response.policy.status == "BLOCK" or response.intent == "OUT_OF_SCOPE":
        message, alternative = guardrail_message(response.policy.category)
        return finalize(OrchestratorResult(
            status="BLOCKED", intent="OUT_OF_SCOPE",
            answer_text=f"{message}\n\n{alternative}",
            guardrail_category=response.policy.category or "out_of_scope",
            alternative=alternative,
            period_label=quarter_label(context.current_review_id)))

    if response.policy.status == "UNSUPPORTED" or response.intent == "UNSUPPORTED":
        return finalize(OrchestratorResult(
            status="BLOCKED", intent="UNSUPPORTED",
            answer_text=("The stored review library does not contain the "
                         "information needed to answer that. It covers report "
                         "content, claims, premium, assumptions and selected "
                         "results for 2024 Q3 to 2026 Q2."),
            period_label=quarter_label(context.current_review_id)))

    # 4. Execute approved report searches and validated query plans --------
    slides: list[SlideEvidence] = []
    from services.report_service import search_slides
    for search in response.report_searches[:3]:
        rids = [r for r in search.review_ids if r] or [context.current_review_id]
        slides.extend(search_slides(rids, search.query, limit=search.limit))

    outputs: list[QueryOutput] = []
    warnings: list[str] = []
    plan_dicts = [p.model_dump() for p in response.query_plans]
    validation_failure: PlanValidationError | None = None

    # Deep analysis: replace the single planned query with a full battery of
    # approved diagnostics so the answer model can reason across evidence.
    run_deep = (is_analytical(question) if deep_analysis is None else deep_analysis)
    analysis_titles: list[str] = []
    if run_deep and response.intent not in ("REPORT_QA", "DIAGNOSTIC_REOPEN"):
        analysis = run_analysis(question, context.current_review_id,
                                inherited_filters=context.active_filters)
        for title, er in analysis.as_pairs():
            outputs.append(QueryOutput(
                engine_result=er,
                chart_spec=build_chart_spec(er.shaped, er.validated.plan.chart)))
            analysis_titles.append(title)
        warnings.extend(analysis.notes)
        for skipped in analysis.skipped:
            warnings.append(f"Not available for this focus - {skipped}")
        if outputs:
            plan_dicts = [o.engine_result.validated.plan.model_dump()
                          for o in outputs]

    for plan in ([] if outputs else
                 response.query_plans[:settings.max_query_plans_per_message]):
        # The selected review leads any comparison it takes part in.
        if (plan.operation in ("compare", "contribution_to_movement", "rank",
                               "list_changes")
                and context.current_review_id in plan.review_ids
                and plan.review_ids[0] != context.current_review_id
                and len(plan.review_ids) == 2):
            plan.review_ids = [context.current_review_id] + [
                r for r in plan.review_ids if r != context.current_review_id]
        try:
            er = run_plan(plan, question=question)
            outputs.append(QueryOutput(
                engine_result=er,
                chart_spec=build_chart_spec(er.shaped, plan.chart)))
            warnings.extend(er.validated.warnings)
        except PlanValidationError as exc:
            validation_failure = exc
            warnings.append(exc.message)
        except QueryExecutionError:
            return finalize(OrchestratorResult(
                status="ERROR", intent=response.intent,
                answer_text=_standard_message("query_failure"),
                warnings=warnings), plan_dicts)

    if validation_failure and not outputs and not slides:
        alt = " ".join(validation_failure.alternatives)
        return finalize(OrchestratorResult(
            status="BLOCKED", intent=response.intent,
            answer_text=(validation_failure.message + (f"\n\n{alt}" if alt else "")),
            warnings=warnings,
            period_label=quarter_label(context.current_review_id)), plan_dicts)

    # 5. No-result transparency -------------------------------------------
    non_empty = [o for o in outputs if not o.engine_result.shaped.df.empty]
    if not non_empty and not slides:
        if outputs:
            plan = outputs[0].engine_result.validated.plan
            label = comparison_label(plan.review_ids)
            return finalize(OrchestratorResult(
                status="NO_RESULT", intent=response.intent,
                answer_text=_standard_message(
                    "no_matching_rows",
                    periods_and_filters=(f"The result uses {label}. "
                                         f"{_filters_label(outputs)}")),
                query_outputs=outputs, warnings=warnings,
                period_label=label), plan_dicts)
        return finalize(OrchestratorResult(
            status="NO_RESULT", intent=response.intent,
            answer_text=("I did not find relevant slides in the selected report "
                         f"({quarter_label(context.current_review_id)}) for that "
                         "question, and no data query was applicable. Try "
                         "rephrasing or selecting another review."),
            warnings=warnings), plan_dicts)

    # 6-9. Evidence package, AI Call 2, verification -----------------------
    primary = context.current_review_id
    comparisons = []
    if outputs:
        comparisons = [r for r in outputs[0].engine_result.validated.plan.review_ids
                       if r != primary]
    # A battery needs a bigger row budget than a single query, or later
    # diagnostics arrive truncated to five rows and cannot be reasoned over.
    row_budget = (settings.answer_evidence_row_limit * 4 if analysis_titles
                  else settings.answer_evidence_row_limit)
    package = build_evidence_package(
        question, primary, comparisons, slides,
        [o.engine_result for o in outputs],
        limitations=[], row_limit_total=row_budget,
        titles=analysis_titles or None)

    try:
        composed: ComposedAnswer = compose_answer(
            question, package, settings=settings, provider=provider,
            deep_analysis=bool(analysis_titles))
        audit_service.log_model_call(
            "answer", composed.metadata,
            "FALLBACK" if composed.used_fallback else "SUCCESS",
            schema_name="AnswerDraft")
        draft = composed.draft
        used_fallback = composed.used_fallback
    except LLMError as exc:
        # Answer-drafting failure: deterministic table plus templated summary.
        from services.answer_service import fallback_answer
        audit_service.log_model_call("answer", None, "ERROR",
                                     schema_name="AnswerDraft",
                                     error_category=type(exc).__name__)
        draft = fallback_answer(package)
        used_fallback = True

    # 10. Context updates and persistence ----------------------------------
    apply_updates(context, response.context_updates)
    if outputs:
        plan = outputs[0].engine_result.validated.plan
        context.comparison_review_ids = [r for r in plan.review_ids[1:]]
        context.active_filters = [f.model_dump() for f in plan.filters]
        context.last_group_by = list(plan.group_by)
        context.last_measure = plan.measures[0] if plan.measures else None
        context.last_dataset = outputs[0].engine_result.validated.dataset

    period_label = package.period_context.get("display_label", "")
    result = OrchestratorResult(
        status="SUCCESS", intent=response.intent,
        answer_text=render_answer_text(draft), draft=draft,
        query_outputs=outputs, slides=slides,
        analysis_titles=analysis_titles,
        used_fallback=used_fallback, warnings=warnings,
        period_label=period_label)
    result.evidence_package = package
    return finalize(result, plan_dicts, in_library=False)


# ---------------------------------------------------------------------------
# Saved diagnostic rerun (FR-027)
# ---------------------------------------------------------------------------

@dataclass
class RerunOutcome:
    ok: bool
    message: str
    engine_result: EngineResult | None = None
    hash_matches: bool = False
    version_mismatch: bool = False


def rerun_diagnostic(diagnostic_id: str) -> RerunOutcome:
    from models.query_plan import QueryPlan
    import json as _json

    record = audit_service.get_diagnostic(diagnostic_id)
    if not record or not record.get("query_plan_json"):
        return RerunOutcome(ok=False,
                            message="This diagnostic has no stored query plan to rerun.")
    plan = QueryPlan(**_json.loads(record["query_plan_json"]))
    new_hash = audit_service.query_hash(plan.model_dump())
    version_mismatch = (record.get("query_hash") is not None
                        and new_hash != record["query_hash"])
    try:
        er = run_plan(plan)
    except (PlanValidationError, QueryExecutionError) as exc:
        return RerunOutcome(ok=False, message=f"Rerun failed: {exc}")
    df = er.shaped.df
    new_result = {
        "columns": list(df.columns),
        "rows": df.where(df.notna(), None).values.tolist(),
        "summary": er.shaped.summary,
    }
    old_result = (_json.loads(record["result_json"])
                  if record.get("result_json") else None)
    same = (audit_service.result_hash(new_result)
            == audit_service.result_hash(old_result))
    if version_mismatch:
        message = ("The packaged review data has changed since this diagnostic "
                   "was saved; results may differ from the stored version.")
    elif same:
        message = "Rerun complete. The result matches the stored diagnostic exactly."
    else:
        message = "Rerun complete, but the result differs from the stored diagnostic."
    return RerunOutcome(ok=True, message=message, engine_result=er,
                        hash_matches=same, version_mismatch=version_mismatch)
