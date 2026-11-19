import unittest
from unittest.mock import patch, Mock
from portal import candidate_data, portal_enabled
from agent import match, key, extract_experience_requirement, known_direct_apply_url, aggregator_jobs, direct_match_score, resolve_aggregator_signals
from job_alerts import parse_alert, platform
from india_sources import india_location, relevant_role, technology_category, technology_role, recruitee
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
    def test_experience_extraction(self):
        self.assertEqual(extract_experience_requirement("Need 2-4 years of DevOps experience"),{"min":2,"max":4,"label":"2-4 years"})
        self.assertEqual(extract_experience_requirement("Minimum 3 years experience required"),{"min":3,"max":None,"label":"3+ years"})
        self.assertEqual(extract_experience_requirement("5+ years in cloud operations"),{"min":5,"max":None,"label":"5+ years"})
        self.assertEqual(extract_experience_requirement("Strong AWS and Kubernetes skills"),{"min":None,"max":None,"label":"Not specified"})
class AggregatorFeedTests(unittest.TestCase):
    @patch.dict("os.environ", {"AGGREGATOR_JOB_FEED_JSON": """[{"source":"indeed","title":"Java Developer","company":"Example","location":"Hyderabad, India","published":"2026-11-19T10:00:00Z","listing_url":"https://in.indeed.com/viewjob?jk=0123456789abcdef","direct_apply_url":"https://jobs.example.com/java"}]"""})
    def test_approved_aggregator_feed(self):
        rows=aggregator_jobs()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["source"],"indeed")
        self.assertEqual(rows[0]["direct_apply_url"],"https://jobs.example.com/java")

class AggregatorResolutionTests(unittest.TestCase):
    def test_confident_signal_resolves_to_direct_job(self):
        direct=[{
            "source":"greenhouse",
            "company":"Example Technologies Pvt Ltd",
            "title":"Senior Java Backend Developer",
            "location":"Hyderabad, India",
            "url":"https://job-boards.greenhouse.io/example/jobs/123",
            "published":"2026-11-19T10:00:00Z"
        }]
        signals=[{
            "source":"indeed",
            "company":"Example Technologies",
            "title":"Java Backend Developer",
            "location":"Hyderabad, India",
            "listing_url":"https://in.indeed.com/viewjob?jk=0123456789abcdef",
            "published":"2026-11-19T10:00:00Z"
        }]
        merged=resolve_aggregator_signals(direct,signals)
        self.assertEqual(len(merged),1)
        self.assertIn("indeed",merged[0]["discovered_via"])
        self.assertEqual(merged[0]["source_listings"]["indeed"],signals[0]["listing_url"])

    def test_different_company_does_not_resolve(self):
        direct=[{
            "source":"lever",
            "company":"Alpha Labs",
            "title":"Python Developer",
            "location":"Bengaluru, India",
            "url":"https://jobs.lever.co/alpha/123"
        }]
        signal={
            "source":"linkedin",
            "company":"Beta Labs",
            "title":"Python Developer",
            "location":"Bengaluru, India",
            "listing_url":"https://www.linkedin.com/jobs/view/123"
        }
        self.assertEqual(direct_match_score(signal,direct[0]),0)
        merged=resolve_aggregator_signals(direct,[signal])
        self.assertEqual(len(merged),2)
        self.assertEqual(merged[1]["resolution"],"listing_only")

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
    def test_all_technology_categories(self):
        self.assertEqual(technology_category("Java Backend Developer"),"Software Engineering")
        self.assertEqual(technology_category("Machine Learning Engineer"),"Data / AI / ML")
        self.assertEqual(technology_category("QA Automation Engineer"),"QA / Testing")
        self.assertEqual(technology_category("Cyber Security Analyst"),"Cybersecurity")
        self.assertEqual(technology_category("DevOps Engineer"),"Cloud / DevOps / SRE")
        self.assertTrue(technology_role("Salesforce Developer"))
        self.assertFalse(technology_role("HR Business Partner"))
class RecruiteeTests(unittest.TestCase):
    @patch("india_sources.read")
    def test_recruitee_direct_jobs(self,mock_read):
        mock_read.return_value={"offers":[{
            "title":"Java Backend Developer",
            "slug":"java-backend-developer",
            "locations":[{"city":"Hyderabad","state_name":"Telangana","country":"India"}],
            "description":"3+ years Java Spring Boot AWS",
            "published_at":"2026-11-19T10:00:00Z",
            "careers_url":"https://example.recruitee.com/o/java-backend-developer",
            "careers_apply_url":"https://example.recruitee.com/o/java-backend-developer/c/new"
        }]}
        rows=recruitee("example",all_tech=True)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["source"],"recruitee")
        self.assertEqual(rows[0]["apply_url"],"https://example.recruitee.com/o/java-backend-developer/c/new")

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
    def test_foundit(self):
        html='<a href="https://www.foundit.in/search/java-developer-jobs-in-hyderabad">Java Developer Hyderabad</a>'
        rows=parse_alert(html,"Technology jobs","foundit_alert","2026-11-19T10:00:00+00:00")
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["source"],"foundit_alert")
class ScreeningTests(unittest.TestCase):
    def test_explicit_facts(self):
        from screening import answer_for
        self.assertEqual(answer_for("Notice period in days?",{"notice_period_days":30}),30)
        self.assertIsNone(answer_for("Total years of experience",{"max_required_years":4}))
        self.assertIsNone(answer_for("Are you authorized to work in the US?",{}))
        self.assertEqual(answer_for("Willing to relocate?",{"screening_answers":{"Willing to relocate?":False}}),False)
class DirectApplyTests(unittest.TestCase):
    def test_known_ats_domains(self):
        self.assertEqual(
            known_direct_apply_url("https://jobs.ashbyhq.com/example/123"),
            "https://jobs.ashbyhq.com/example/123",
        )
        self.assertEqual(
            known_direct_apply_url("https://company.wd5.myworkdayjobs.com/en-US/Careers/job/123"),
            "https://company.wd5.myworkdayjobs.com/en-US/Careers/job/123",
        )
        self.assertEqual(known_direct_apply_url("https://www.linkedin.com/jobs/view/123"),"")
        self.assertEqual(known_direct_apply_url("http://jobs.ashbyhq.com/example/123"),"")

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
class TargetingAndOptionTests(unittest.TestCase):
    def test_test_automation_not_target(self):
        from india_sources import relevant_role
        self.assertFalse(relevant_role("Test Automation Engineer II"))
        self.assertTrue(relevant_role("Infrastructure Automation Engineer"))
    def test_location_option_prefix(self):
        from screening import option_match
        self.assertTrue(option_match("Current location","Hyderabad","Hyderabad, Telangana, India",{"country":"India"}))
        self.assertFalse(option_match("Current location","Hyderabad","Hyderabad, Sindh, Pakistan",{"country":"India"}))
        self.assertFalse(option_match("Expected CTC","11","11 LPA"))
class DemandbaseAndPlaneTests(unittest.TestCase):
    def test_demandbase_questions(self):
        from screening import answer_for
        p={"notice_period_days":30,"expected_ctc_inr":1100000,"expected_ctc_lpa":11}
        self.assertEqual(answer_for("What is your current notice period?",p),30)
        self.assertEqual(answer_for("What is your expected annual CTC range?",p),"11 LPA")
    def test_plane_joining_and_ctc(self):
        from screening import answer_for
        p={"notice_period_days":30,"immediate_joiner":False,"current_ctc_inr":500000,"experience_years":2.9,"application_source":"Company careers page"}
        self.assertEqual(answer_for("How did you come to know about Plane?",p),"Company careers page")
        self.assertEqual(answer_for("If you are offered, by when can you join?",p),"Available after my 30-day notice period.")
        self.assertEqual(answer_for("If available immediately, what was your last working day in the previous organisation?",p),"Not applicable - serving a 30-day notice period.")
        self.assertEqual(answer_for("What is your current CTC/ last drawn CTC?",p),500000)
        self.assertEqual(answer_for("What is your total work experience in a similar role/ capacity?",p),2.9)
class AshbySubmitTests(unittest.TestCase):
    def test_ashby_submit_signals(self):
        from portal import ashby_submit_signal
        self.assertEqual(ashby_submit_signal({"data":{"submitMultipleFormsAction":{"applicationFormResult":{"__typename":"FormSubmitSuccess","_":True},"messages":{}}}}),"success")
        self.assertEqual(ashby_submit_signal({"data":{"submitApplicationFormAction":{"applicationFormResult":{"__typename":"FormSubmitSuccess","_":True},"messages":{}}}}),"success")
        self.assertEqual(ashby_submit_signal({"data":{"submitMultipleFormsAction":{"applicationFormResult":{"__typename":"FormRender","id":"form"},"messages":{}}}}),"validation")
        self.assertEqual(ashby_submit_signal({"data":{"submitMultipleFormsAction":{"applicationFormResult":{"__typename":"FormSubmitSuccess","_":True},"messages":{"blockMessageForCandidateHtml":"blocked"}}}}),"blocked")
        self.assertEqual(ashby_submit_signal({"errors":[{"message":"x"}]}),"")
class PrivateLinkedInFallbackTests(unittest.TestCase):
    def test_extract_candidate_linkedin(self):
        from portal import extract_candidate_linkedin
        body="LinkedIn: https://www.linkedin.com/in/chenna123/\nRecruiter: https://www.linkedin.com/in/other-person/"
        self.assertEqual(extract_candidate_linkedin(body,"Matta Chenna Rao"),"https://www.linkedin.com/in/chenna123")
    @patch("portal.linkedin_from_sent_mail",return_value="https://www.linkedin.com/in/chenna123")
    @patch.dict("os.environ", {"SMTP_USER":"candidate@example.com","PORTAL_PROFILE_JSON":""})
    def test_candidate_data_private_linkedin_fallback(self,mock_linkedin):
        from portal import candidate_data
        d=candidate_data({"name":"Matta Chenna Rao","phone":"+919876543210","current_company":"Example Ltd"},b"%PDF-invalid")
        self.assertEqual(d["linkedin"],"https://www.linkedin.com/in/chenna123")
class PlaneLinkedInLabelTests(unittest.TestCase):
    def test_plane_linkedin_label(self):
        from screening import answer_for
        self.assertEqual(answer_for("Your Linkedin profile link.",{"linkedin":"https://www.linkedin.com/in/example"}),"https://www.linkedin.com/in/example")
if __name__=="__main__": unittest.main()
