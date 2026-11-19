import unittest
from unittest.mock import patch
from portal import candidate_data, portal_enabled
from agent import match, key
from job_alerts import parse_alert, platform
from india_sources import india_location, relevant_role
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
class IndiaTests(unittest.TestCase):
    def test_locations(self):
        self.assertTrue(india_location("Remote - India"))
        self.assertTrue(india_location("Kochi"))
        self.assertFalse(india_location("Remote - US"))
        self.assertFalse(india_location("Indianapolis"))
    def test_roles(self):
        self.assertTrue(relevant_role("Cloud Support Engineer"))
        self.assertTrue(relevant_role("Build Engineer"))
        self.assertFalse(relevant_role("Java Developer"))
class AlertTests(unittest.TestCase):
    def test_linkedin(self):
        html='<a href="https://www.linkedin.com/jobs/view/devops-engineer-12345?tracking=abc">DevOps Engineer</a>'
        rows=parse_alert(html,"Jobs in India","linkedin_alert")
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["location"],"Unverified location")
        self.assertNotIn("?",rows[0]["url"])
    def test_naukri(self):
        html='<a href="https://www.naukri.com/job-listings-cloud-engineer-company-hyderabad-123">Cloud Engineer Hyderabad</a>'
        self.assertEqual(len(parse_alert(html,"Jobs","naukri_alert")),1)
    def test_reject_lookalike(self):
        self.assertEqual(platform("https://linkedin.com.evil.example/jobs/view/123"),"")
if __name__=="__main__": unittest.main()
