from fastapi import Header

from api.security import resolve_mobile_tenant


def current_tenant_id(
    authorization: str = Header(default="", alias="Authorization"),
    x_mobile_api_key: str = Header(default="", alias="X-Mobile-Api-Key"),
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
):
    return resolve_mobile_tenant(api_key=x_mobile_api_key, tenant_id=x_tenant_id, authorization=authorization)
