from datetime import date, datetime
from typing import Any, Callable

import config
from utils.finance_format import normalize_text, parse_date, parse_number


def _optional_psycopg_connect(database_url: str):
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg is required to use PostgresFinanceRepository") from exc
    return psycopg.connect(database_url)


def _legacy_transaction_type(value: str) -> str:
    return "Ingreso" if value == "income" else "Gasto"


def _normalized_transaction_type(value: str) -> str:
    normalized = normalize_text(value)
    if normalized in {"ingreso", "income"}:
        return "income"
    return "expense"


def _legacy_status(value: str) -> str:
    if value == "active":
        return "Activo"
    if value == "paid":
        return "Pagado"
    if value == "pending":
        return "Pendiente"
    if value == "confirmed":
        return "Confirmado"
    if value == "discarded":
        return "Descartado"
    return value or ""


def _date_value(value: Any) -> date:
    parsed = parse_date(value)
    if isinstance(parsed, datetime):
        return parsed.date()
    if isinstance(value, date):
        return value
    return date.today()


def _value(row: Any, key: str, index: int | None = None, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    if index is not None:
        try:
            return row[index]
        except (IndexError, TypeError):
            return default
    return default


class PostgresFinanceRepository:
    def __init__(self, database_url: str | None = None, connection_factory: Callable[[], Any] | None = None):
        self.database_url = database_url or config.SUPABASE_DATABASE_URL
        self.connection_factory = connection_factory or self._connect

    def _connect(self):
        if not self.database_url:
            raise RuntimeError("SUPABASE_DATABASE_URL or DATABASE_URL is required to use PostgresFinanceRepository")
        return _optional_psycopg_connect(self.database_url)

    def _fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
        with self.connection_factory() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return list(cursor.fetchall())

    def _fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        rows = self._fetchall(sql, params)
        return rows[0] if rows else None

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        with self.connection_factory() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                try:
                    result = cursor.fetchone()
                except Exception:
                    result = None
            if hasattr(conn, "commit"):
                conn.commit()
        return result

    def _tenant_uuid(self, tenant_id: str) -> str:
        row = self._fetchone("select id from tenants where legacy_tenant_id = %s or id::text = %s", (tenant_id, tenant_id))
        if not row:
            raise ValueError(f"tenant not found: {tenant_id}")
        return str(_value(row, "id", 0))

    def _audit(self, cursor, tenant_uuid: str, action: str, entity_type: str, entity_id: Any, metadata: str = "{}"):
        cursor.execute(
            "insert into audit_logs (tenant_id, action, entity_type, entity_id, metadata) values (%s, %s, %s, %s, %s::jsonb)",
            (tenant_uuid, action, entity_type, entity_id, metadata),
        )

    def _account_id(self, cursor, tenant_uuid: str, account_name: str) -> Any:
        if not account_name:
            return None
        cursor.execute("select id from accounts where tenant_id = %s and name = %s and status = 'active' limit 1", (tenant_uuid, account_name))
        row = cursor.fetchone()
        return _value(row, "id", 0) if row else None

    def _category_id(self, cursor, tenant_uuid: str, category_name: str, transaction_type: str) -> Any:
        name = category_name or "Other"
        cursor.execute("select id from categories where tenant_id = %s and lower(name) = lower(%s) and transaction_type = %s limit 1", (tenant_uuid, name, transaction_type))
        row = cursor.fetchone()
        if row:
            return _value(row, "id", 0)
        cursor.execute("insert into categories (tenant_id, name, transaction_type, is_active) values (%s, %s, %s, true) returning id", (tenant_uuid, name, transaction_type))
        return _value(cursor.fetchone(), "id", 0)

    def _apply_account_delta(self, cursor, tenant_uuid: str, account_id: Any, transaction_type: str, amount: float, reverse: bool = False):
        if not account_id:
            return
        delta = amount if transaction_type == "income" else -amount
        if reverse:
            delta = -delta
        cursor.execute("update accounts set current_balance = current_balance + %s, updated_at = now() where tenant_id = %s and id = %s", (delta, tenant_uuid, account_id))

    def get_accounts_summary(self, tenant_id: str) -> dict[str, Any]:
        tenant_uuid = self._tenant_uuid(tenant_id)
        rows = self._fetchall(
            """
            select name, account_type, currency, current_balance
            from accounts
            where tenant_id = %s and status = 'active'
            order by name
            """,
            (tenant_uuid,),
        )
        accounts = []
        total_assets = 0.0
        total_liabilities = 0.0
        for row in rows:
            balance = parse_number(_value(row, "current_balance", 3, 0))
            account_type = str(_value(row, "account_type", 1, "other"))
            accounts.append({"nombre": _value(row, "name", 0, ""), "tipo": account_type, "saldo": balance, "moneda": _value(row, "currency", 2, "PEN")})
            if account_type not in {"credit_card", "loan"} and balance >= 0:
                total_assets += balance
        return {"cuentas": accounts, "total_activos": total_assets, "total_pasivos": total_liabilities, "patrimonio": total_assets - total_liabilities}

    def get_month_balance(self, month: int, year: int, tenant_id: str) -> dict[str, Any]:
        tenant_uuid = self._tenant_uuid(tenant_id)
        row = self._fetchone(
            """
            select
              coalesce(sum(case when transaction_type = 'income' then amount else 0 end), 0) as income,
              coalesce(sum(case when transaction_type = 'expense' then amount else 0 end), 0) as expenses
            from transactions
            where tenant_id = %s
              and status = 'posted'
              and extract(month from transaction_date) = %s
              and extract(year from transaction_date) = %s
            """,
            (tenant_uuid, month, year),
        )
        income = parse_number(_value(row, "income", 0, 0)) if row else 0.0
        expenses = parse_number(_value(row, "expenses", 1, 0)) if row else 0.0
        return {"mes": month, "año": year, "ingresos": income, "gastos": expenses, "ahorro": income - expenses}

    def list_active_debts(self, tenant_id: str) -> list[dict[str, Any]]:
        tenant_uuid = self._tenant_uuid(tenant_id)
        rows = self._fetchall(
            """
            select d.id, d.description, d.outstanding_amount, d.currency, d.due_date, coalesce(a.name, '') as account_name, d.status
            from debts d
            left join accounts a on a.id = d.account_id
            where d.tenant_id = %s and d.status in ('active', 'overdue')
            order by d.due_date nulls last, d.created_at desc
            """,
            (tenant_uuid,),
        )
        return [
            {
                "id": str(_value(row, "id", 0, "")),
                "descripcion": _value(row, "description", 1, ""),
                "pendiente": parse_number(_value(row, "outstanding_amount", 2, 0)),
                "moneda": _value(row, "currency", 3, "PEN"),
                "vencimiento": str(_value(row, "due_date", 4, "") or ""),
                "cuenta": _value(row, "account_name", 5, ""),
                "estado": _legacy_status(str(_value(row, "status", 6, "active"))),
            }
            for row in rows
        ]

    def list_transactions(self, tenant_id: str) -> list[dict[str, Any]]:
        tenant_uuid = self._tenant_uuid(tenant_id)
        rows = self._fetchall(
            """
            select t.id, t.transaction_date, t.transaction_type, t.amount, t.currency, coalesce(c.name, '') as category_name,
                   coalesce(a.name, '') as account_name, coalesce(t.payment_method, ''), coalesce(t.note, ''), coalesce(t.debt_id::text, '')
            from transactions t
            left join categories c on c.id = t.category_id
            left join accounts a on a.id = t.account_id
            where t.tenant_id = %s and t.status = 'posted'
            order by t.transaction_date desc, t.created_at desc
            """,
            (tenant_uuid,),
        )
        return [
            {
                "ID": str(_value(row, "id", 0, "")),
                "Fecha": str(_value(row, "transaction_date", 1, "")),
                "Tipo": _legacy_transaction_type(str(_value(row, "transaction_type", 2, "expense"))),
                "Monto": parse_number(_value(row, "amount", 3, 0)),
                "Moneda": _value(row, "currency", 4, "PEN"),
                "Categoría": _value(row, "category_name", 5, ""),
                "Cuenta": _value(row, "account_name", 6, ""),
                "Método": _value(row, "payment_method", 7, ""),
                "Nota": _value(row, "note", 8, ""),
                "DeudaID": _value(row, "debt_id", 9, ""),
            }
            for row in rows
        ]

    def list_categories(self, tenant_id: str, category_type: str | None = None) -> list[dict[str, Any]]:
        tenant_uuid = self._tenant_uuid(tenant_id)
        normalized_type = _normalized_transaction_type(category_type) if category_type else None
        rows = self._fetchall(
            """
            select name, transaction_type, icon
            from categories
            where tenant_id = %s and is_active = true and (%s::text is null or transaction_type = %s)
            order by name
            """,
            (tenant_uuid, normalized_type, normalized_type),
        )
        return [{"original": _value(row, "name", 0, ""), "tipo": _legacy_transaction_type(str(_value(row, "transaction_type", 1, "expense"))), "subcategorias": "", "icono": _value(row, "icon", 2, "")} for row in rows]

    def create_category_if_missing(self, tenant_id: str, name: str, category_type: str, subcategories: str = "") -> dict[str, Any]:
        tenant_uuid = self._tenant_uuid(tenant_id)
        normalized_type = _normalized_transaction_type(category_type)
        existing = self._fetchone(
            """
            select name, transaction_type
            from categories
            where tenant_id = %s and lower(name) = lower(%s) and transaction_type = %s
            """,
            (tenant_uuid, name, normalized_type),
        )
        if existing:
            self._execute("update categories set is_active = true, updated_at = now() where tenant_id = %s and lower(name) = lower(%s) and transaction_type = %s", (tenant_uuid, name, normalized_type))
            return {"nombre": _value(existing, "name", 0, name), "tipo": _legacy_transaction_type(str(_value(existing, "transaction_type", 1, normalized_type))), "created": False}

        row = self._execute(
            """
            insert into categories (tenant_id, name, transaction_type, is_active)
            values (%s, %s, %s, true)
            returning name, transaction_type
            """,
            (tenant_uuid, name, normalized_type),
        )
        return {"nombre": _value(row, "name", 0, name), "tipo": _legacy_transaction_type(str(_value(row, "transaction_type", 1, normalized_type))), "created": True}

    def list_pending_movements(self, tenant_id: str, limit: int = 50, include_resolved: bool = False) -> list[dict[str, Any]]:
        tenant_uuid = self._tenant_uuid(tenant_id)
        status_filter = "" if include_resolved else "and status = 'pending'"
        rows = self._fetchall(
            f"""
            select id, detected_at, source_reference, account_hint, transaction_type, amount, currency, description,
                   source_reference, status, confidence_score, confirmed_transaction_id, observation
            from pending_movements
            where tenant_id = %s {status_filter}
            order by detected_at desc
            limit %s
            """,
            (tenant_uuid, max(1, min(int(limit or 50), 200))),
        )
        return [
            {
                "ID": str(_value(row, "id", 0, "")),
                "FechaDetectada": str(_value(row, "detected_at", 1, "")),
                "Fuente": _value(row, "source_reference", 2, ""),
                "Cuenta": _value(row, "account_hint", 3, ""),
                "Tipo": _legacy_transaction_type(str(_value(row, "transaction_type", 4, "expense"))),
                "Monto": parse_number(_value(row, "amount", 5, 0)),
                "Moneda": _value(row, "currency", 6, "PEN"),
                "Descripcion": _value(row, "description", 7, ""),
                "Referencia": _value(row, "source_reference", 8, ""),
                "Estado": _legacy_status(str(_value(row, "status", 9, "pending"))),
                "Confianza": str(_value(row, "confidence_score", 10, "") or ""),
                "TXID": str(_value(row, "confirmed_transaction_id", 11, "") or ""),
                "Observacion": _value(row, "observation", 12, "") or "",
            }
            for row in rows
        ]

    def create_transaction(self, tenant_id: str, payload: dict[str, Any]) -> str:
        tenant_uuid = self._tenant_uuid(tenant_id)
        transaction_type = _normalized_transaction_type(payload.get("tipo"))
        transaction_date = _date_value(payload.get("fecha"))
        account_name = str(payload.get("cuenta", "")).strip()
        category_name = str(payload.get("categoria_input", "")).strip()
        amount = parse_number(payload.get("monto", 0))
        currency = str(payload.get("moneda", "PEN")).upper()
        with self.connection_factory() as conn:
            with conn.cursor() as cursor:
                account_id = self._account_id(cursor, tenant_uuid, account_name)
                category_id = self._category_id(cursor, tenant_uuid, category_name, transaction_type)
                cursor.execute(
                    """
                    insert into transactions (tenant_id, account_id, category_id, transaction_date, transaction_type, amount, currency, payment_method, note)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    returning id
                    """,
                    (tenant_uuid, account_id, category_id, transaction_date, transaction_type, amount, currency, str(payload.get("metodo", "")), str(payload.get("nota", ""))),
                )
                transaction_id = _value(cursor.fetchone(), "id", 0, "")
                self._apply_account_delta(cursor, tenant_uuid, account_id, transaction_type, amount)
                self._audit(cursor, tenant_uuid, "transaction.created", "transaction", transaction_id)
            conn.commit()
        return str(transaction_id)

    def update_transaction(self, tenant_id: str, transaction_id: str, field: str, value: Any) -> Any:
        tenant_uuid = self._tenant_uuid(tenant_id)
        normalized_field = normalize_text(field)
        with self.connection_factory() as conn:
            with conn.cursor() as cursor:
                if normalized_field in {"nota", "note"}:
                    cursor.execute("update transactions set note = %s, updated_at = now() where tenant_id = %s and id = %s returning id", (value, tenant_uuid, transaction_id))
                elif normalized_field in {"metodo", "payment_method"}:
                    cursor.execute("update transactions set payment_method = %s, updated_at = now() where tenant_id = %s and id = %s returning id", (value, tenant_uuid, transaction_id))
                elif normalized_field in {"categoria", "category"}:
                    cursor.execute("select transaction_type from transactions where tenant_id = %s and id = %s and status = 'posted'", (tenant_uuid, transaction_id))
                    row = cursor.fetchone()
                    if not row:
                        raise ValueError("transaction not found")
                    category_id = self._category_id(cursor, tenant_uuid, str(value).strip(), str(_value(row, "transaction_type", 0, "expense")))
                    cursor.execute("update transactions set category_id = %s, updated_at = now() where tenant_id = %s and id = %s returning id", (category_id, tenant_uuid, transaction_id))
                else:
                    raise ValueError("field is not supported by Postgres repository")
                result = cursor.fetchone()
                self._audit(cursor, tenant_uuid, "transaction.updated", "transaction", transaction_id)
            conn.commit()
        return result

    def delete_transaction(self, tenant_id: str, transaction_id: str) -> Any:
        tenant_uuid = self._tenant_uuid(tenant_id)
        with self.connection_factory() as conn:
            with conn.cursor() as cursor:
                cursor.execute("select account_id, transaction_type, amount from transactions where tenant_id = %s and id = %s and status = 'posted'", (tenant_uuid, transaction_id))
                row = cursor.fetchone()
                if not row:
                    raise ValueError("transaction not found")
                account_id = _value(row, "account_id", 0)
                transaction_type = str(_value(row, "transaction_type", 1, "expense"))
                amount = parse_number(_value(row, "amount", 2, 0))
                self._apply_account_delta(cursor, tenant_uuid, account_id, transaction_type, amount, reverse=True)
                cursor.execute("update transactions set status = 'voided', updated_at = now() where tenant_id = %s and id = %s returning id", (tenant_uuid, transaction_id))
                result = cursor.fetchone()
                self._audit(cursor, tenant_uuid, "transaction.voided", "transaction", transaction_id)
            conn.commit()
        return result

    def pay_debt(self, tenant_id: str, debt_id: str, payload: dict[str, Any]) -> Any:
        tenant_uuid = self._tenant_uuid(tenant_id)
        amount = parse_number(payload.get("monto", 0))
        currency = str(payload.get("moneda_pago", payload.get("moneda", "PEN"))).upper()
        account_name = str(payload.get("cuenta_banco", payload.get("cuenta", ""))).strip()
        note = str(payload.get("nota", "")).strip()
        with self.connection_factory() as conn:
            with conn.cursor() as cursor:
                account_id = self._account_id(cursor, tenant_uuid, account_name)
                cursor.execute("select description from debts where tenant_id = %s and id = %s", (tenant_uuid, debt_id))
                debt = cursor.fetchone()
                if not debt:
                    raise ValueError("debt not found")
                category_id = self._category_id(cursor, tenant_uuid, "Debt payment", "expense")
                cursor.execute(
                    """
                    insert into transactions (tenant_id, account_id, category_id, debt_id, transaction_date, transaction_type, amount, currency, payment_method, note)
                    values (%s, %s, %s, %s, current_date, 'expense', %s, %s, %s, %s)
                    returning id
                    """,
                    (tenant_uuid, account_id, category_id, debt_id, amount, currency, account_name, note),
                )
                transaction_id = _value(cursor.fetchone(), "id", 0)
                cursor.execute(
                    "insert into debt_payments (tenant_id, debt_id, account_id, transaction_id, amount, currency, note) values (%s, %s, %s, %s, %s, %s, %s) returning id",
                    (tenant_uuid, debt_id, account_id, transaction_id, amount, currency, note),
                )
                payment_id = _value(cursor.fetchone(), "id", 0)
                cursor.execute(
                    """
                    update debts
                    set outstanding_amount = greatest(outstanding_amount - %s, 0),
                        status = case when greatest(outstanding_amount - %s, 0) = 0 then 'paid' else status end,
                        updated_at = now()
                    where tenant_id = %s and id = %s
                    returning id
                    """,
                    (amount, amount, tenant_uuid, debt_id),
                )
                result = cursor.fetchone()
                self._apply_account_delta(cursor, tenant_uuid, account_id, "expense", amount)
                self._audit(cursor, tenant_uuid, "debt.payment_created", "debt_payment", payment_id)
            conn.commit()
        return result

    def confirm_pending_movement(self, tenant_id: str, pending_id: str, category: str, note: str = "") -> Any:
        tenant_uuid = self._tenant_uuid(tenant_id)
        with self.connection_factory() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "select account_hint, transaction_type, amount, currency, description from pending_movements where tenant_id = %s and id = %s and status = 'pending'",
                    (tenant_uuid, pending_id),
                )
                pending = cursor.fetchone()
                if not pending:
                    raise ValueError("pending movement not found")
                account_name = str(_value(pending, "account_hint", 0, "") or "")
                transaction_type = str(_value(pending, "transaction_type", 1, "expense"))
                amount = parse_number(_value(pending, "amount", 2, 0))
                currency = str(_value(pending, "currency", 3, "PEN"))
                description = str(_value(pending, "description", 4, ""))
                account_id = self._account_id(cursor, tenant_uuid, account_name)
                category_id = self._category_id(cursor, tenant_uuid, category, transaction_type)
                cursor.execute(
                    """
                    insert into transactions (tenant_id, account_id, category_id, pending_movement_id, transaction_date, transaction_type, amount, currency, payment_method, note)
                    values (%s, %s, %s, %s, current_date, %s, %s, %s, %s, %s)
                    returning id
                    """,
                    (tenant_uuid, account_id, category_id, pending_id, transaction_type, amount, currency, account_name, note or description),
                )
                transaction_id = _value(cursor.fetchone(), "id", 0)
                self._apply_account_delta(cursor, tenant_uuid, account_id, transaction_type, amount)
                cursor.execute("update pending_movements set status = 'confirmed', confirmed_transaction_id = %s, observation = %s, updated_at = now() where tenant_id = %s and id = %s returning id", (transaction_id, note, tenant_uuid, pending_id))
                result = cursor.fetchone()
                self._audit(cursor, tenant_uuid, "pending.confirmed", "pending_movement", pending_id)
            conn.commit()
        return result

    def discard_pending_movement(self, tenant_id: str, pending_id: str, reason: str = "") -> Any:
        tenant_uuid = self._tenant_uuid(tenant_id)
        with self.connection_factory() as conn:
            with conn.cursor() as cursor:
                cursor.execute("update pending_movements set status = 'discarded', observation = %s, updated_at = now() where tenant_id = %s and id = %s returning id", (reason, tenant_uuid, pending_id))
                result = cursor.fetchone()
                self._audit(cursor, tenant_uuid, "pending.discarded", "pending_movement", pending_id)
            conn.commit()
        return result

    def create_snapshot(self, tenant_id: str, origin: str = "Mobile", date: Any = None) -> Any:
        return {"created": False, "reason": "snapshots_disabled"}
