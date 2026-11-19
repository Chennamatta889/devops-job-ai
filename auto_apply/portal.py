"""Conservative applicant-side browser adapter; never bypass challenges."""
import os, json, base64, re, io
from urllib.parse import urlparse
from screening import fill_screening, unanswered_required

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
    if not data.get("phone") or not data.get("linkedin") or not data.get("current_company"):
        # Parse only unambiguous, explicitly identifiable resume facts.
        try:
            from pypdf import PdfReader
            text="\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages[:2])
        except Exception:
            text=""
        matches=set(re.sub(r"[^0-9+]","",m) for m in re.findall(r"(?<!\d)(?:\+91[\s-]*)?[6-9]\d{4}[\s-]?\d{5}(?!\d)",text))
        normalized={"+91"+m[-10:] for m in matches}
        if len(normalized)==1 and not data.get("phone"): data["phone"]=normalized.pop()
        urls=set(re.findall(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[A-Za-z0-9_%.-]+",text,re.I))
        if len(urls)==1 and not data.get("linkedin"):
            link=urls.pop().rstrip(".")
            data["linkedin"]=link if link.startswith("http") else "https://"+link
        companies=set(m.strip() for m in re.findall(r"(?im)^\s*current\s+(?:company|employer)\s*:\s*([^\n]{2,100})",text))
        if len(companies)==1 and not data.get("current_company"): data["current_company"]=companies.pop()
    for target,aliases in {"current_location":("city","location"),"education":("qualification","highest_qualification"),"notice_period_days":("notice_days",),"experience_years":("total_experience_years",),"current_company":("employer",),"preferred_location":("preferred_city",)}.items():
        if not data.get(target):
            for alias in aliases:
                if data.get(alias) is not None and isinstance(data[alias],(str,int,float)):
                    data[target]=data[alias]; break
    for key in ("current","expected"):
        amount=data.get(key+"_ctc_inr")
        if isinstance(amount,(int,float)) and amount>0: data.setdefault(key+"_ctc_lpa",amount/100000)
    data.setdefault("interest_statement","I am interested in this opportunity because it aligns with my goal of growing in cloud infrastructure, automation and reliable software delivery. I would welcome the opportunity to contribute to the team and develop my technical expertise.")
    return data
def verification_required(page):
    """Detect an active human challenge without interacting with verification widgets."""
    frames=page.locator('iframe[src*="captcha" i], iframe[src*="challenge" i], iframe[src*="turnstile" i], iframe[title*="captcha" i], iframe[title*="challenge" i]')
    for i in range(frames.count()):
        frame=frames.nth(i)
        if not frame.is_visible(): continue
        bounds=frame.bounding_box()
        if not bounds or bounds["width"]<2 or bounds["height"]<2: continue
        title=(frame.get_attribute("title") or "").lower()
        src=(frame.get_attribute("src") or "").lower()
        # A small reCAPTCHA informational badge is not an interactive challenge.
        if ("recaptcha" in src or "recaptcha" in title) and bounds["width"]<=100 and bounds["height"]<=100 and "/bframe" not in src and "challenge" not in title:
            continue
        return True
    selectors=page.get_by_text(re.compile(r"^(verify (?:that )?you are (?:a )?human|complete the (?:captcha|security check)|please (?:complete|solve) the captcha|checking your browser|security verification|i am not a robot|i'm not a robot)[.!]?$",re.I))
    for i in range(min(selectors.count(),20)):
        if selectors.nth(i).is_visible(): return True
    return False

def portal_apply(job, profile, pdf, diagnostic=None):
    diagnostic=diagnostic if diagnostic is not None else {}
    stage="candidate"
    submitted=False
    try:
        if not pdf.startswith(b"%PDF-"): return "portal_review_invalid_resume"
        data=candidate_data(profile,pdf)
        data.setdefault("interest_statement","I am interested in this "+str(job.get("title","")).strip()+" opportunity because it aligns with my interest in cloud infrastructure, automation and reliable software delivery.")
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
            page.route("**/*", lambda route: route.abort() if route.request.is_navigation_request() and route.request.frame==page.main_frame and urlparse(route.request.url).hostname not in HOSTS else route.continue_())
            stage="navigation"
            page.goto(url,wait_until="domcontentloaded",timeout=45000)
            if u.hostname in ("job-boards.greenhouse.io","boards.greenhouse.io"):
                link=page.get_by_role("link",name=re.compile(r"^apply(?: now| for this job)?$",re.I))
                if link.count()==1 and link.is_visible(): link.click(timeout=10000)
            if urlparse(page.url).hostname not in HOSTS: return "portal_review_redirect"
            page.wait_for_timeout(2000)
            if verification_required(page): return "portal_review_human_verification_v2"
            stage="contact_fields"
            fields={"first_name":data.get("first_name"),"last_name":data.get("last_name"),"name":data.get("name"),"email":data.get("email"),"phone":data.get("phone"),"org":data.get("current_company"),"urls[LinkedIn]":data.get("linkedin"),"urls[GitHub]":data.get("github")}
            for key,val in fields.items():
                if not val: continue
                locator=page.locator('input[name="'+key+'"],input[id="'+key+'"]')
                if locator.count()==1 and locator.is_visible(): locator.fill(str(val))
            if u.hostname in HOSTS:
                for label,value in [(r"^(?:full |legal |your )?name\s*\*?$",data.get("name")),(r"^first name",data.get("first_name")),(r"^last name",data.get("last_name")),(r"^email",data.get("email")),(r"^phone",data.get("phone"))]:
                    field=page.get_by_label(re.compile(label,re.I))
                    if value and field.count()==1 and field.is_visible(): field.fill(str(value))
            stage="resume_field"
            files=page.locator('input[type=file][name="resume"], input[type=file][id="resume"], input[type=file][name="resumeFile"]')
            if files.count()==0:
                files=page.get_by_label(re.compile(r"resume|curriculum vitae",re.I)).and_(page.locator("input[type=file]"))
            if files.count()!=1: return "portal_review_resume_field"
            stage="screening"
            print("Screening fields filled:",fill_screening(page,data))
            missing=unanswered_required(page)
            if missing:
                diagnostic["missing_fields"]=missing
                return "portal_review_missing_screening_v3"
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
            if verification_required(page): return "portal_review_human_verification_v2"
            stage="resume_upload"
            files.set_input_files({"name":"Resume.pdf","mimeType":"application/pdf","buffer":pdf})
            if verification_required(page): return "portal_review_human_verification_v2"
            if not buttons.is_enabled(): return "portal_review_submit_disabled"
            stage="submit"
            responses=[]
            def capture(response):
                u=urlparse(response.url)
                if response.request.method!="POST" or u.hostname not in HOSTS|{"api.ashbyhq.com","api.lever.co","boards-api.greenhouse.io"}: return
                # No payloads, query parameters, cookies, or applicant data in reports.
                responses.append({"host":u.hostname,"status":response.status})
            page.on("response",capture)
            success=page.get_by_text(re.compile(r"^(?:thank you for applying|thanks for applying|(?:your )?application (?:has been )?(?:successfully )?(?:submitted|received))[.!]?$",re.I))
            def visible_success():
                return any(success.nth(i).is_visible() for i in range(min(success.count(),10)))
            already_visible=visible_success()
            diagnostic["attempted_at_utc"]=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
            submitted=True
            buttons.click(timeout=10000)
            stage="confirmation"
            for _ in range(30):
                if not already_visible and visible_success():
                    diagnostic["confirmation"]="new_visible_success_message"
                    return "portal_confirmed"
                if verification_required(page): return "portal_uncertain_human_verification_after_submit"
                page.wait_for_timeout(1000)
            invalid=page.locator("input:invalid:visible, textarea:invalid:visible, select:invalid:visible, [aria-invalid=true]:visible")
            diagnostic["invalid_field_count"]=invalid.count()
            diagnostic["visible_alert_count"]=page.get_by_role("alert").count()
            if any(x["status"]>=400 for x in responses):
                return "portal_uncertain_http_error"
            return "portal_uncertain_confirmation"
    except Exception as exc:
        print("Portal diagnostic:",stage,type(exc).__name__)
        return "portal_uncertain_"+stage if submitted else "portal_review_"+stage+"_error"
    finally:
        diagnostic["stage"]=stage
        if "responses" in locals(): diagnostic["post_responses"]=responses[:20]
