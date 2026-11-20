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
    fill_contact_fields(page,data,greenhouse=True)
    # The real country picker and the phone widget must both report India.
    page.wait_for_timeout(500)
    state=greenhouse_phone_state(page,data)
    print("LIVE PHONE PREFLIGHT:",json.dumps(state))
    if not state["verified"]:raise SystemExit("Live phone state not verified. No live application will run.")
    missing=required_after_resume(page,data,True)
    if any(re.fullmatch(r"(?:phone(?: number)?|country(?: code)?)(?:\s*\*)?",x.strip(),re.I) for x in missing):
        raise SystemExit("Phone still flagged as incomplete. No live application will run.")
    print("LIVE PHONE PREFLIGHT PASSED: country flag +91, matching number, and widget state verified; no application submitted.")
    browser.close()
