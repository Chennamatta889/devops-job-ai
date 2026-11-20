"""Local fixture tests: no external employer traffic or candidate data."""
import unittest
from portal import email_code_form
from playwright.sync_api import sync_playwright
from screening import location_suggestion_matches, select_lever_location, answer_for, fill_screening, unanswered_required
from portal import verification_required, ashby_submit_signal, passive_recaptcha_frame, fill_contact_fields, validation_details, fill_greenhouse_country, resume_attachment_state, verify_resume_attachment, required_after_resume, greenhouse_phone_state
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


    def test_country_and_phone_and_validation_safe(self):
        with sync_playwright() as p:
            b=p.chromium.launch(); page=b.new_page()
            page.set_content('<label for="country">Country</label><select id="country"><option value="">Choose</option><option value="IN">India (+91)</option><option value="US">United States (+1)</option></select><label for="phone">Phone</label><input id="phone" pattern="[0-9]{10}" required><label for="email">Email</label><input id="email" type="email" required>')
            profile={"phone":"9876543210","screening_answers":{"Country":"India"}}
            self.assertEqual(fill_contact_fields(page,profile,greenhouse=True),1)
            self.assertEqual(page.locator("#country").input_value(),"IN")
            self.assertEqual(page.locator("#phone").input_value(),"9876543210")
            page.locator("#email").fill("invalid")
            self.assertEqual(validation_details(page),[{"category":"email","flags":["typeMismatch"]}])
            self.assertEqual(public_status("portal_uncertain_validation_after_submit"),"UNCERTAIN")
            b.close()
    def test_country_unknown_and_no_overwrite(self):
        with sync_playwright() as p:
            b=p.chromium.launch(); page=b.new_page()
            page.set_content('<label for="country">Country</label><select id="country"><option value="US" selected>United States (+1)</option><option value="IN">India (+91)</option></select>')
            self.assertIsNone(fill_greenhouse_country(page,{"phone":"9876543210"}))
            self.assertIsNone(fill_greenhouse_country(page,{"phone":"+919876543210","country":"India"}))
            self.assertEqual(page.locator("#country").input_value(),"US")
            b.close()


    def test_resume_wrapper_and_visible_phone(self):
        with sync_playwright() as p:
            browser=p.chromium.launch(); page=browser.new_page()
            page.set_content('<div aria-required="true" aria-label="Phone"><input type="tel" id="mobile"></div><input type="hidden" name="phone"><div aria-required="true" aria-label="Resume/CV*"><button type="button">Attach resume</button><input type="file" id="resume" style="display:none"></div><div aria-required="true" aria-label="Unanswered"><input id="other"></div>')
            self.assertEqual(fill_contact_fields(page,{"phone":"+919876543210"}),1)
            self.assertEqual(page.locator("#mobile").input_value(),"+919876543210")
            self.assertCountEqual(unanswered_required(page),["Resume/CV*","Unanswered"])
            page.locator("#resume").set_input_files({"name":"Fixture.pdf","mimeType":"application/pdf","buffer":b"%PDF-1.4 fixture"})
            self.assertEqual(unanswered_required(page),["Unanswered"])
            browser.close()


    def test_salary_answers_and_dialing_prefix(self):
        with sync_playwright() as p:
            browser=p.chromium.launch(); page=browser.new_page()
            page.set_content('<div aria-required="true" aria-label="Phone"><input role="combobox" aria-label="Country"><input type="tel" id="phone" value="+91"></div><label for="q1">Current Salary ?</label><input id="q1" required><label for="q2">Expected Salary ?</label><input id="q2" required>')
            data={"phone":"+919876543210","screening_answers":{"Current Salary ?":"INR 500000 annual CTC","Expected Salary ?":"INR 1200000 annual CTC"}}
            self.assertEqual(fill_contact_fields(page,data),1)
            self.assertEqual(fill_screening(page,data,verification_required),2)
            self.assertEqual(page.locator("#phone").input_value(),"+919876543210")
            self.assertEqual(unanswered_required(page),[])
            browser.close()


    def test_resume_input_removed_after_upload(self):
        with sync_playwright() as p:
            b=p.chromium.launch(); page=b.new_page()
            page.set_content('<div aria-required="true" aria-label="Resume/CV*"><input type="file" id="resume"><script>document.getElementById("resume").onchange=e=>{const parent=e.target.parentElement;const name=e.target.files[0].name;e.target.remove();const span=document.createElement("span");span.textContent=name;parent.append(span);const button=document.createElement("button");button.textContent="Remove file";parent.append(button)}</script></div>')
            files=page.locator("#resume")
            files.set_input_files({"name":"Resume.pdf","mimeType":"application/pdf","buffer":b"%PDF-1.4 fixture"})
            self.assertEqual(files.count(),0)
            from playwright.sync_api import TimeoutError
            with self.assertRaises(TimeoutError):
                files.evaluate("el=>el.files.length",timeout=100)
            diag={}
            self.assertEqual(verify_resume_attachment(page,files,"Resume.pdf",diag),"attached")
            self.assertEqual(diag["resume_attachment"]["preview_with_remove"],1)
            self.assertEqual(required_after_resume(page),[])
            b.close()
    def test_attachment_not_assumed_when_input_disappears(self):
        with sync_playwright() as p:
            b=p.chromium.launch(); page=b.new_page()
            page.set_content('<div>Resume.pdf</div><button>Submit application</button>')
            self.assertFalse(resume_attachment_state(page,page.locator("#resume"),"Resume.pdf")["attached"])
            page.set_content('<input type="file" id="resume">')
            self.assertFalse(resume_attachment_state(page,page.locator("#resume"),"Resume.pdf")["attached"])
            b.close()


    def test_linked_phone_label_and_explicit_answers(self):
        with sync_playwright() as p:
            b=p.chromium.launch(); page=b.new_page()
            page.set_content('<label for="tel" aria-required="true">Phone</label><input id="tel" type="tel" required><label for="join">How soon can you join us?</label><input id="join" type="number" required><label for="relocate">Are you willing to relocate if needed?</label><select id="relocate" required><option value="">Select</option><option value="yes">Yes</option><option value="no">No</option></select>')
            data={"phone":"+919876543210","screening_answers":{"How soon can you join us?":"30 days","Are you willing to relocate if needed?":True}}
            self.assertEqual(fill_contact_fields(page,data),1)
            self.assertEqual(fill_screening(page,data,verification_required),2)
            self.assertEqual(page.locator("#join").input_value(),"30")
            self.assertEqual(unanswered_required(page),[])
            page.locator("#tel").fill("")
            self.assertIn("Phone",unanswered_required(page))
            b.close()


    def test_greenhouse_phone_selection_and_exact_digits(self):
        with sync_playwright() as p:
            b=p.chromium.launch();page=b.new_page()
            page.set_content('<div><div class="select__single-value">India +91</div><input id="country" role="combobox" aria-required="true" aria-label="Country"></div><input id="phone" type="tel" aria-required="true" aria-label="Phone" value="09876543210">')
            data={"phone":"+919876543210"}
            self.assertTrue(greenhouse_phone_state(page,data)["verified"])
            self.assertEqual(required_after_resume(page,data,True),[])
            page.locator("#phone").fill("1234")
            self.assertFalse(greenhouse_phone_state(page,data)["verified"])
            self.assertIn("Phone",required_after_resume(page,data,True))
            page.locator("#phone").fill("9876543210")
            page.locator(".select__single-value").evaluate("el=>el.textContent='United States +1'")
            self.assertFalse(greenhouse_phone_state(page,data)["verified"])
            self.assertIn("Phone",required_after_resume(page,data,True))
            b.close()


    def test_greenhouse_flag_dial_code_and_independent_phone_widget(self):
        with sync_playwright() as p:
            b=p.chromium.launch();page=b.new_page()
            page.set_content('''<div class="select__value-container select__value-container--has-value">
                <div class="select__single-value"><div class="iti__flag iti__in"></div><span>+91</span></div>
                <div class="select__input-container"><input id="country" role="combobox" aria-expanded="false" aria-invalid="false" aria-required="true" aria-label="Country"></div>
                </div><div class="iti"><button class="iti__selected-country" aria-expanded="false" title="India" aria-label="Change country, selected India (+91)"><div class="iti__flag iti__in"></div></button><input id="phone" type="tel" data-intl-tel-input-id="0" aria-required="true" aria-label="Phone" value="09876543210"></div>''')
            data={"phone":"+919876543210"}
            self.assertTrue(greenhouse_phone_state(page,data)["verified"])
            self.assertEqual(required_after_resume(page,data,True),[])
            page.locator("button.iti__selected-country").evaluate("el=>el.style.display='none'")
            self.assertTrue(greenhouse_phone_state(page,data)["verified"])
            page.locator("button .iti__flag").evaluate("el=>el.className='iti__flag iti__us'")
            self.assertFalse(greenhouse_phone_state(page,data)["verified"])
            page.locator("button .iti__flag").evaluate("el=>el.className='iti__flag iti__in'")
            page.locator(".select__single-value .iti__flag").evaluate("el=>el.className='iti__flag iti__us'")
            self.assertFalse(greenhouse_phone_state(page,data)["verified"])
            page.locator(".select__single-value .iti__flag").evaluate("el=>el.className='iti__flag iti__in'")
            page.locator("#country").evaluate("el=>el.setAttribute('aria-expanded','true')")
            self.assertFalse(greenhouse_phone_state(page,data)["verified"])
            page.locator("#country").evaluate("el=>el.setAttribute('aria-expanded','false')")
            page.locator("#phone").fill("")
            self.assertFalse(greenhouse_phone_state(page,data)["verified"])
            b.close()


    def test_job_email_verification_form_is_scoped(self):
        with sync_playwright() as p:
            b=p.chromium.launch(); page=b.new_page()
            page.set_content('<div role="dialog"><p>A verification code was sent to your email.</p><label for="code">Security code</label><input id="code"><button>Verify</button></div>')
            controls=email_code_form(page)
            self.assertIsNotNone(controls)
            controls[0].fill("12345678")
            self.assertEqual(controls[0].input_value(),"12345678")
            page.set_content('<div role="dialog"><p>A verification code was sent to your email. Sign in to your account.</p><label for="code">Security code</label><input id="code"><button>Verify</button></div>')
            self.assertIsNone(email_code_form(page))
            page.set_content('<form><label for="code">Security code</label><input id="code"><button>Submit</button></form>')
            self.assertIsNone(email_code_form(page))
            page.set_content('<div role="dialog"><p>A verification code was sent to your email.</p><label for="code">Security code</label><input id="code"><button>Verify</button><button>Submit</button></div>')
            self.assertIsNone(email_code_form(page))
            b.close()

if __name__ == "__main__":
    unittest.main()
