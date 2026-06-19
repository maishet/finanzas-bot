from fastapi import Header

from api.security import require_tenant_header, validate_mobile_api_key


def current_tenant_id(
    x_mobile_api_key: str = Header(default="", alias="X-Mobile-Api-Key"),
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
):
    validate_mobile_api_key(x_mobile_api_key)
    return require_tenant_header(x_tenant_id)
