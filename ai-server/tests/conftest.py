import os
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def _escaped_pem(value: bytes) -> str:
    return value.decode("utf-8").replace("\n", "\\n")


_test_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
TEST_BACKEND_JWT_PRIVATE_KEY = _escaped_pem(
    _test_private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
)
TEST_BACKEND_JWT_PUBLIC_KEY = _escaped_pem(
    _test_private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
)

# Set dummy environment variables for tests
os.environ["AI_INGEST_API_KEY"] = "test-key"
os.environ["BACKEND_JWT_PUBLIC_KEY"] = TEST_BACKEND_JWT_PUBLIC_KEY
os.environ["PG_PASSWORD"] = "changeit"
os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key"

from tests.fixtures.large_batch_generator import get_mock_batch, generate_large_batch

__all__ = ["get_mock_batch", "generate_large_batch"]
