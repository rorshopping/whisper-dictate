import unittest

from license_gate import GRACE_DAYS, locally_valid, token_payload

NOW = 1_800_000_000  # fixed "now" for deterministic tests


def make_state(exp, last_ok=None, token="a.b"):
    state = {"token": token, "exp": exp}
    if last_ok is not None:
        state["last_ok"] = last_ok
    return state


class TokenPayloadTests(unittest.TestCase):
    def test_decodes_payload(self):
        import base64
        import json

        body = base64.urlsafe_b64encode(
            json.dumps({"email": "a@b.com", "exp": 123}).encode()
        ).decode().rstrip("=")
        payload = token_payload(f"{body}.somesignature")
        self.assertEqual(payload["email"], "a@b.com")
        self.assertEqual(payload["exp"], 123)

    def test_malformed_tokens_are_empty(self):
        self.assertEqual(token_payload(""), {})
        self.assertEqual(token_payload("not-a-token"), {})
        self.assertEqual(token_payload("###.###"), {})


class LocallyValidTests(unittest.TestCase):
    def test_missing_or_empty_state(self):
        self.assertFalse(locally_valid(None, NOW))
        self.assertFalse(locally_valid({}, NOW))
        self.assertFalse(locally_valid({"token": ""}, NOW))

    def test_valid_inside_expiry(self):
        state = make_state(exp=NOW + 1000, last_ok=NOW)
        self.assertTrue(locally_valid(state, NOW))

    def test_expired_without_grace_contact(self):
        # Expired AND never validated against the server: no grace.
        state = make_state(exp=NOW - 1000)
        self.assertFalse(locally_valid(state, NOW))

    def test_expired_within_offline_grace(self):
        state = make_state(exp=NOW - 1000, last_ok=NOW - 100)
        self.assertTrue(locally_valid(state, NOW))

    def test_expired_beyond_offline_grace(self):
        state = make_state(exp=NOW - 100, last_ok=NOW - GRACE_DAYS * 86400 - 100)
        self.assertFalse(locally_valid(state, NOW))

    def test_falls_back_to_activated_timestamp(self):
        state = {"token": "a.b", "exp": NOW - 1000, "activated": NOW - 100}
        self.assertTrue(locally_valid(state, NOW))

    def test_garbage_exp_is_invalid(self):
        state = {"token": "a.b", "exp": "soon", "last_ok": NOW}
        self.assertFalse(locally_valid(state, NOW))


if __name__ == "__main__":
    unittest.main()
