"""Local fixture tests: no external employer traffic or candidate data."""
import unittest
from playwright.sync_api import sync_playwright
from screening import location_suggestion_matches, select_lever_location, answer_for, fill_screening, unanswered_required
from portal import verification_required, ashby_submit_signal, passive_recaptcha_frame, fill_contact_fields
from supabase_worker import public_status

class BrowserEngineTests(unittest.TestCase):
    def test_full_location(self):
        self.assertTrue(location_suggestion_matches("Hyderabad, Telangana, India", "Hyderabad", "Hyderabad Telangana, India"))
        self.assertFalse(location_suggestion_matches("Hyderabad, Telangana, India", "Hyderabad", "Hyderabad, Sindh, Pakistan"))
    def test_confirmation(self):
        self.assertEqual(ashby_submit_signal({"data":{"submitApplicationFormAction":{"applicationFormResult":{"__typename":"FormSubmitSuccess"}}}}),"success")
        self.assertEqual(public_status("portal_uncertain_human_verification_after_submit"),"UNCERTAIN")
    def test_actual_selection(self):
        with sync_playwright() as p:
            browser=p.chromium.launch()
            page=browser.new_page()
            page.set_content("""<input class="location-input" name="location">
                <div class="pac-container" style="display:none">
                  <div class="pac-item"><span class="pac-item-query">Hyderabad</span><span>Sindh, Pakistan</span></div>
                  <div class="pac-item"><span class="pac-item-query">Hyderabad</span><span>Telangana, India</span></div>
                </div><script>
                const input=document.querySelector('input');const list=document.querySelector('.pac-container');
                input.oninput=()=>{list.style.display=input.value.length>2?'block':'none'};
                document.querySelectorAll('.pac-item').forEach((el,i)=>el.onclick=()=>{input.value=i?'Hyderabad, Telangana, India':'Hyderabad, Sindh, Pakistan';list.style.display='none'});
                </script>""")
            trace={}
            result=select_lever_location(page,{"current_location":"Hyderabad, Telangana, India"},verification_required,trace)
            self.assertEqual(result,"selected",trace)
            self.assertEqual(page.locator("input").input_value(),"Hyderabad, Telangana, India")
            self.assertEqual(trace["match_count"],1)
            browser.close()
    def test_question_aliases(self):
        profile={"years_experience":3,"notice_period_days":30,"screening_answers":{"Current location":"Example City"}}
        self.assertEqual(answer_for("Number of years of experience",profile),3)
        self.assertEqual(answer_for("Current notice period (in days)",profile),30)
        self.assertEqual(answer_for("Current location",profile),"Example City")
        self.assertIsNone(answer_for("Have you received security clearance?",profile))
    def test_required_and_unknown(self):
        with sync_playwright() as p:
            browser=p.chromium.launch()
            page=browser.new_page()
            page.set_content('<label for="city">Current location</label><input id="city" required><label for="x">Unverified declaration</label><input id="x" required>')
            self.assertEqual(fill_screening(page,{"current_location":"Example City"},verification_required),1)
            self.assertEqual(unanswered_required(page),["Unverified declaration"])
            browser.close()
    def test_no_dropdown_classification(self):
        self.assertEqual(public_status("portal_review_location_autocomplete"),"REVIEW_REQUIRED")
        self.assertEqual(public_status("portal_review_human_verification_v2"),"HUMAN_VERIFICATION_REQUIRED")
        self.assertEqual(public_status("portal_uncertain_no_submission_response"),"UNCERTAIN")
    def test_challenge_stop(self):
        with sync_playwright() as p:
            browser=p.chromium.launch()
            page=browser.new_page()
            page.set_content('<input class="location-input" name="location"><p>Verify you are human</p>')
            trace={}
            self.assertEqual(select_lever_location(page,{"current_location":"Hyderabad, Telangana, India"},verification_required,trace),"verification")
            self.assertEqual(page.locator("input").input_value(),"")
            browser.close()


    def test_invisible_recaptcha_is_not_active_challenge(self):
        with sync_playwright() as p:
            browser=p.chromium.launch()
            page=browser.new_page()
            page.route("**/*",lambda route: route.fulfill(status=200,body="fixture"))
            page.set_content('<iframe title="reCAPTCHA" width="256" height="60" src="https://www.google.com/recaptcha/api2/anchor?size=invisible"></iframe><input id="email" type="email">')
            self.assertFalse(verification_required(page))
            self.assertEqual(fill_contact_fields(page,{"email":"fixture@example.invalid"}),1)
            self.assertEqual(page.locator("#email").input_value(),"fixture@example.invalid")
            page.evaluate("""()=>{const f=document.createElement('iframe');f.title='reCAPTCHA challenge';f.src='https://www.google.com/recaptcha/api2/bframe';document.body.append(f)}""")
            self.assertTrue(verification_required(page))
            browser.close()
    def test_checkbox_and_unknown_provider_still_stop(self):
        self.assertFalse(passive_recaptcha_frame("https://www.google.com/recaptcha/api2/anchor?size=normal","reCAPTCHA",{}))
        self.assertFalse(passive_recaptcha_frame("https://evil.invalid/recaptcha/api2/anchor?size=invisible","reCAPTCHA",{}))
        self.assertFalse(passive_recaptcha_frame("https://www.google.com/recaptcha/api2/bframe?size=invisible","reCAPTCHA",{}))
        with sync_playwright() as p:
            browser=p.chromium.launch()
            page=browser.new_page()
            page.route("**/*",lambda route: route.fulfill(status=200,body="fixture"))
            page.set_content('<iframe title="reCAPTCHA" width="300" height="80" src="https://www.google.com/recaptcha/api2/anchor?size=normal"></iframe><input id="email">')
            self.assertTrue(verification_required(page))
            self.assertEqual(fill_contact_fields(page,{"email":"fixture@example.invalid"}),0)
            browser.close()
    def test_greenhouse_style_form_and_explicit_screening(self):
        with sync_playwright() as p:
            browser=p.chromium.launch()
            page=browser.new_page()
            page.set_content("""
              <label for="first_name">First Name *</label><input id="first_name" required value="Existing">
              <label for="last_name">Last Name *</label><input id="last_name" required>
              <label for="email">Email *</label><input id="email" required type="email">
              <label for="phone">Phone</label><input id="phone" type="tel">
              <label for="resume">Resume/CV *</label><input id="resume" type="file" required>
              <label for="q1">Current Location *</label><input id="q1" required>
              <label for="q2">Current CTC *</label><input id="q2" required>
              <label for="q3">Expected CTC *</label><input id="q3" required>
              <label for="q4">Official Notice Period *</label><input id="q4" required>
              <label for="q5">LWD, if serving notice *</label><input id="q5" required>
              <button>Submit application</button>
            """)
            profile={"first_name":"Do not overwrite","last_name":"Fixture","email":"fixture@example.invalid","phone":"1234567890","current_location":"Example City","notice_period_days":30,"current_ctc_inr":500000,"expected_ctc_inr":1100000}
            self.assertIsNone(answer_for("Current CTC",profile))
            self.assertIsNone(answer_for("Expected CTC",profile))
            profile["screening_answers"]={"Current CTC":5,"Expected CTC":11,"LWD, if serving notice":"NA"}
            self.assertEqual(fill_contact_fields(page,profile),3)
            self.assertEqual(fill_screening(page,profile,verification_required),5)
            self.assertEqual(page.locator("#first_name").input_value(),"Existing")
            self.assertEqual(page.locator("#q2").input_value(),"5")
            self.assertEqual(page.locator("#q3").input_value(),"11")
            self.assertEqual(page.locator("#q4").input_value(),"30")
            self.assertEqual(page.locator("#q5").input_value(),"NA")
            self.assertEqual(unanswered_required(page),[])
            page.locator("#resume").set_input_files({"name":"Fixture.pdf","mimeType":"application/pdf","buffer":b"%PDF-1.4 fixture"})
            self.assertEqual(page.locator("#resume").evaluate("el=>el.files.length"),1)
            browser.close()

if __name__ == "__main__":
    unittest.main()
