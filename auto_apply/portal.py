"""Conservative applicant-side browser adapter; never bypass challenges."""
import os, json, base64, re
from urllib.parse import urlparse

HOSTS={"job-boards.greenhouse.io","boards.greenhouse.io","jobs.lever.co"}
def portal_enabled():
    return os.getenv("PORTAL_AUTO_APPLY","").lower()=="true" and bool(os.getenv("PORTAL_PROFILE_JSON","").strip()) and bool(os.getenv("RESUME_BASE64","") or (os.getenv("RESUME_PART_1","") and os.getenv("RESUME_PART_2","")))
def portal_apply(job, profile):
    try:
        data=json.loads(os.environ["PORTAL_PROFILE_JSON"])
        pdf=base64.b64decode(os.getenv("RESUME_BASE64","") or (os.getenv("RESUME_PART_1","")+os.getenv("RESUME_PART_2","")),validate=True)
        if not pdf.startswith(b"%PDF-"): return "portal_review_invalid_resume"
        url=job.get("url","")
        u=urlparse(url)
        if u.scheme!="https" or u.hostname not in HOSTS or u.username or u.password: return "portal_review_unsupported_url"
        if u.hostname=="jobs.lever.co": url=url.split("?")[0].rstrip("/")+"/apply" if not url.split("?")[0].rstrip("/").endswith("/apply") else url.split("?")[0]
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser=p.chromium.launch()
            page=browser.new_page()
            page.goto(url,wait_until="domcontentloaded",timeout=45000)
            if urlparse(page.url).hostname not in HOSTS: return "portal_review_redirect"
            page.wait_for_timeout(2000)
            if page.locator('iframe[src*="captcha"], iframe[src*="challenge"]').count(): return "portal_review_challenge"
            fields={"first_name":data.get("first_name"),"last_name":data.get("last_name"),"name":data.get("name"),"email":data.get("email"),"phone":data.get("phone"),"org":data.get("current_company")}
            for key,val in fields.items():
                if not val: continue
                locator=page.locator('input[name="'+key+'"],input[id="'+key+'"]')
                if locator.count()==1 and locator.is_visible(): locator.fill(str(val))
            files=page.locator('input[type=file][name="resume"], input[type=file][id="resume"], input[type=file][name="resumeFile"]')
            if files.count()!=1: return "portal_review_resume_field"
            files.set_input_files({"name":"Resume.pdf","mimeType":"application/pdf","buffer":pdf})
            if page.locator('select:visible, [role=combobox]:visible, input[type=checkbox]:visible, input[type=radio]:visible').count(): return "portal_review_choices"
            unknown=page.locator('input:visible:not([type=hidden]):not([type=submit]):not([type=button]):not([type=file]), textarea:visible')
            for i in range(unknown.count()):
                field=unknown.nth(i)
                if not field.input_value().strip(): return "portal_review_unanswered_fields"
            if not all(data.get(x) for x in ("email","phone")): return "portal_review_contact"
            buttons=page.get_by_role("button",name=re.compile(r"^(submit application|submit|apply for this job)$",re.I))
            if buttons.count()!=1: return "portal_review_submit_button"
            buttons.click(timeout=10000)
            try:
                page.get_by_text(re.compile(r"thank you for applying|application (?:has been )?(?:submitted|received)|thanks for applying",re.I)).first.wait_for(timeout=12000)
                return "portal_confirmed"
            except Exception: return "portal_uncertain_manual_review"
    except Exception:
        return "portal_uncertain_manual_review"
