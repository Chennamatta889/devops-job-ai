"""Conservative applicant-side browser adapter; never bypass challenges."""
import os, json, base64, re, io
from urllib.parse import urlparse
from screening import fill_screening

HOSTS={"job-boards.greenhouse.io","boards.greenhouse.io","jobs.lever.co","jobs.ashbyhq.com"}
def portal_enabled(profile, pdf):
    return os.getenv("PORTAL_AUTO_APPLY","").strip().lower()!="false" and pdf.startswith(b"%PDF-")
def candidate_data(profile, pdf):
    data=dict(profile)
    if os.getenv("PORTAL_PROFILE_JSON","").strip():
        data.update(json.loads(os.environ["PORTAL_PROFILE_JSON"]))
    name=str(data.get("name","")).strip()
    if name:
        data.setdefault("first_name",name.split()[0])
        data.setdefault("last_name"," ".join(name.split()[1:]))
    data.setdefault("email",os.getenv("SMTP_USER",""))
    if not data.get("phone"):
        from pypdf import PdfReader
        text="\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages[:2])
        matches=set(re.sub(r"[^0-9+]","",m) for m in re.findall(r"(?<!\d)(?:\+91[\s-]*)?[6-9]\d{4}[\s-]?\d{5}(?!\d)",text))
        normalized={"+91"+m[-10:] for m in matches}
        if len(normalized)==1: data["phone"]=normalized.pop()
    return data
def portal_apply(job, profile, pdf):
    stage="candidate"
    submitted=False
    try:
        if not pdf.startswith(b"%PDF-"): return "portal_review_invalid_resume"
        data=candidate_data(profile,pdf)
        if not all(data.get(x) for x in ("first_name","last_name","email","phone")):
            return "portal_review_contact"
        url=job.get("apply_url") or job.get("url","")
        u=urlparse(url)
        if u.scheme!="https" or u.hostname not in HOSTS or u.username or u.password: return "portal_review_unsupported_url"
        if u.hostname=="jobs.lever.co": url=url.split("?")[0].rstrip("/")+"/apply" if not url.split("?")[0].rstrip("/").endswith("/apply") else url.split("?")[0]
        stage="browser_launch"
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser=p.chromium.launch()
            page=browser.new_page(accept_downloads=False)
            page.route("**/*", lambda route: route.abort() if route.request.is_navigation_request() and urlparse(route.request.url).hostname not in HOSTS else route.continue_())
            stage="navigation"
            page.goto(url,wait_until="domcontentloaded",timeout=45000)
            if u.hostname in ("job-boards.greenhouse.io","boards.greenhouse.io"):
                link=page.get_by_role("link",name=re.compile(r"^apply(?: now| for this job)?$",re.I))
                if link.count()==1 and link.is_visible(): link.click(timeout=10000)
            if urlparse(page.url).hostname not in HOSTS: return "portal_review_redirect"
            page.wait_for_timeout(2000)
            if page.locator('iframe[src*="captcha"], iframe[src*="challenge"]').count(): return "portal_review_human_verification"
            stage="contact_fields"
            fields={"first_name":data.get("first_name"),"last_name":data.get("last_name"),"name":data.get("name"),"email":data.get("email"),"phone":data.get("phone"),"org":data.get("current_company"),"urls[LinkedIn]":data.get("linkedin"),"urls[GitHub]":data.get("github")}
            for key,val in fields.items():
                if not val: continue
                locator=page.locator('input[name="'+key+'"],input[id="'+key+'"]')
                if locator.count()==1 and locator.is_visible(): locator.fill(str(val))
            if u.hostname in HOSTS:
                for label,value in [(r"^full name",data.get("name")),(r"^first name",data.get("first_name")),(r"^last name",data.get("last_name")),(r"^email",data.get("email")),(r"^phone",data.get("phone"))]:
                    field=page.get_by_label(re.compile(label,re.I))
                    if value and field.count()==1 and field.is_visible(): field.fill(str(value))
            stage="resume_field"
            files=page.locator('input[type=file][name="resume"], input[type=file][id="resume"], input[type=file][name="resumeFile"]')
            if files.count()==0:
                files=page.get_by_label(re.compile(r"resume|curriculum vitae",re.I)).and_(page.locator("input[type=file]"))
            if files.count()!=1: return "portal_review_resume_field"
            stage="screening"
            print("Screening fields filled:",fill_screening(page,data))
            if page.locator('[role=combobox]:visible[aria-required=true]:not(select), input[type=checkbox]:visible[required], input[type=radio]:visible[required]').count(): return "portal_review_choices"
            selects=page.locator("select:visible[required], select:visible[aria-required=true]")
            for i in range(selects.count()):
                if not selects.nth(i).input_value(): return "portal_review_unanswered_select"
            unknown=page.locator('input:visible:not([type=hidden]):not([type=submit]):not([type=button]):not([type=file]), textarea:visible')
            for i in range(unknown.count()):
                field=unknown.nth(i)
                if not field.input_value().strip() and (field.get_attribute("required") is not None or field.get_attribute("aria-required")=="true"): return "portal_review_unanswered_fields"
            if not all(data.get(x) for x in ("email","phone")): return "portal_review_contact"
            buttons=page.get_by_role("button",name=re.compile(r"^(submit application|submit|apply for this job)$",re.I))
            if buttons.count()!=1: return "portal_review_submit_button"
            stage="resume_upload"
            files.set_input_files({"name":"Resume.pdf","mimeType":"application/pdf","buffer":pdf})
            stage="submit"
            submitted=True
            buttons.click(timeout=10000)
            try:
                page.get_by_text(re.compile(r"thank you for applying|application (?:has been )?(?:submitted|received)|thanks for applying",re.I)).first.wait_for(timeout=12000)
                return "portal_confirmed"
            except Exception: return "portal_uncertain_confirmation"
    except Exception as exc:
        print("Portal diagnostic:",stage,type(exc).__name__)
        return "portal_uncertain_"+stage if submitted else "portal_review_"+stage+"_error"
