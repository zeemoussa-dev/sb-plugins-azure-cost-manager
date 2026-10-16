"""The Azure Cost Manager's HTTP surface. The host mounts it under `/plugins/azure-cost-manager/`."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from .azure_token import AzureCliToken, AzureSignInError
from .billing_client import AzureApiError, AzureThrottled
from .consumption_service import AccountNotTracked, ConsumptionService


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
    except AccountNotTracked as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def build_router(service: ConsumptionService, token: AzureCliToken) -> APIRouter:
    router = APIRouter()

    @router.get("/sign-in")
    def get_sign_in() -> dict:
        try:
            token.get()
        except AzureSignInError as exc:
            return {"signed_in": False, "message": str(exc)}
        return {"signed_in": True, "message": None}

    @router.get("/billing-accounts")
    def get_billing_accounts() -> list[dict]:
        return _answered(service.visible_billing_accounts)

    @router.get("/tracked")
    def get_tracked() -> list[dict]:
        return _answered(service.tracked_accounts)

    @router.put("/tracked")
    def put_tracked(account_names: list[str] = Body(..., embed=True)) -> list[dict]:
        return _answered(lambda: service.set_tracked(account_names))

    @router.post("/tracked/{account_name}/refresh")
    def post_refresh(account_name: str) -> dict:
        return _answered(lambda: service.refresh(account_name))

    @router.get("/tracked/{account_name}/analysis")
    def get_analysis(account_name: str) -> dict:
        return _answered(lambda: service.analysis(account_name))

    @router.get("/tracked/{account_name}/consumption")
    def get_consumption(account_name: str, first_month: str | None = None, last_month: str | None = None,
                        group: str = "service", cost: str = "actual") -> dict:
        return _answered(lambda: service.consumption(account_name, first_month, last_month, group, cost))

    return router
