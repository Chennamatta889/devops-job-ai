"""Public form inspection only: no personal data, no form filling, no submit."""
from playwright.sync_api import sync_playwright
import json
from portal import verification_required
URL="https://job-boards.greenhouse.io/truveta/jobs/6114473004"
def main():
    with sync_playwright() as p:
        b=p.chromium.launch()
        page=b.new_page()
        page.goto(URL,wait_until="domcontentloaded",timeout=40000)
        page.wait_for_timeout(2500)
        print("Active challenge:",verification_required(page))
        data=page.locator('input:visible,select:visible,[role=combobox]:visible').evaluate_all(r"""els=>els.map(el=>{
            const labels=Array.from(el.labels||[]).map(x=>x.innerText).join(' ');
            const prompt=(labels+' '+(el.getAttribute('aria-label')||'')+' '+(el.id||'')+' '+(el.name||'')).toLowerCase();
            const category=/phone|mobile/.test(prompt)?'phone':/country/.test(prompt)?'country':/email/.test(prompt)?'email':/linkedin/.test(prompt)?'linkedin':/resume|cv/.test(prompt)?'resume':/first.?name/.test(prompt)?'first_name':/last.?name/.test(prompt)?'last_name':/website/.test(prompt)?'website':'other';
            return {category,tag:el.tagName,role:el.getAttribute('role')==='combobox'?'combobox':null,type:el.type,required:el.required||el.getAttribute('aria-required')==='true',pattern:!!el.getAttribute('pattern')};
        })""")
        print("Read-only form structure:",json.dumps(data))
        b.close()
if __name__=="__main__": main()
