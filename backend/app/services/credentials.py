import os

from cryptography.fernet import Fernet, InvalidToken


class CredentialConfigurationError(RuntimeError):
    """Raised when the encryption key is missing or cannot decrypt a secret."""


def _fernet() -> Fernet:
    key = os.getenv("CREDENTIAL_ENCRYPTION_KEY")
    if not key:
        raise CredentialConfigurationError(
            "CREDENTIAL_ENCRYPTION_KEY must be configured to use credentials"
        )
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise CredentialConfigurationError(
            "CREDENTIAL_ENCRYPTION_KEY is not a valid Fernet key"
        ) from exc


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
        raise CredentialConfigurationError(
            "credential secret cannot be decrypted; check the encryption key"
        ) from exc
