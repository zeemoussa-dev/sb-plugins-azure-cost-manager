"""The Azure Cost Manager's HTTP surface. The host mounts it under `/plugins/azure-cost-manager/`.

Reading a customer never calls Azure; `POST /sync` is the one route that does,
and it only starts the background sync. The weekly Hermes job calls it.
"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Body, File, HTTPException, Query, Response, UploadFile

from .azure_token import AzureCliToken, AzureSignInError
from .billing_client import AzureApiError, AzureThrottled
from . import consumption_analysis
from .consumption_service import ConsumptionService, CustomerNotFound
from .consumption_sync import ConsumptionSync
from .customers import COMMITMENT_TYPES, AccountDirectory, CustomerBook, CustomerError
from .pipeline import Pipeline, PipelineUnavailable
from .sync_log import SyncLog


def _answered(call):
    """Each failure says who can fix it: the operator's sign-in (424), Azure's
    throttling (429), Azure itself (502), or the request (400/404)."""
    try:
        return call()
    except AzureSignInError as exc:
        raise HTTPException(status_code=424, detail=str(exc)) from exc
    except AzureThrottled as exc:
        raise HTTPException(status_code=429, detail=str(exc),
                            headers={"Retry-After": str(exc.retry_after_seconds)}) from exc
    except AzureApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except CustomerNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PipelineUnavailable as exc:
        raise HTTPException(status_code=424, detail=str(exc)) from exc
    except (CustomerError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _account_list(accounts: str | None) -> list[str] | None:
    return [name.strip() for name in (accounts or "").split(",") if name.strip()] or None


def _compass(call):
    """A Compass feature's failures said by who can fix them: a framework or install
    without Compass (424), Compass itself (502)."""
    try:
        return _answered(call)
    except RuntimeError as exc:
        if type(exc).__name__ in ("CompassUnavailable", "BriefUnavailable"):
            raise HTTPException(status_code=424, detail=str(exc)) from exc
        if type(exc).__name__ == "LlmError":
            raise HTTPException(status_code=502, detail=f"Compass could not answer: {exc}") from exc
        raise
    except HTTPException as exc:
        if exc.status_code == 400 and "Compass did not answer" in str(exc.detail):
            raise HTTPException(status_code=502, detail=exc.detail) from exc
        raise


def build_router(service: ConsumptionService, book: CustomerBook, directory: AccountDirectory,
                 sync: ConsumptionSync, token: AzureCliToken, pipeline: Pipeline,
                 log: SyncLog | None = None, advisor=None) -> APIRouter:
    router = APIRouter()

    def measure(marketplace: str, credits: bool, billing_day: int | None = None) -> dict:
        """`marketplace`: true, false, or core42 (only Core42's own offers: Core42 revenue).
        `billing_day`: from which day of the month the month before counts as closed."""
        chosen = marketplace.strip().lower()
        if chosen not in ("true", "false", "core42"):
            raise HTTPException(status_code=400, detail="marketplace is true, false or core42")
        if billing_day is not None and not 1 <= billing_day <= consumption_analysis.LATEST_BILLING_DAY:
            raise HTTPException(status_code=400,
                                detail=f"billing_day is a day from 1 to {consumption_analysis.LATEST_BILLING_DAY}")
        return {"marketplace": "core42" if chosen == "core42" else chosen == "true", "credits": credits,
                "billing_day": consumption_analysis.DEFAULT_BILLING_DAY if billing_day is None else billing_day}

    @router.get("/customers/{customer_id}/export.xlsx")
    def get_export(customer_id: str, marketplace: str = "true", credits: bool = True, view: str = "account",
                   billing_day: int | None = None, accounts: str | None = None) -> Response:
        name, workbook = _answered(lambda: service.export(customer_id, measure(marketplace, credits, billing_day), view,
                                                          _account_list(accounts)))
        return Response(workbook, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})

    @router.get("/customers/{customer_id}/marketplace")
    def get_customer_marketplace(customer_id: str, first_month: str | None = None, last_month: str | None = None,
                                 accounts: str | None = None) -> dict:
        return _answered(lambda: service.marketplace(customer_id, first_month, last_month, _account_list(accounts)))

    @router.get("/marketplace/renewals")
    def get_marketplace_renewals() -> list[dict]:
        """When each recurring Marketplace purchase next charges, and for how much."""
        return _answered(service.renewals)

    @router.get("/marketplace/whitespace")
    def get_marketplace_whitespace(first_month: str | None = None, last_month: str | None = None) -> dict:
        """What customers buy from publishers other than Core42, by category."""
        return _answered(lambda: service.marketplace_whitespace(first_month, last_month))

    @router.get("/marketplace")
    def get_marketplace(first_month: str | None = None, last_month: str | None = None) -> dict:
        """Every partner solution across every customer. The line-level detail is
        the export's, not the page's -- thousands of rows the page never shows."""
        report = _answered(lambda: service.marketplace_across(first_month, last_month))
        report.pop("lines", None)
        return report

    @router.get("/marketplace/not-macc-eligible")
    def get_not_macc_eligible() -> list[dict]:
        return service.not_macc_eligible()

    @router.put("/marketplace/macc-eligibility")
    def put_macc_eligibility(change: dict = Body(...)) -> list[dict]:
        """`{publisher, offer, eligible}`: one offer, for every customer."""
        return _answered(lambda: service.set_macc_eligible((change.get("publisher") or "").strip(),
                                                           (change.get("offer") or "").strip(),
                                                           bool(change.get("eligible", True))))

    @router.get("/solutions/catalog")
    def get_solution_catalog() -> dict:
        return _answered(service.solution_catalog)

    @router.get("/guide")
    def get_guide() -> dict:
        return _answered(service.guide)

    @router.get("/solutions")
    def get_solutions_across() -> dict:
        return _answered(service.solutions_across)

    @router.get("/customers/{customer_id}/brief")
    def get_customer_brief(customer_id: str) -> dict:
        return _answered(lambda: service.customer_brief(customer_id))

    @router.post("/customers/{customer_id}/brief")
    def post_customer_brief(customer_id: str) -> dict:
        """Writes the brief now. Compass failing is said as such (502), and a framework
        without Compass for plugins (424), never as a fault of the request."""
        try:
            return _answered(lambda: service.customer_brief(customer_id, write=True))
        except RuntimeError as exc:
            if type(exc).__name__ == "BriefUnavailable":
                raise HTTPException(status_code=424, detail=str(exc)) from exc
            if type(exc).__name__ == "LlmError":
                raise HTTPException(status_code=502, detail=f"Compass could not write the brief: {exc}") from exc
            raise

    # -- the seller's Compass features (operator, 2026-10-23) --------------------------

    @router.get("/customers/{customer_id}/memory")
    def get_memory(customer_id: str) -> list[dict]:
        return _answered(lambda: service.memory.of(service.customer(customer_id)["id"]))

    @router.post("/customers/{customer_id}/memory")
    def post_memory(customer_id: str, submitted: dict = Body(...)) -> list[dict]:
        """Something for Compass to remember about the customer (operator, 2026-10-23)."""
        return _answered(lambda: service.memory.add(service.customer(customer_id)["id"], str(submitted.get("said") or ""),
                                                    str(submitted.get("source") or "you")[:80]))

    @router.delete("/customers/{customer_id}/memory/{line_id}")
    def delete_memory(customer_id: str, line_id: str) -> list[dict]:
        return _answered(lambda: service.memory.remove(service.customer(customer_id)["id"], line_id))

    @router.get("/customers/{customer_id}/explain")
    def get_explain(customer_id: str, kind: str, name: str, accounts: str | None = None) -> dict:
        return _compass(lambda: advisor.explain(customer_id, kind, name, False, [a for a in (accounts or "").split(",") if a] or None))

    @router.post("/customers/{customer_id}/explain")
    def post_explain(customer_id: str, kind: str, name: str, accounts: str | None = None,
                     submitted: dict | None = Body(None)) -> dict:
        """Explains it again; `{"note": ...}` adds what the seller learned first."""
        return _compass(lambda: advisor.explain(customer_id, kind, name, True,
                                                [a for a in (accounts or "").split(",") if a] or None,
                                                (submitted or {}).get("note")))

    @router.get("/customers/{customer_id}/finops/plan")
    def get_finops_plan(customer_id: str, accounts: str | None = None) -> dict:
        return _compass(lambda: advisor.finops_plan(customer_id, False, _account_list(accounts)))

    @router.post("/customers/{customer_id}/finops/plan")
    def post_finops_plan(customer_id: str, accounts: str | None = None) -> dict:
        return _compass(lambda: advisor.finops_plan(customer_id, True, _account_list(accounts)))

    @router.get("/customers/{customer_id}/finops/report")
    def get_finops_report(customer_id: str, accounts: str | None = None) -> dict:
        return _compass(lambda: advisor.finops_report(customer_id, False, _account_list(accounts)))

    @router.post("/customers/{customer_id}/finops/report")
    def post_finops_report(customer_id: str, accounts: str | None = None) -> dict:
        return _compass(lambda: advisor.finops_report(customer_id, True, _account_list(accounts)))

    @router.get("/customers/{customer_id}/tags/plan")
    def get_tagging_plan(customer_id: str, accounts: str | None = None) -> dict:
        return _compass(lambda: advisor.tagging_plan(customer_id, False, _account_list(accounts)))

    @router.post("/customers/{customer_id}/tags/plan")
    def post_tagging_plan(customer_id: str, accounts: str | None = None) -> dict:
        return _compass(lambda: advisor.tagging_plan(customer_id, True, _account_list(accounts)))

    @router.get("/customers/{customer_id}/tags/guide")
    def get_tagging_guide(customer_id: str, accounts: str | None = None) -> dict:
        return _compass(lambda: advisor.tagging_guide(customer_id, False, _account_list(accounts)))

    @router.post("/customers/{customer_id}/tags/guide")
    def post_tagging_guide(customer_id: str, accounts: str | None = None) -> dict:
        return _compass(lambda: advisor.tagging_guide(customer_id, True, _account_list(accounts)))

    @router.get("/customers/{customer_id}/context")
    def get_context(customer_id: str) -> dict:
        return _answered(lambda: service.profile.of(service.customer(customer_id)["id"]))

    @router.put("/customers/{customer_id}/context")
    def put_context(customer_id: str, submitted: dict = Body(...)) -> dict:
        """Where the customer stands, as the seller knows it (operator, 2026-10-24)."""
        return _answered(lambda: service.profile.save(service.customer(customer_id)["id"], submitted.get("fields") or {}))

    @router.post("/customers/{customer_id}/context/draft")
    def draft_context(customer_id: str) -> dict:
        return _compass(lambda: advisor.draft_context(service.customer(customer_id)["id"]))

    @router.get("/customers/{customer_id}/use-case")
    def get_use_case(customer_id: str, pitch: str) -> dict:
        return _compass(lambda: advisor.use_case(customer_id, pitch))

    @router.post("/customers/{customer_id}/use-case")
    def post_use_case(customer_id: str, pitch: str) -> dict:
        return _compass(lambda: advisor.use_case(customer_id, pitch, write=True))

    @router.post("/customers/{customer_id}/use-case/publish")
    def publish_use_case(customer_id: str, pitch: str) -> dict:
        return _compass(lambda: advisor.publish_use_case(customer_id, pitch))

    @router.get("/pipeline/settings")
    def get_pipeline_settings() -> dict:
        return service.pipeline_review_settings()

    @router.put("/pipeline/settings")
    def put_pipeline_settings(changes: dict = Body(...)) -> dict:
        return _answered(lambda: service.save_pipeline_review_settings(changes))

    @router.get("/pipeline/snapshots")
    def get_pipeline_snapshots() -> dict:
        """The months snapshotted; opening it takes (or refreshes) the running month's."""
        return _answered(lambda: service.pipeline_snapshots())

    @router.get("/pipeline/review")
    def get_pipeline_review(level: str = "all", month: str | None = None) -> dict:
        """The monthly pipeline review at a level: all, am:<key>, segment:<name>, pss:<key>, customer:<id>."""
        return _answered(lambda: service.pipeline_review_report(level, month))

    @router.get("/pipeline/snapshots/{month}")
    def get_pipeline_snapshot(month: str) -> dict:
        return _answered(lambda: service.pipeline_snapshot_of(month))

    @router.post("/pipeline/snapshot")
    def post_pipeline_snapshot(force: bool = False) -> dict:
        """For a Hermes cron job at each month's end, and Settings' "Take snapshot now"
        (`force`: retake the running month's now)."""
        found = service.pipeline_snapshot(force=force)
        return {key: found.get(key) for key in ("month", "taken_at", "fitted_through", "gaps")} | {
            "opportunities": len(found.get("opportunities") or [])}

    @router.get("/compass/personas")
    def get_personas() -> dict:
        return advisor.personas()

    @router.put("/compass/personas/{persona_id}")
    def put_persona(persona_id: str, submitted: dict = Body(...)) -> dict:
        return _answered(lambda: {**advisor.personas(),
                                  "personas": service.personas.save(persona_id, str(submitted.get("prompt") or ""))})

    @router.delete("/compass/personas/{persona_id}")
    def delete_persona(persona_id: str) -> dict:
        return _answered(lambda: {**advisor.personas(), "personas": service.personas.reset(persona_id)})

    @router.post("/compass/personas/{persona_id}/generate")
    def generate_persona(persona_id: str, submitted: dict | None = Body(None)) -> dict:
        return _compass(lambda: advisor.generate_persona(persona_id, str((submitted or {}).get("wish") or "")))

    @router.get("/advisor/actions")
    def get_actions() -> dict:
        return _compass(advisor.actions)

    @router.post("/advisor/actions")
    def post_actions() -> dict:
        return _compass(lambda: advisor.actions(True))

    @router.get("/customers/{customer_id}/pitches")
    def get_pitches(customer_id: str) -> dict:
        return _compass(lambda: advisor.pitches(customer_id))

    @router.post("/customers/{customer_id}/pitches")
    def post_pitches(customer_id: str) -> dict:
        return _compass(lambda: advisor.pitches(customer_id, True))

    @router.post("/customers/{customer_id}/draft")
    def post_draft(customer_id: str, submitted: dict = Body(...)) -> dict:
        return _compass(lambda: advisor.draft(customer_id, str(submitted.get("pitch") or "")))

    @router.post("/solutions/{solution_id}/size")
    def post_size(solution_id: str, submitted: dict = Body(...)) -> dict:
        return _compass(lambda: advisor.size(solution_id, str(submitted.get("answers") or ""), submitted.get("customer")))

    @router.post("/ask")
    def post_ask(submitted: dict = Body(...)) -> dict:
        return _compass(lambda: advisor.ask(str(submitted.get("question") or "")))

    @router.get("/guide/marketplace")
    def get_marketplace_classes() -> dict:
        return _compass(advisor.marketplace)

    @router.post("/guide/marketplace")
    def post_marketplace_classes() -> dict:
        return _compass(lambda: advisor.marketplace(True))

    @router.get("/solutions/placements")
    def get_placements(customer: str | None = None) -> dict:
        return _answered(lambda: service.placements(customer))

    @router.post("/solutions/placements")
    def post_placements(customer: str | None = None, limit: int = 24) -> dict:
        """Asks Compass about the largest unplaced subscriptions not yet asked about."""
        try:
            return _answered(lambda: service.place(customer, limit))
        except RuntimeError as exc:
            if type(exc).__name__ == "BriefUnavailable":
                raise HTTPException(status_code=424, detail=str(exc)) from exc
            if type(exc).__name__ == "LlmError":
                raise HTTPException(status_code=502, detail=f"Compass could not answer: {exc}") from exc
            raise

    @router.get("/solutions/proposals/note")
    def get_proposal_note(name: str) -> dict:
        return _answered(lambda: service.proposal_note(name))

    @router.get("/customers/{customer_id}/drill")
    def get_customer_drill(customer_id: str, kind: str, name: str, accounts: str | None = None) -> dict:
        return _answered(lambda: service.drill(customer_id, kind, name,
                                               [a for a in (accounts or "").split(",") if a] or None))

    @router.get("/customers/{customer_id}/solutions")
    def get_customer_solutions(customer_id: str, accounts: str | None = None) -> dict:
        return _answered(lambda: service.solutions_of(customer_id, _account_list(accounts)))

    @router.get("/data/export.zip")
    def get_data_export() -> Response:
        """Every data file, for another machine: no sync needed there."""
        name, archive = _answered(service.export_data)
        return Response(archive, media_type="application/zip",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})

    @router.post("/data/import")
    async def post_data_import(file: UploadFile = File(...)) -> dict:
        """Replaces this machine's data with an export's. Refused while a sync runs:
        it would write its own cache back over the import."""
        if sync.status()["running"]:
            raise HTTPException(status_code=409, detail="A sync is running; import once it has finished.")
        content = await file.read()
        return _answered(lambda: service.import_data(content))

    @router.get("/quota/settings")
    def get_quota_settings() -> dict:
        return _answered(service.quota_settings)

    @router.put("/quota/settings")
    def put_quota_settings(changes: dict = Body(...)) -> dict:
        """Any of baseline_start (YYYY-MM or null for the default), baseline_months,
        fy_start_month and quota."""
        return _answered(lambda: service.save_quota_settings(changes))

    @router.get("/quota")
    def get_quota(marketplace: str = "core42", credits: bool = True) -> dict:
        """Every customer above the baseline, and the quota's attainment."""
        return _answered(lambda: service.quota_across(measure(marketplace, credits)))

    @router.get("/customers/{customer_id}/quota")
    def get_customer_quota(customer_id: str, marketplace: str = "core42", credits: bool = True,
                           accounts: str | None = None) -> dict:
        return _answered(lambda: service.quota_customer(customer_id, measure(marketplace, credits), _account_list(accounts)))

    @router.get("/reports/{report}/export.xlsx")
    def get_report_export(report: str, marketplace: str = "true", credits: bool = True) -> Response:
        """growth, whitespace, marketplace-whitespace, hygiene, renewals or quota, as a workbook."""
        name, workbook = _answered(lambda: service.export_report(report, measure(marketplace, credits)))
        return Response(workbook, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})

    @router.get("/marketplace/export.xlsx")
    def get_marketplace_export(first_month: str | None = None, last_month: str | None = None) -> Response:
        name, workbook = _answered(lambda: service.export_marketplace(first_month, last_month))
        return Response(workbook, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})

    @router.put("/customers/{customer_id}/scenario")
    def put_scenario(customer_id: str, settings: dict = Body(...)) -> dict:
        return _answered(lambda: book.set_scenario(customer_id, settings))

    @router.get("/entity-customers")
    def get_entity_customers() -> dict:
        """The Customer notes a customer can be linked to, or why there are none."""
        try:
            return {"available": True, "customers": pipeline.entity_customers(),
                    "commitments_on_notes": book.commitments_on_notes()}
        except PipelineUnavailable as exc:
            return {"available": False, "reason": str(exc), "customers": [], "commitments_on_notes": False}

    @router.get("/customers/{customer_id}/pipeline")
    def get_pipeline(customer_id: str) -> dict:
        return _answered(lambda: service.pipeline(customer_id))

    @router.post("/customers/{customer_id}/opportunities")
    def post_opportunity(customer_id: str, opportunity: dict = Body(...)) -> dict:
        found = _answered(lambda: pipeline.create(
            service.customer(customer_id), opportunity.get("owner_stem") or service.customer(customer_id)["entity_customer"],
            (opportunity.get("title") or "").strip(), opportunity.get("fields") or {}, opportunity.get("plan") or [],
            opportunity.get("sections")))
        service.pipeline_changed()
        return found

    @router.put("/opportunities/{opportunity_id}")
    def put_opportunity(opportunity_id: str, change: dict = Body(...)) -> dict:
        found = _answered(lambda: pipeline.update(opportunity_id, change.get("fields") or {}, change.get("plan")))
        service.pipeline_changed()
        return found

    @router.get("/sign-in")
    def get_sign_in() -> dict:
        try:
            token.get()
        except AzureSignInError as exc:
            return {"signed_in": False, "message": str(exc)}
        return {"signed_in": True, "message": None}

    @router.get("/billing-accounts")
    def get_billing_accounts(fresh: bool = False) -> list[dict]:
        in_customer = {account["name"]: customer["id"] for customer in book.list()
                       for account in customer["accounts"]}
        return _answered(lambda: [{**account, "customer": in_customer.get(account["name"])}
                                  for account in directory.accounts(fresh=fresh)])

    @router.get("/unassigned")
    def get_unassigned() -> list[dict]:
        """Enrollments in no customer, grouped, biggest first -- the customers to add."""
        return _answered(lambda: service.unassigned(directory.accounts()))

    @router.get("/commitment-types")
    def get_commitment_types() -> list[str]:
        return list(COMMITMENT_TYPES)

    @router.get("/customers")
    def get_customers() -> list[dict]:
        return _answered(book.list)

    @router.post("/customers")
    def post_customer(customer: dict = Body(...)) -> dict:
        return _answered(lambda: book.save(None, customer))

    @router.put("/customers/{customer_id}")
    def put_customer(customer_id: str, customer: dict = Body(...)) -> dict:
        return _answered(lambda: book.save(customer_id, customer))

    @router.post("/entity-customers/{customer_stem}/affiliates")
    def post_affiliate(customer_stem: str, affiliate: dict = Body(...)) -> dict:
        """A new affiliate note under a Customer, written by the Entities plugin."""
        return _answered(lambda: pipeline.create_affiliate(customer_stem, (affiliate.get("name") or "").strip()))

    @router.delete("/customers/{customer_id}")
    def delete_customer(customer_id: str) -> dict:
        _answered(lambda: book.delete(customer_id))
        return {"deleted": customer_id}

    @router.get("/portfolio")
    def get_portfolio() -> list[dict]:
        return service.portfolio()

    @router.get("/customers/{customer_id}/analysis")
    def get_analysis(customer_id: str, marketplace: str = "true", credits: bool = True, view: str = "account",
                     billing_day: int | None = None, accounts: str | None = None) -> dict:
        """`accounts`: comma-separated enrollment numbers to show; empty shows all."""
        return _answered(lambda: service.analysis(customer_id, measure(marketplace, credits, billing_day), view,
                                                  _account_list(accounts)))

    @router.get("/customers/{customer_id}/finops")
    def get_finops(customer_id: str, accounts: str | None = None) -> dict:
        return _answered(lambda: service.finops(customer_id, _account_list(accounts)))

    @router.get("/customers/{customer_id}/this-month")
    def get_this_month(customer_id: str, accounts: str | None = None) -> dict:
        return _answered(lambda: service.this_month(customer_id, _account_list(accounts)))

    @router.post("/sync/this-month")
    def post_sync_this_month(customer: str | None = None) -> dict:
        """This month and last, by day -- only when asked."""
        return sync.start_this_month(customer)

    @router.get("/customers/{customer_id}/tags")
    def get_tags(customer_id: str, accounts: str | None = None) -> dict:
        return _answered(lambda: service.tags(customer_id, _account_list(accounts)))

    @router.get("/tags")
    def get_tags_across() -> list[dict]:
        return service.tags_across()

    @router.post("/sync/forecasts")
    def post_sync_forecasts(customer: str | None = None) -> dict:
        """Azure's forecasts only -- the whole bill's and Azure usage's -- without a full sync."""
        return sync.start_forecasts(customer)

    @router.post("/sync/tags")
    def post_sync_tags(customer: str | None = None) -> dict:
        """Cost by tag only, without a full sync."""
        return sync.start_tags(customer)

    @router.get("/finops/digest")
    def get_finops_digest() -> dict:
        """The week's FinOps as text, for a Hermes job to send to the operator."""
        return service.finops_digest()

    @router.post("/finops/prices")
    def post_finops_prices() -> dict:
        """Prices the steady candidates now, rather than after the next sync."""
        return _answered(service.refresh_prices)

    @router.put("/finops/pricing-region")
    def put_pricing_region(change: dict = Body(...)) -> dict:
        """The Azure region candidates are priced in (``uaenorth`` unless set)."""
        return _answered(lambda: service.set_pricing_region(str(change.get("region") or "")))

    @router.get("/finops")
    def get_finops_across() -> list[dict]:
        """Every customer's FinOps at a glance -- the operator's view only."""
        return service.finops_across()

    @router.get("/customers/{customer_id}/consumption")
    def get_consumption(customer_id: str, first_month: str | None = None, last_month: str | None = None,
                        group: str = "service", cost: str = "actual", accounts: str | None = None) -> dict:
        return _answered(lambda: service.consumption(customer_id, first_month, last_month, group, cost,
                                                     _account_list(accounts)))

    @router.get("/customers/{customer_id}/focus/options")
    def get_focus_options(customer_id: str, accounts: str | None = None) -> dict:
        return _answered(lambda: service.focus_options(customer_id, _account_list(accounts)))

    @router.get("/customers/{customer_id}/focus/kept")
    def get_focus_kept(customer_id: str) -> list[dict]:
        return _answered(lambda: advisor.focus_kept(customer_id))

    @router.post("/customers/{customer_id}/focus")
    def post_focus(customer_id: str, request: dict = Body(...), accounts: str | None = None) -> dict:
        """`{focus: {groups, subscriptions, services}, write, prompt}`: the slice's figures and the
        kept analysis; `write` asks Compass for a new one, steered by `prompt`."""
        return _compass(lambda: advisor.focus(customer_id, request.get("focus") or {}, bool(request.get("write")),
                                              _account_list(accounts), request.get("prompt")))

    @router.get("/customers/{customer_id}/subscription-groups")
    def get_subscription_groups(customer_id: str, only_service: str | None = Query(None, alias="service"),
                                accounts: str | None = None) -> dict:
        """Each named group of subscriptions, per month -- all services or just `service`."""
        return _answered(lambda: service.subscription_groups(customer_id, only_service, _account_list(accounts)))

    @router.put("/customers/{customer_id}/subscription-groups")
    def put_subscription_groups(customer_id: str, groups: list = Body(...)) -> list[dict]:
        return _answered(lambda: book.set_subscription_groups(customer_id, groups))

    @router.get("/hygiene")
    def get_hygiene() -> list[dict]:
        """Subscriptions and tag coverage for every customer."""
        return _answered(service.hygiene_across)

    @router.get("/whitespace")
    def get_whitespace() -> list[dict]:
        """Common services each customer does not use yet."""
        return _answered(service.whitespace_across)

    @router.get("/growth")
    def get_growth() -> list[dict]:
        """Growth and churn signals for every customer."""
        return _answered(service.growth_across)

    @router.get("/solution-plays")
    def get_solution_plays() -> dict:
        """Every service seen, its spend and solution play, for Settings."""
        return _answered(service.solution_plays_settings)

    @router.put("/solution-plays")
    def put_solution_play(change: dict = Body(...)) -> dict:
        """`{service, play}`; a null play puts the service back to its default."""
        return _answered(lambda: service.set_solution_play((change.get("service") or "").strip(), change.get("play")))

    @router.post("/sync")
    def post_sync(customer: str | None = None, profiles: str = "none") -> dict:
        """Starts the sync and returns at once: every customer, or one; with
        `profiles=also` then every other billing profile (invoice totals and
        Marketplace only), or `profiles=only` just those."""
        return _answered(lambda: sync.start(customer, profiles))

    @router.get("/sync")
    def get_sync() -> dict:
        return sync.status()

    @router.get("/sync/log")
    def get_sync_log() -> dict:
        """The last runs, newest first: scope, outcome, requests, pages, waits, errors."""
        return {"runs": log.runs() if log else []}

    @router.get("/sync/log/{run_id}")
    def get_sync_run(run_id: str, last: int = 200) -> dict:
        """One run with its newest `last` events; `latest` is the newest run."""
        found = log.events(None if run_id == "latest" else run_id, max(1, min(last, 1500))) if log else None
        if found is None:
            raise HTTPException(status_code=404, detail="No such sync run.")
        return found

    return router
