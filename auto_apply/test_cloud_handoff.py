import unittest
from unittest.mock import Mock
from cloud_handoff import SteelSessions, Handoff, HandoffError, prepare_handoff, valid_url
from datetime import datetime, timezone

SID="11111111-1111-4111-8111-111111111111"
class HandoffTests(unittest.TestCase):
    def provider(self,viewer="https://api.steel.dev/v1/sessions/fixture/player/token"):
        reply=Mock(status_code=201)
        reply.json.return_value={"id":SID,"status":"live","websocketUrl":"wss://connect.steel.dev/fixture","debugUrl":viewer}
        http=Mock()
        http.request.return_value=reply
        return SteelSessions("fixture-key",http),http
    def test_consent_before_browser(self):
        with self.assertRaisesRegex(HandoffError,"explicit_provider_consent_required"):
            prepare_handoff({}, {}, b"%PDF-",consent=False,client=Mock())
    def test_allowlisted_employer(self):
        with self.assertRaisesRegex(HandoffError,"unsupported_employer"):
            prepare_handoff({"url":"https://example.invalid"}, {}, b"%PDF-",consent=True,client=Mock())
    def test_bounded_private_session(self):
        client,http=self.provider()
        sid,cdp,viewer,expiry=client.create(9999)
        body=http.request.call_args.kwargs["json"]
        self.assertEqual(body["timeout"],600000)
        for name in ("solveCaptcha","useProxy","recording","persistProfile","headless"):
            self.assertIs(body[name],False)
        self.assertTrue(body["debugConfig"]["interactive"])
        self.assertEqual(sid,SID)
        self.assertLessEqual((expiry-datetime.now(timezone.utc)).total_seconds(),600)
        self.assertNotIn(viewer,repr(Handoff(sid,viewer,expiry,"review",True,1)))
    def test_reject_viewer_redirect_and_release(self):
        client,http=self.provider("https://example.invalid/capability")
        with self.assertRaisesRegex(HandoffError,"invalid_provider_session"):
            client.create()
        self.assertTrue(http.request.call_args.args[1].endswith("/release"))
    def test_untrusted_url(self):
        self.assertFalse(valid_url("https://api.steel.dev@evil.invalid/player","https",{"api.steel.dev"}))
        self.assertFalse(valid_url("https://api.steel.dev:444/player","https",{"api.steel.dev"}))

if __name__=="__main__": unittest.main()
