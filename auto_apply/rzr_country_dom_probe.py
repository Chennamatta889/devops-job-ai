"""Live public preflight, synthetic phone, no candidate data, no submit."""
import json,re
from playwright.sync_api import sync_playwright
from portal import verification_required,fill_contact_fields,greenhouse_phone_state,required_after_resume
URL="https://job-boards.greenhouse.io/rzr/jobs/4254732009"
with sync_playwright() as p:
    browser=p.chromium.launch()
    context=browser.new_context(service_workers="block")
    context.route("**/*",lambda r:r.continue_() if r.request.method in ("GET","HEAD","OPTIONS") else r.abort())
    page=context.new_page()
    page.goto(URL,wait_until="domcontentloaded",timeout=45000)
    page.wait_for_timeout(2000)
    if verification_required(page):raise SystemExit("Live preflight stopped for human verification")
    link=page.get_by_role("link",name=re.compile(r"^apply(?: now| for this job)?$",re.I))
    if link.count()==1 and link.is_visible():link.click(timeout=5000)
    if verification_required(page):raise SystemExit("Live preflight stopped for human verification")
    data={"phone":"+919876543210"}
    country=page.locator('input#country[role=combobox]:visible')
    if country.count()!=1:raise SystemExit("Country control not found")
    country.click()
    country.fill("India")
    page.wait_for_timeout(400)
    options=page.get_by_role("option",name=re.compile(r"^\s*India\s*\+91\s*$",re.I))
    print("EXACT COUNTRY OPTION COUNT:",options.count())
    if options.count()!=1 or verification_required(page):raise SystemExit("No unique country option")
    options.click()
    page.wait_for_timeout(350)
    print("SELECTED COUNTRY DOM:",json.dumps(country.evaluate(r"""el=>{
        let p=el;
        return Array.from({length:5},()=>{
            if(!p||p.matches('form,body,main'))return null;
            const result={tag:p.tagName,cls:p.className,html:p.outerHTML.slice(0,6000),text:p.innerText};
            p=p.parentElement;
            return result;
        }).filter(Boolean)
    }""")))
    phone=page.locator('input#phone[type=tel]:visible')
    print("PHONE DOM:",json.dumps(phone.evaluate("el=>el.parentElement.outerHTML.slice(0,6000)")))
    fill_contact_fields(page,data,greenhouse=True)
    page.wait_for_timeout(500)
    state=greenhouse_phone_state(page,data)
    print("LIVE PHONE PREFLIGHT:",json.dumps(state))
    if not state["verified"]: print("Existing country check failed; diagnostic only.")
    missing=required_after_resume(page,data,True)
    if any(re.fullmatch(r"(?:phone(?: number)?|country(?: code)?)(?:\s*\*)?",x.strip(),re.I) for x in missing):
        print("Phone still flagged as incomplete.")
    print("COUNTRY DOM DIAGNOSTIC COMPLETE; no submit")
    browser.close()
