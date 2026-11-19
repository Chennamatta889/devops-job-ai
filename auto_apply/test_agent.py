import unittest
from unittest.mock import patch
from portal import candidate_data, portal_enabled
from agent import match, key
class AgentTests(unittest.TestCase):
    def setUp(self):
        self.p={"locations":["india"],"skills":["aws","jenkins","docker"],"max_required_years":3}
        self.j={"company":"Example","title":"DevOps Engineer","location":"India","description":"2-4 years AWS Jenkins Docker"}
    def test_match(self):
        self.assertEqual(match(self.j,self.p)[0],100)
    def test_senior(self):
        self.assertEqual(match(dict(self.j,title="Senior DevOps Engineer"),self.p)[0],0)
    def test_experience(self):
        self.assertEqual(match(dict(self.j,description="5+ years AWS Jenkins Docker"),self.p)[0],0)
    def test_unknown_experience(self):
        self.assertEqual(match(dict(self.j,description="AWS Jenkins Docker"),self.p)[3],"experience unclear")
    def test_duplicate(self):
        self.assertEqual(key(self.j),key(dict(self.j,url="other")))
class PortalTests(unittest.TestCase):
    @patch.dict("os.environ", {"SMTP_USER":"candidate@example.com","PORTAL_PROFILE_JSON":"","PORTAL_AUTO_APPLY":""})
    def test_existing_secrets(self):
        p={"name":"Example Candidate","phone":"+919876543210"}
        d=candidate_data(p,b"%PDF-test")
        self.assertEqual(d["first_name"],"Example")
        self.assertEqual(d["last_name"],"Candidate")
        self.assertEqual(d["email"],"candidate@example.com")
        self.assertTrue(portal_enabled(p,b"%PDF-test"))
        self.assertFalse(portal_enabled(p,b"invalid"))
    @patch.dict("os.environ", {"PORTAL_AUTO_APPLY":"false"})
    def test_opt_out(self):
        self.assertFalse(portal_enabled({},b"%PDF-test"))
if __name__=="__main__": unittest.main()
