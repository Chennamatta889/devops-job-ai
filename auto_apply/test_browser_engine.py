"""Local fixture tests: no external employer traffic or candidate data."""
import unittest
from playwright.sync_api import sync_playwright
from screening import location_suggestion_matches, select_lever_location
from portal import verification_required, ashby_submit_signal
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
    def test_challenge_stop(self):
        with sync_playwright() as p:
            browser=p.chromium.launch()
            page=browser.new_page()
            page.set_content('<input class="location-input" name="location"><p>Verify you are human</p>')
            trace={}
            self.assertEqual(select_lever_location(page,{"current_location":"Hyderabad, Telangana, India"},verification_required,trace),"verification")
            self.assertEqual(page.locator("input").input_value(),"")
            browser.close()

if __name__ == "__main__":
    unittest.main()
