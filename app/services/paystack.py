import hashlib
import hmac
from decimal import Decimal
from typing import Dict, Optional

import requests

from app.core.config import settings


class PaystackError(Exception):
    """Custom exception for Paystack API errors"""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _raise_for_http_error(response, default_message: str) -> None:
    """Raise PaystackError carrying the HTTP status so callers can tell definitive
    rejections (4xx) from ambiguous failures (5xx / network errors)."""
    if response.status_code >= 400:
        try:
            message = response.json().get("message") or default_message
        except Exception:
            message = default_message
        raise PaystackError(
            f"Paystack error ({response.status_code}): {message}",
            status_code=response.status_code,
        )


class PaystackService:
    """
    Service class for Paystack payment gateway integration.

    Handles transaction initialization, verification, webhook validation,
    and fund transfers to artisans.
    """

    BASE_URL = settings.PAYSTACK_BASE_URL
    SECRET_KEY = settings.PAYSTACK_SECRET_KEY

    @staticmethod
    def _get_headers() -> Dict[str, str]:
        """Get authorization headers for Paystack API requests"""
        return {
            "Authorization": f"Bearer {PaystackService.SECRET_KEY}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _naira_to_kobo(amount: Decimal) -> int:
        """Convert Naira to Kobo (multiply by 100)"""
        return int(amount * 100)

    @staticmethod
    def _kobo_to_naira(amount: int) -> Decimal:
        """Convert Kobo to Naira (divide by 100)"""
        return Decimal(amount) / 100

    @classmethod
    def initialize_transaction(
        cls,
        email: str,
        amount: Decimal,
        reference: str,
        metadata: Optional[Dict] = None,
        callback_url: Optional[str] = None,
    ) -> Dict:
        """
        Initialize a payment transaction with Paystack.

        Args:
            email: Customer's email address
            amount: Amount in Naira (will be converted to kobo)
            reference: Unique payment reference
            metadata: Additional metadata (optional)
            callback_url: URL to redirect after payment (optional)

        Returns:
            Dictionary with authorization_url, access_code, and reference

        Raises:
            PaystackError: If API request fails
        """
        url = f"{cls.BASE_URL}/transaction/initialize"

        payload = {
            "email": email,
            "amount": cls._naira_to_kobo(amount),
            "reference": reference,
        }

        if metadata:
            payload["metadata"] = metadata

        if callback_url:
            payload["callback_url"] = callback_url

        try:
            response = requests.post(url, json=payload, headers=cls._get_headers(), timeout=30)
        except requests.RequestException as e:
            raise PaystackError(f"Paystack API request failed: {str(e)}")

        data: Dict = {}
        try:
            data = response.json()
        except Exception:
            data = {}

        if response.status_code >= 400:
            message = (
                data.get("message")
                or data.get("detail")
                or response.text
                or "Transaction initialization failed"
            )
            raise PaystackError(
                f"Paystack initialize error ({response.status_code}): {message}",
                status_code=response.status_code,
            )

        if not data.get("status"):
            raise PaystackError(
                data.get("message", "Transaction initialization failed"),
                status_code=response.status_code,
            )

        return data["data"]

    @classmethod
    def verify_transaction(cls, reference: str) -> Dict:
        """
        Verify a payment transaction.

        Args:
            reference: Payment reference to verify

        Returns:
            Dictionary with transaction details

        Raises:
            PaystackError: If verification fails
        """
        url = f"{cls.BASE_URL}/transaction/verify/{reference}"

        try:
            response = requests.get(url, headers=cls._get_headers(), timeout=30)
            response.raise_for_status()
            data = response.json()

            if not data.get("status"):
                raise PaystackError(data.get("message", "Transaction verification failed"))

            return data["data"]

        except requests.RequestException as e:
            raise PaystackError(f"Paystack API request failed: {str(e)}")

    @staticmethod
    def verify_webhook_signature(signature: str, payload: bytes) -> bool:
        """
        Verify webhook signature using HMAC SHA512.

        Args:
            signature: Signature from webhook header (x-paystack-signature)
            payload: Raw webhook payload bytes

        Returns:
            True if signature is valid, False otherwise
        """
        if not settings.PAYSTACK_WEBHOOK_SECRET:
            return False

        computed_signature = hmac.new(
            settings.PAYSTACK_WEBHOOK_SECRET.encode("utf-8"), payload, hashlib.sha512
        ).hexdigest()

        return hmac.compare_digest(computed_signature, signature)

    @classmethod
    def create_transfer_recipient(cls, name: str, account_number: str, bank_code: str) -> Dict:
        """
        Create a transfer recipient (artisan's bank account).

        Args:
            name: Account holder's name
            account_number: Bank account number
            bank_code: Bank code (e.g., "057" for Zenith Bank)

        Returns:
            Dictionary with recipient_code

        Raises:
            PaystackError: If recipient creation fails
        """
        url = f"{cls.BASE_URL}/transferrecipient"

        payload = {
            "type": "nuban",
            "name": name,
            "account_number": account_number,
            "bank_code": bank_code,
            "currency": "NGN",
        }

        try:
            response = requests.post(url, json=payload, headers=cls._get_headers(), timeout=30)
            _raise_for_http_error(response, "Recipient creation failed")
            data = response.json()

            if not data.get("status"):
                raise PaystackError(data.get("message", "Recipient creation failed"))

            return data["data"]

        except requests.RequestException as e:
            raise PaystackError(f"Paystack API request failed: {str(e)}")

    @classmethod
    def initiate_transfer(
        cls, recipient_code: str, amount: Decimal, reason: str, reference: str
    ) -> Dict:
        """
        Transfer funds to artisan.

        Args:
            recipient_code: Recipient code from create_transfer_recipient
            amount: Amount in Naira (will be converted to kobo)
            reason: Reason for transfer
            reference: Unique transfer reference

        Returns:
            Dictionary with transfer details

        Raises:
            PaystackError: If transfer fails
        """
        url = f"{cls.BASE_URL}/transfer"

        payload = {
            "source": "balance",
            "amount": cls._naira_to_kobo(amount),
            "recipient": recipient_code,
            "reason": reason,
            "reference": reference,
        }

        try:
            response = requests.post(url, json=payload, headers=cls._get_headers(), timeout=30)
            _raise_for_http_error(response, "Transfer initiation failed")
            data = response.json()

            if not data.get("status"):
                raise PaystackError(
                    data.get("message", "Transfer initiation failed"),
                    status_code=response.status_code,
                )

            return data["data"]

        except requests.RequestException as e:
            raise PaystackError(f"Paystack API request failed: {str(e)}")

    @classmethod
    def verify_transfer(cls, reference: str) -> Dict:
        """
        Fetch a transfer by OUR reference (GET /transfer/verify/:reference).

        Returns the transfer data (``status``: success | pending | otp | failed | reversed ...).
        Raises PaystackError with ``status_code == 404`` when the transfer does not exist,
        and without a status code on network errors.
        """
        url = f"{cls.BASE_URL}/transfer/verify/{reference}"
        try:
            response = requests.get(url, headers=cls._get_headers(), timeout=30)
            _raise_for_http_error(response, "Transfer verification failed")
            data = response.json()
            if not data.get("status"):
                raise PaystackError(
                    data.get("message", "Transfer verification failed"),
                    status_code=response.status_code,
                )
            return data["data"]
        except requests.RequestException as e:
            raise PaystackError(f"Paystack API request failed: {str(e)}")

    @classmethod
    def get_banks(cls) -> Dict:
        """
        Get list of supported banks.

        Returns:
            Dictionary with list of banks

        Raises:
            PaystackError: If request fails
        """
        url = f"{cls.BASE_URL}/bank"

        try:
            response = requests.get(url, headers=cls._get_headers(), timeout=30)
            response.raise_for_status()
            data = response.json()

            if not data.get("status"):
                raise PaystackError(data.get("message", "Failed to fetch banks"))

            return data["data"]

        except requests.RequestException as e:
            raise PaystackError(f"Paystack API request failed: {str(e)}")

    @classmethod
    def verify_account_number(cls, account_number: str, bank_code: str) -> Dict:
        """
        Verify bank account number.

        Args:
            account_number: Bank account number
            bank_code: Bank code

        Returns:
            Dictionary with account details (account_name, account_number)

        Raises:
            PaystackError: If verification fails
        """
        url = f"{cls.BASE_URL}/bank/resolve"

        params = {"account_number": account_number, "bank_code": bank_code}

        try:
            response = requests.get(url, params=params, headers=cls._get_headers(), timeout=30)
            data = response.json()

            if response.status_code >= 400:
                error_message = data.get("message", "Account verification failed")
                raise PaystackError(error_message)

            if not data.get("status"):
                raise PaystackError(data.get("message", "Account verification failed"))

            return data["data"]

        except requests.RequestException as e:
            raise PaystackError(f"Paystack API request failed: {str(e)}")
