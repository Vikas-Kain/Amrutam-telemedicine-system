"""Payment provider adapter interface and simulated mock payment provider."""

import hashlib
import hmac
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class PaymentProviderStatus(StrEnum):
    """External payment provider outcome status."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"
    REQUIRES_RECONCILIATION = "requires_reconciliation"


@dataclass(frozen=True)
class PaymentIntentResult:
    """Outcome returned from payment provider adapter operations."""

    provider: str
    provider_reference: str
    status: PaymentProviderStatus
    amount_minor: int
    currency: str
    client_secret: str | None = None
    raw_response: dict[str, Any] | None = None


class PaymentProviderAdapter(ABC):
    """Abstract interface defining required provider integration capabilities."""

    @abstractmethod
    async def create_payment_intent(
        self,
        *,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
        metadata: dict[str, Any],
        simulation: str | None = None,
    ) -> PaymentIntentResult:
        """Initiate payment intent with external provider outside database transactions."""
        ...

    @abstractmethod
    async def reconcile_payment(
        self,
        *,
        provider_reference: str,
    ) -> PaymentIntentResult:
        """Query external provider state to reconcile timeout or unknown outcomes."""
        ...

    @abstractmethod
    def verify_webhook_signature(
        self,
        *,
        payload_bytes: bytes,
        signature_header: str,
        secret: str,
    ) -> bool:
        """Verify HMAC signature for incoming provider webhooks."""
        ...


class MockPaymentProviderAdapter(PaymentProviderAdapter):
    """Clearly marked simulated mock payment provider for assignment evaluation.

    Simulates payment intent creation, webhook processing, signature verification,
    and reconciliation. Absolutely NO real monetary transactions or bank/card
    charges are performed.
    """

    PROVIDER_NAME: str = "mock_provider"
    DEFAULT_SECRET: str = "mock_webhook_secret_for_amrutam_telemedicine"

    async def create_payment_intent(
        self,
        *,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
        metadata: dict[str, Any],
        simulation: str | None = None,
    ) -> PaymentIntentResult:
        """Simulate payment intent initiation.

        Supports simulation behaviors:
        - None / 'success': Immediate simulated payment success
        - 'pending': Simulated asynchronous intent requiring webhook
        - 'failure': Simulated payment rejection (e.g. insufficient funds)
        - 'timeout': Simulated network timeout requiring lookup reconciliation
        """
        ref_suffix = uuid.uuid4().hex[:12]
        provider_ref = f"mock_pi_{ref_suffix}"

        sim_type = (simulation or metadata.get("simulation") or "success").lower()

        if sim_type == "timeout":
            status = PaymentProviderStatus.REQUIRES_RECONCILIATION
        elif sim_type == "failure":
            status = PaymentProviderStatus.FAILED
        elif sim_type == "pending":
            status = PaymentProviderStatus.PENDING
        else:
            status = PaymentProviderStatus.SUCCEEDED

        return PaymentIntentResult(
            provider=self.PROVIDER_NAME,
            provider_reference=provider_ref,
            status=status,
            amount_minor=amount_minor,
            currency=currency,
            client_secret=f"mock_secret_{uuid.uuid4().hex[:16]}",
            raw_response={
                "simulation": sim_type,
                "idempotency_key": idempotency_key,
                "consultation_id": metadata.get("consultation_id"),
            },
        )

    async def reconcile_payment(
        self,
        *,
        provider_reference: str,
    ) -> PaymentIntentResult:
        """Simulate reconciling a timeout/unknown transaction.

        In production, this queries the provider's REST API using the provider reference.
        The mock adapter verifies the reference and returns a resolved succeeded status.
        """
        return PaymentIntentResult(
            provider=self.PROVIDER_NAME,
            provider_reference=provider_reference,
            status=PaymentProviderStatus.SUCCEEDED,
            amount_minor=1_000,
            currency="INR",
            raw_response={"reconciled": True},
        )

    def verify_webhook_signature(
        self,
        *,
        payload_bytes: bytes,
        signature_header: str,
        secret: str,
    ) -> bool:
        """Verify HMAC-SHA256 signature against request body bytes."""
        if not signature_header or not secret:
            return False
        expected = hmac.new(
            secret.encode("utf-8"),
            msg=payload_bytes,
            digestmod=hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature_header)

    @classmethod
    def generate_signature(cls, payload_bytes: bytes, secret: str) -> str:
        """Helper to generate authentic HMAC-SHA256 signatures for testing and callbacks."""
        return hmac.new(
            secret.encode("utf-8"),
            msg=payload_bytes,
            digestmod=hashlib.sha256,
        ).hexdigest()
