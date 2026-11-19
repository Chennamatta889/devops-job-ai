import unittest
from unittest.mock import patch, Mock
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
class ScreeningTests(unittest.TestCase):
    def test_explicit_facts(self):
        from screening import answer_for
        self.assertEqual(answer_for("Notice period in days?",{"notice_period_days":30}),30)
        self.assertIsNone(answer_for("Total years of experience",{"max_required_years":4}))
        self.assertIsNone(answer_for("Are you authorized to work in the US?",{}))
        self.assertEqual(answer_for("Willing to relocate?",{"screening_answers":{"Willing to relocate?":False}}),False)
class VerificationTests(unittest.TestCase):
    def page_with_frame(self, visible, width=300, height=80, src="https://example.test/captcha", title="CAPTCHA"):
        p=Mock()
        p.locator.return_value.count.return_value=1
        f=p.locator.return_value.nth.return_value
        f.is_visible.return_value=visible
        f.bounding_box.return_value={"width":width,"height":height}
        f.get_attribute.side_effect=lambda k: {"src":src,"title":title}.get(k)
        p.get_by_text.return_value.count.return_value=0
        return p
    def test_hidden_widget(self):
        from portal import verification_required
        self.assertFalse(verification_required(self.page_with_frame(False)))
    def test_active_widget(self):
        from portal import verification_required
        self.assertTrue(verification_required(self.page_with_frame(True)))
    def test_badge_and_visible_prompt(self):
        from portal import verification_required
        p=self.page_with_frame(True,70,60,"https://www.google.com/recaptcha/api2/anchor","reCAPTCHA")
        self.assertFalse(verification_required(p))
        p.get_by_text.return_value.count.return_value=1
        p.get_by_text.return_value.nth.return_value.is_visible.return_value=True
        self.assertTrue(verification_required(p))
class ReconciliationTests(unittest.TestCase):
    def test_acknowledgment(self):
        from reconcile import ack_matches
        job={"company":"ExampleCo","title":"DevOps Engineer"}
        self.assertTrue(ack_matches("Application confirmation","ExampleCo: Thank you for applying to DevOps Engineer.","jobs@ashbyhq.com",job))
        self.assertFalse(ack_matches("Application confirmation","ExampleCo: Thank you for applying to Cloud Engineer.","jobs@ashbyhq.com",job))
        self.assertFalse(ack_matches("Application confirmation","ExampleCo: Thank you for applying to DevOps Engineer.","someone@gmail.com",job))
        self.assertFalse(ack_matches("Application confirmation","ExampleCo: Failed to submit. Your application received an error for DevOps Engineer.","jobs@ashbyhq.com",job))
class ExpandedProfileTests(unittest.TestCase):
    def test_profile_variants(self):
        from screening import answer_for
        profile={"current_location":"Example City","current_company":"Example Ltd","preferred_location":"Example City","willing_to_relocate":True,"immediate_joiner":False,"notice_period_days":30,"experience_years":2.9,"experience_months":34,"current_ctc_inr":500000,"expected_ctc_lpa":11,"education":"B.Tech","graduation_year":2023,"open_to_hybrid":True,"reason_for_change":"Career growth"}
        for question,expected in [
            ("Please enter your current location", "Example City"),
            ("Current employer name", "Example Ltd"),
            ("Preferred work city", "Example City"),
            ("Are you willing to relocate for this role?", True),
            ("Are you an immediate joiner?", False),
            ("Notice period in days", 30),
            ("Overall experience in months", 34),
            ("Total experience in years", 2.9),
            ("Current CTC in INR", 500000),
            ("Expected CTC in LPA", 11),
            ("Highest qualification", "B.Tech"),
            ("Year of graduation", 2023),
            ("Are you open to work in hybrid model?", True),
            ("Reason for change", "Career growth"),
        ]:
            with self.subTest(question=question):
                self.assertEqual(answer_for(question,profile),expected)
    def test_no_guessed_facts(self):
        from screening import answer_for
        profile={"experience_years":2.9,"willing_to_relocate":True}
        for question in ("AWS experience in years","Are you authorized to work in the US?","Do you have a security clearance?","Current CTC","Expected joining date"):
            self.assertIsNone(answer_for(question,profile))
class IndeedAlertTests(unittest.TestCase):
    def test_indeed_links(self):
        html='<a href="https://in.indeed.com/viewjob?jk=0123456789abcdef&amp;from=alert">DevOps Engineer</a><a href="https://www.indeed.com/rc/clk?jk=0123456789abcdef">DevOps Engineer</a>'
        rows=parse_alert(html,"Daily jobs","indeed_alert")
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["url"],"https://in.indeed.com/viewjob?jk=0123456789abcdef")
        self.assertEqual(rows[0]["location"],"Unverified location")
    def test_reject_invalid_links(self):
        self.assertEqual(platform("https://indeed.com.evil.example/viewjob?jk=0123456789abcdef"),"")
        self.assertEqual(platform("https://in.indeed.com/viewjob?jk=invalid"),"")
class LiveLeverQuestionTests(unittest.TestCase):
    def test_known_lever_questions(self):
        from screening import answer_for
        p={"current_location":"Hyderabad","willing_to_relocate":True,"notice_period_days":30,"current_ctc_inr":500000,"expected_ctc_inr":1100000,"experience_years":2.9,"willing_to_work_in_shifts":True,"open_to_onsite":True}
        cases=[
            ("What is your Current Annual Salary?",500000),
            ("What is your Expected Annual Salary ?",1100000),
            ("What is your notice period?",30),
            ("What is your current CTC",500000),
            ("What is your expected CTC",1100000),
            ("How many years of relevant experience do you have?",2.9),
            ("Are you currently living in Hyderabad?",True),
            ("If not, will you be comfortable relocating to Hyderabad?",True),
            ("This is a work from office role and would require you to work in rotational shifts, including nights, weekends and public holidays, is that okay with you ?",True),
        ]
        for q,expected in cases:
            with self.subTest(q=q): self.assertEqual(answer_for(q,p),expected)
    def test_visa_not_inferred(self):
        from screening import answer_for
        self.assertIsNone(answer_for("Will you now or in the future require sponsorship for employment visa status to work legally in the United States?",{"country":"India"}))
if __name__=="__main__": unittest.main()
