"""Content-script integration tests on synthetic ATS pages; no network or real applicant data."""
import unittest
from pathlib import Path
from playwright.sync_api import sync_playwright

SCRIPT=Path(__file__).with_name("content.js")
PROFILE={"fullName":"Example Candidate","email":"example@example.invalid","phone":"1234567890","location":"Example City, Example State, Example Country","linkedin":"https://example.invalid/profile"}
RESUME={"name":"fixture.pdf","base64":"JVBERi0xLjQK"}
BASE="""<form onsubmit="event.preventDefault();window.clicks++">
<label for="name">Full name</label><input id="name" name="name" required>
<label for="email">Email</label><input id="email" type="email" required>
<label for="phone">Phone</label><input id="phone" type="tel" required>
<input type="file" name="resume" required style="display:none">
{extra}
<button>Submit application</button></form>"""
class ContentScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=sync_playwright().start()
        cls.browser=cls.p.chromium.launch()
    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.p.stop()
    def setUp(self):
        self.page=self.browser.new_page()
        self.page.route("**/*",lambda route:route.abort())
    def tearDown(self):
        self.page.close()
    def load(self,extra=""):
        self.page.set_content(BASE.format(extra=extra))
        self.page.evaluate("""() => {window.clicks=0;window.chrome={runtime:{onMessage:{addListener:(fn)=>window.listener=fn}}}}""")
        self.page.add_script_tag(path=str(SCRIPT))
    def send(self,command):
        return self.page.evaluate("""m=>new Promise(resolve=>window.listener(m,{},resolve))""",{"type":"DRAFTFLOW_ASSISTED_APPLY","command":command,"profile":PROFILE,"resume":RESUME})
    def test_standard_form_and_duplicate_click(self):
        self.load()
        self.assertEqual(self.send("fill")["status"],"ready")
        self.assertEqual(self.page.locator("#name").input_value(),"Example Candidate")
        self.assertEqual(self.page.locator("#email").input_value(),PROFILE["email"])
        self.assertEqual(self.page.locator("input[type=file]").evaluate("el=>el.files.length"),1)
        self.assertEqual(self.send("submit")["status"],"submission_attempted")
        self.assertEqual(self.send("submit")["status"],"submission_attempted")
        self.assertEqual(self.page.evaluate("window.clicks"),1)
    def test_location_manual(self):
        self.load('<label for="location">Current location</label><input id="location" name="location" class="location-input" required>')
        self.assertEqual(self.send("fill")["status"],"review")
        self.assertEqual(self.page.locator("#location").input_value(),"")
        self.page.locator("#location").fill(PROFILE["location"])
        self.assertEqual(self.send("submit")["status"],"review")
        self.assertEqual(self.page.evaluate("window.clicks"),0)
    def test_challenge(self):
        self.load("<p>Verify you are human</p>")
        self.assertEqual(self.send("fill")["status"],"verification_required")
        self.assertEqual(self.page.locator("#name").input_value(),"")
        self.assertEqual(self.send("submit")["status"],"verification_required")
        self.assertEqual(self.page.evaluate("window.clicks"),0)
    def test_missing_question(self):
        self.load('<label for="extra">Required screening question</label><input id="extra" required>')
        self.assertEqual(self.send("fill")["status"],"missing_required")
        self.assertEqual(self.send("submit")["status"],"missing_required")
        self.assertEqual(self.page.evaluate("window.clicks"),0)
    def test_hidden_resume_required(self):
        self.load()
        self.assertEqual(self.send("check")["status"],"missing_required")
        self.assertIn("resume",self.send("check")["missing"])
    def test_invalid_email(self):
        self.load()
        self.send("fill")
        self.page.locator("#email").fill("not-an-email")
        self.assertEqual(self.send("submit")["status"],"review")
        self.assertEqual(self.page.evaluate("window.clicks"),0)

if __name__=="__main__":
    unittest.main(verbosity=2)
