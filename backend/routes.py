"""The Azure Cost Manager's HTTP surface. The host mounts it under `/plugins/azure-cost-manager/`.

Reading a customer never calls Azure; `POST /sync` is the one route that does,
and it only starts the background sync. The weekly Hermes job calls it.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from .azure_token import AzureCliToken, AzureSignInError
from .billing_client import AzureApiError, AzureThrottled
from .consumption_service import ConsumptionService, CustomerNotFound
from .consumption_sync import ConsumptionSync
from .customers import COMMITMENT_TYPES, AccountDirectory, CustomerBook, CustomerError


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
    except (CustomerError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def build_router(service: ConsumptionService, book: CustomerBook, directory: AccountDirectory,
                 sync: ConsumptionSync, token: AzureCliToken) -> APIRouter:
    router = APIRouter()

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

    @router.delete("/customers/{customer_id}")
    def delete_customer(customer_id: str) -> dict:
        _answered(lambda: book.delete(customer_id))
        return {"deleted": customer_id}

    @router.get("/customers/{customer_id}/analysis")
    def get_analysis(customer_id: str) -> dict:
        return _answered(lambda: service.analysis(customer_id))

    @router.get("/customers/{customer_id}/consumption")
    def get_consumption(customer_id: str, first_month: str | None = None, last_month: str | None = None,
                        group: str = "service", cost: str = "actual") -> dict:
        return _answered(lambda: service.consumption(customer_id, first_month, last_month, group, cost))

    @router.post("/sync")
    def post_sync(customer: str | None = None) -> dict:
        """Starts the sync -- every customer, or one -- and returns at once."""
        return sync.start(customer)

    @router.get("/sync")
    def get_sync() -> dict:
        return sync.status()

    return router
