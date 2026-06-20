import unittest
from unittest.mock import patch

from api.auth_service import create_jwt, hash_otp, verify_jwt


class AuthServiceTests(unittest.TestCase):
    def test_create_and_verify_jwt(self):
        with patch("api.auth_service.config.MOBILE_JWT_SECRET", "test-secret"):
            token = create_jwt({"tenant_id": "TEN_TEST", "telegram_user_id": "123", "rol": "Owner"})
            payload = verify_jwt(token)

        self.assertEqual(payload["tenant_id"], "TEN_TEST")
        self.assertEqual(payload["telegram_user_id"], "123")
        self.assertEqual(payload["rol"], "Owner")
        self.assertIn("exp", payload)

    def test_verify_jwt_rejects_tampering(self):
        with patch("api.auth_service.config.MOBILE_JWT_SECRET", "test-secret"):
            token = create_jwt({"tenant_id": "TEN_TEST"})
            tampered = token[:-1] + ("a" if token[-1] != "a" else "b")

            with self.assertRaises(ValueError):
                verify_jwt(tampered)

    def test_hash_otp_is_stable_for_same_input(self):
        with patch("api.auth_service.config.MOBILE_JWT_SECRET", "test-secret"):
            first = hash_otp("TEN_TEST", "123", "456789")
            second = hash_otp("TEN_TEST", "123", "456789")

            self.assertEqual(first, second)
            self.assertNotEqual(first, hash_otp("TEN_TEST", "123", "000000"))


if __name__ == "__main__":
    unittest.main()
