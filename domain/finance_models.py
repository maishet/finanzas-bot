from dataclasses import dataclass

from utils.finance_format import get_field, normalize_text, parse_date, parse_number


def normalize_transaction_type(value):
    normalized = normalize_text(value)
    if normalized in {"ingreso", "income"}:
        return "income"
    if normalized in {"gasto", "expense"}:
        return "expense"
    return normalized or "expense"


def normalize_account_type(value):
    normalized = normalize_text(value)
    if "efectivo" in normalized or "cash" in normalized:
        return "cash"
    if "credito" in normalized or "credit" in normalized or "tarjeta" in normalized:
        return "credit_card"
    return "bank_account" if normalized else "other"


def normalize_status(value, default="active"):
    normalized = normalize_text(value)
    if normalized in {"activo", "active"}:
        return "active"
    if normalized in {"pagado", "paid"}:
        return "paid"
    if normalized in {"pendiente", "pending"}:
        return "pending"
    if normalized in {"confirmado", "confirmed"}:
        return "confirmed"
    if normalized in {"descartado", "discarded"}:
        return "discarded"
    return normalized or default


@dataclass(frozen=True)
class AccountRecord:
    name: str
    account_type: str
    balance: float
    currency: str

    @classmethod
    def from_legacy(cls, row):
        return cls(
            name=str(row.get("nombre", row.get("Nombre", ""))).strip(),
            account_type=normalize_account_type(row.get("tipo", row.get("Tipo", ""))),
            balance=round(parse_number(row.get("saldo", row.get("SaldoActual", 0))), 2),
            currency=str(row.get("moneda", row.get("Moneda", "PEN"))).strip().upper() or "PEN",
        )

    def to_mobile_payload(self):
        return {"nombre": self.name, "tipo": self.account_type, "saldo": self.balance, "moneda": self.currency}


@dataclass(frozen=True)
class TransactionRecord:
    transaction_id: str
    transaction_date: str
    transaction_type: str
    amount: float
    currency: str
    category: str
    subcategory: str
    account: str
    payment_method: str
    note: str
    debt_id: str

    @classmethod
    def from_legacy(cls, row):
        raw_date = row.get("Fecha", "")
        parsed_date = parse_date(raw_date)
        return cls(
            transaction_id=str(row.get("ID", "")).strip(),
            transaction_date=parsed_date.isoformat(timespec="seconds") if parsed_date else str(raw_date or ""),
            transaction_type=normalize_transaction_type(row.get("Tipo", "")),
            amount=round(parse_number(row.get("Monto", 0)), 2),
            currency=str(row.get("Moneda", "PEN")).strip().upper() or "PEN",
            category=str(get_field(row, "Categoría", "Categoria", default="")).strip(),
            subcategory=str(get_field(row, "Subcategoría", "Subcategoria", default="")).strip(),
            account=str(row.get("Cuenta", "")).strip(),
            payment_method=str(get_field(row, "Método", "Metodo", default="")).strip(),
            note=str(row.get("Nota", "")).strip(),
            debt_id=str(row.get("DeudaID", "")).strip(),
        )

    def to_mobile_payload(self):
        return {
            "id": self.transaction_id,
            "fecha": self.transaction_date,
            "tipo": "Ingreso" if self.transaction_type == "income" else "Gasto",
            "monto": self.amount,
            "moneda": self.currency,
            "categoria": self.category,
            "subcategoria": self.subcategory,
            "cuenta": self.account,
            "metodo": self.payment_method,
            "nota": self.note,
            "deuda_id": self.debt_id,
        }


@dataclass(frozen=True)
class DebtRecord:
    debt_id: str
    description: str
    outstanding_amount: float
    currency: str
    due_date: str
    account: str
    status: str

    @classmethod
    def from_legacy(cls, row):
        return cls(
            debt_id=str(row.get("id", row.get("ID", ""))).strip(),
            description=str(row.get("descripcion", row.get("Descripcion", ""))).strip(),
            outstanding_amount=round(parse_number(row.get("pendiente", row.get("Pendiente", 0))), 2),
            currency=str(row.get("moneda", row.get("Moneda", "PEN"))).strip().upper() or "PEN",
            due_date=str(row.get("vencimiento", row.get("FechaVencimiento", ""))).strip(),
            account=str(row.get("cuenta", row.get("Cuenta", ""))).strip(),
            status=normalize_status(row.get("estado", row.get("Estado", ""))),
        )

    def to_mobile_payload(self):
        return {"id": self.debt_id, "descripcion": self.description, "pendiente": self.outstanding_amount, "moneda": self.currency, "vencimiento": self.due_date, "cuenta": self.account, "estado": self.status}


@dataclass(frozen=True)
class PendingMovementRecord:
    pending_id: str
    detected_at: str
    source: str
    account: str
    transaction_type: str
    amount: float
    currency: str
    description: str
    reference: str
    status: str
    confidence: str
    transaction_id: str
    observation: str

    @classmethod
    def from_legacy(cls, row):
        return cls(
            pending_id=str(row.get("ID", "")).strip(),
            detected_at=str(row.get("FechaDetectada", "")).strip(),
            source=str(row.get("Fuente", "")).strip(),
            account=str(row.get("Cuenta", "")).strip(),
            transaction_type=normalize_transaction_type(row.get("Tipo", "")),
            amount=round(parse_number(row.get("Monto", 0)), 2),
            currency=str(row.get("Moneda", "PEN")).strip().upper() or "PEN",
            description=str(row.get("Descripcion", "")).strip(),
            reference=str(row.get("Referencia", "")).strip(),
            status=normalize_status(row.get("Estado", ""), default="pending"),
            confidence=str(row.get("Confianza", "")).strip(),
            transaction_id=str(row.get("TXID", "")).strip(),
            observation=str(row.get("Observacion", "")).strip(),
        )

    def to_mobile_payload(self):
        return {
            "id": self.pending_id,
            "fecha_detectada": self.detected_at,
            "fuente": self.source,
            "cuenta": self.account,
            "tipo": "Ingreso" if self.transaction_type == "income" else "Gasto",
            "monto": self.amount,
            "moneda": self.currency,
            "descripcion": self.description,
            "referencia": self.reference,
            "estado": self.status,
            "confianza": self.confidence,
            "txid": self.transaction_id,
            "observacion": self.observation,
        }
