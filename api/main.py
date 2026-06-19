from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import config
from api.dependencies import current_tenant_id
from api.mobile_service import (
    get_accounts_payload,
    get_debts_payload,
    get_me_payload,
    get_pending_movements_payload,
    get_summary_payload,
    get_transactions_payload,
    get_version_payload,
)
from api.security import MobileAPIError


def create_app():
    app = FastAPI(title="Finanzas Bot Mobile API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.MOBILE_API_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Mobile-Api-Key", "X-Tenant-ID"],
    )

    @app.exception_handler(MobileAPIError)
    async def mobile_api_error_handler(_, exc):
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/api/version")
    def version():
        return get_version_payload()

    @app.get("/api/me")
    def me(tenant_id: str = Depends(current_tenant_id)):
        return {"ok": True, "data": get_me_payload(tenant_id)}

    @app.get("/api/accounts")
    def accounts(tenant_id: str = Depends(current_tenant_id)):
        return {"ok": True, "data": get_accounts_payload(tenant_id)}

    @app.get("/api/summary")
    def summary(tenant_id: str = Depends(current_tenant_id)):
        return {"ok": True, "data": get_summary_payload(tenant_id)}

    @app.get("/api/transactions")
    def transactions(limit: int = Query(default=50, ge=1, le=200), tenant_id: str = Depends(current_tenant_id)):
        return {"ok": True, "data": get_transactions_payload(tenant_id, limit=limit)}

    @app.get("/api/debts")
    def debts(tenant_id: str = Depends(current_tenant_id)):
        return {"ok": True, "data": get_debts_payload(tenant_id)}

    @app.get("/api/pending-movements")
    def pending_movements(limit: int = Query(default=50, ge=1, le=200), tenant_id: str = Depends(current_tenant_id)):
        return {"ok": True, "data": get_pending_movements_payload(tenant_id, limit=limit)}

    return app


app = create_app()
