from typing import List, Optional, Union

from pydantic import BaseModel


class VersionResponse(BaseModel):
    ok: bool
    name: str
    version: str
    phase: str
    auth: str


class MeResponse(BaseModel):
    tenant_id: str
    telegram_user_id: str
    nombre: str
    estado: str
    rol: str
    setup_completo: bool
    gmail_enabled: bool
    voice_enabled: bool


class AccountResponse(BaseModel):
    nombre: str
    tipo: str
    saldo: float
    moneda: str


class TransactionResponse(BaseModel):
    id: str
    fecha: str
    tipo: str
    monto: float
    moneda: str
    categoria: str
    subcategoria: str
    cuenta: str
    metodo: str
    nota: str
    deuda_id: str


class DebtResponse(BaseModel):
    id: str
    descripcion: str
    pendiente: float
    moneda: str
    vencimiento: str
    cuenta: str
    estado: str


class PendingMovementResponse(BaseModel):
    id: str
    fecha_detectada: str
    fuente: str
    cuenta: str
    tipo: str
    monto: float
    moneda: str
    descripcion: str
    referencia: str
    estado: str
    confianza: str
    txid: str
    observacion: str


class AccountsResponse(BaseModel):
    ok: bool = True
    data: List[AccountResponse]


class TransactionsResponse(BaseModel):
    ok: bool = True
    data: List[TransactionResponse]


class DebtsResponse(BaseModel):
    ok: bool = True
    data: List[DebtResponse]


class PendingMovementsResponse(BaseModel):
    ok: bool = True
    data: List[PendingMovementResponse]


class ErrorResponse(BaseModel):
    ok: bool = False
    error: str
    message: str


class RequestCodeRequest(BaseModel):
    telegram_user_id: str


class RequestCodeResponseData(BaseModel):
    telegram_user_id: str
    tenant_id: str
    expires_in_minutes: int
    delivery: str


class VerifyCodeRequest(BaseModel):
    telegram_user_id: str
    code: str


class VerifyCodeResponseData(BaseModel):
    access_token: str
    token_type: str
    expires_in_hours: int
    tenant_id: str
    telegram_user_id: str
    rol: str


class CreateTransactionRequest(BaseModel):
    tipo: str
    monto: float
    moneda: str = "PEN"
    categoria: str
    subcategoria: str = ""
    cuenta: str = "Efectivo"
    metodo: str = "Efectivo"
    nota: str = ""
    fecha: Optional[str] = None


class UpdateTransactionRequest(BaseModel):
    campo: str
    valor: Union[str, float]


class PayDebtRequest(BaseModel):
    monto: float
    moneda: str = "PEN"
    cuenta: str
    nota: str = ""


class ConfirmPendingMovementRequest(BaseModel):
    categoria: str
    nota: str = ""


class DiscardPendingMovementRequest(BaseModel):
    motivo: str = ""


class CreateSnapshotRequest(BaseModel):
    origen: str = "Mobile"
    fecha: Optional[str] = None
