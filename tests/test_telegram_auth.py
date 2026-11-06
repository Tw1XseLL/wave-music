import hashlib
import hmac
import json
import os
import time
import unittest
from urllib.parse import urlencode
from unittest.mock import patch

os.environ["BOT_TOKEN"] = "123456:TEST_TOKEN"
os.environ["DB_PATH"] = "/tmp/wave_auth_test.sqlite3"
from api.main import verify

def signed_data(token, user_id=42, timestamp=None):
    params = {
        "auth_date": str(int(time.time()) if timestamp is None else timestamp),
        "user": json.dumps({"id": user_id, "first_name": "Test"}, separators=(",", ":")),
        "query_id": "test-query",
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(params)

class TelegramAuthTests(unittest.TestCase):
    def test_valid_signature(self):
        self.assertEqual(verify(signed_data("123456:TEST_TOKEN"))["id"], 42)

    def test_tampered_signature(self):
        raw = signed_data("123456:TEST_TOKEN").replace("Test", "Other")
        self.assertIsNone(verify(raw))

    def test_wrong_bot_token(self):
        self.assertIsNone(verify(signed_data("123456:OTHER_TOKEN")))

    def test_expired_signature(self):
        self.assertIsNone(verify(signed_data("123456:TEST_TOKEN", timestamp=int(time.time())-90000)))

    def test_missing_initdata(self):
        self.assertIsNone(verify(""))

if __name__ == "__main__":
    unittest.main()
