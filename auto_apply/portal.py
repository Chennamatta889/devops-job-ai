"""Conservative applicant-side browser adapter; never bypass challenges."""
import os, json, base64, re, io, imaplib, email, ssl
from urllib.parse import urlparse, parse_qs
from screening import fill_screening, unanswered_required, field_question

HOSTS={"job-boards.greenhouse.io","boards.greenhouse.io","jobs.lever.co","jobs.ashbyhq.com"}
_PRIVATE_LINKEDIN_CACHE={}
def portal_enabled(profile, pdf):
    return os.getenv("PORTAL_AUTO_APPLY","").strip().lower()!="false" and pdf.startswith(b"%PDF-")
def extract_candidate_linkedin(text, name):
    raw=str(text or "")
    strong=set(m.rstrip("/") for m in re.findall(r"(?is)linkedin.{0,400}?(https?://(?:www\.)?linkedin\.com/in/[A-Za-z0-9_%.-]+/?)",raw))
    if len(strong)==1:
        return next(iter(strong))
    urls=set(re.findall(r"https?://(?:www\.)?linkedin\.com/in/[A-Za-z0-9_%.-]+/?",raw,re.I))
    tokens=[token for token in re.findall(r"[a-z0-9]+",str(name or "").lower()) if len(token)>=4]
    matched=[]
    for url in urls:
        slug=url.rstrip("/").rsplit("/",1)[-1].lower()
        if tokens and any(token in slug for token in tokens):
            matched.append(url.rstrip("/"))
    matched=sorted(set(matched))
    return matched[0] if len(matched)==1 else ""

def linkedin_from_sent_mail(name):
    user=os.getenv("SMTP_USER",""); password=os.getenv("SMTP_APP_PASSWORD","")
    if not user or not password: return ""
    cache_key=(user.lower(),str(name).strip().lower())
    if cache_key in _PRIVATE_LINKEDIN_CACHE: return _PRIVATE_LINKEDIN_CACHE[cache_key]
    found=set()
    try:
        with imaplib.IMAP4_SSL("imap.gmail.com",993,ssl_context=ssl.create_default_context(),timeout=20) as box:
            box.login(user,password.replace(" ",""))
            status,_=box.select('"[Gmail]/Sent Mail"',readonly=True)
            if status!="OK":
                status,_=box.select('"[Gmail]/All Mail"',readonly=True)
            if status!="OK": return ""
            typ,ids=box.uid("search",None,"BODY",'"linkedin.com/in/"')
            if typ!="OK" or not (ids[0] or b"").strip():
                typ,ids=box.uid("search",None,"ALL")
            if typ!="OK": return ""
            for uid in (ids[0] or b"").split()[-60:]:
                typ,parts=box.uid("fetch",uid,"(BODY.PEEK[])")
                if typ!="OK": continue
                for item in parts:
                    if not isinstance(item,tuple): continue
                    msg=email.message_from_bytes(item[1])
                    chunks=[]
                    for part in msg.walk():
                        if part.get_content_maintype()=="multipart" or part.get_content_disposition()=="attachment": continue
                        if part.get_content_type() not in ("text/plain","text/html"): continue
                        raw=part.get_payload(decode=True)
                        if raw: chunks.append(raw.decode(part.get_content_charset() or "utf-8","ignore"))
                    link=extract_candidate_linkedin("\n".join(chunks),name)
                    if link: found.add(link)
        result=next(iter(found)) if len(found)==1 else ""
        _PRIVATE_LINKEDIN_CACHE[cache_key]=result
        return result
    except Exception:
        _PRIVATE_LINKEDIN_CACHE[cache_key]=""
        return ""

def candidate_data(profile, pdf):
    data=dict(profile)
    if os.getenv("PORTAL_PROFILE_JSON","").strip():
        data.update(json.loads(os.environ["PORTAL_PROFILE_JSON"]))
    if os.getenv("SCREENING_FACTS_JSON","").strip():
        data.update(json.loads(os.environ["SCREENING_FACTS_JSON"]))
    name=str(data.get("name","")).strip()
    if name:
        data.setdefault("first_name",name.split()[0])
        data.setdefault("last_name"," ".join(name.split()[1:]))
    data.setdefault("email",os.getenv("SMTP_USER",""))
    text=""
    if not data.get("phone") or not data.get("linkedin") or not data.get("current_company"):
        # Parse only unambiguous, explicitly identifiable resume facts.
        annotation_urls=set()
        try:
            from pypdf import PdfReader
            reader=PdfReader(io.BytesIO(pdf))
            pages=reader.pages
            text="\n".join(page.extract_text() or "" for page in pages)

            # Hyperlinks in PDFs are often stored as annotations rather than visible text.
            for page in pages:
                annots=page.get("/Annots",[]) or []
                for ref in annots:
                    try:
                        annot=ref.get_object() if hasattr(ref,"get_object") else ref
                        action=annot.get("/A") if hasattr(annot,"get") else None
                        action=action.get_object() if hasattr(action,"get_object") else action
                        uri=action.get("/URI") if hasattr(action,"get") else None
                        if isinstance(uri,str):
                            annotation_urls.add(uri.strip())
                    except Exception:
                        pass

            # Some PDF generators embed URI strings in the raw PDF object stream.
            try:
                raw_pdf=pdf.decode("latin1","ignore")
                for match in re.findall(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[A-Za-z0-9_%.-]+/?",raw_pdf,re.I):
                    annotation_urls.add(match)
            except Exception:
                pass
        except Exception:
            text=""
        matches=set(re.sub(r"[^0-9+]","",m) for m in re.findall(r"(?<!\d)(?:\+91[\s-]*)?[6-9]\d{4}[\s-]?\d{5}(?!\d)",text))
        normalized={"+91"+m[-10:] for m in matches}
        if len(normalized)==1 and not data.get("phone"): data["phone"]=normalized.pop()
        urls=set(re.findall(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[A-Za-z0-9_%.-]+/?",text,re.I))
        for value in annotation_urls:
            value=str(value or "").strip()
            match=re.search(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[A-Za-z0-9_%.-]+/?",value,re.I)
            if match:
                urls.add(match.group(0))
        normalized_urls=set()
        for link in urls:
            link=str(link).rstrip(".,);/")
            normalized_urls.add(link if link.startswith("http") else "https://"+link)
        if len(normalized_urls)==1 and not data.get("linkedin"):
            data["linkedin"]=normalized_urls.pop()
        companies=set(m.strip() for m in re.findall(r"(?im)^\s*current\s+(?:company|employer)\s*:\s*([^\n]{2,100})",text))
        if len(companies)==1 and not data.get("current_company"): data["current_company"]=companies.pop()
    if not data.get("linkedin") and os.getenv("ALLOW_PRIVATE_MAIL_LOOKUP","").strip().lower()=="true":
        private_link=linkedin_from_sent_mail(data.get("name",""))
        if private_link: data["linkedin"]=private_link
    print("Candidate LinkedIn available:",bool(data.get("linkedin")))
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

ASHBY_SUBMIT_OPS={"ApiSubmitSingleApplicationFormAction","ApiSubmitMultipleFormsAction"}
def ashby_submit_signal(payload):
    """Return only a safe submit classification; never return applicant data."""
    if not isinstance(payload,dict): return ""
    data=payload.get("data") or {}
    action=data.get("submitApplicationFormAction") or data.get("submitMultipleFormsAction")
    if not isinstance(action,dict): return ""
    messages=action.get("messages") or {}
    if isinstance(messages,dict) and messages.get("blockMessageForCandidateHtml"):
        return "blocked"
    result=action.get("applicationFormResult")
    if not isinstance(result,dict): return ""
    typename=str(result.get("__typename") or "")
    if typename=="FormSubmitSuccess":
        return "success"
    if typename=="FormRender" or "id" in result:
        return "validation"
    return ""

def portal_apply(job, profile, pdf, diagnostic=None):
    diagnostic=diagnostic if diagnostic is not None else {}
    stage="candidate"
    submitted=False
    try:
        if not pdf.startswith(b"%PDF-"): return "portal_review_invalid_resume"
        data=candidate_data(profile,pdf)
        data.setdefault("application_source","Company careers page")
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
            responses=[]
            ashby_signals=[]
            def capture(response):
                u=urlparse(response.url)
                if response.request.method!="POST" or u.hostname not in HOSTS|{"api.ashbyhq.com","api.lever.co","boards-api.greenhouse.io"}: return
                operation=parse_qs(u.query).get("op",[""])[0][:120]
                entry={
                    "host":u.hostname,
                    "path":(u.path or "/")[:240],
                    "status":response.status,
                    "content_type":(response.headers.get("content-type","").split(";")[0])[:80]
                }
                if operation:
                    entry["operation"]=operation
                if u.hostname=="jobs.ashbyhq.com" and operation in ASHBY_SUBMIT_OPS and response.status==200:
                    try:
                        signal=ashby_submit_signal(response.json())
                    except Exception:
                        signal=""
                    if signal:
                        entry["submit_result"]=signal
                        ashby_signals.append(signal)
                # Never persist request bodies, response bodies, cookies, query parameters or applicant values.
                responses.append(entry)
            page.on("response",capture)
            sync_ops={"ApiSetFormValue","ApiSetFormValueToFile","ApiCreateFileUploadHandle"}
            def submit_responses():
                return [x for x in responses if x.get("operation") in ASHBY_SUBMIT_OPS]
            def wait_form_quiet():
                if u.hostname!="jobs.ashbyhq.com": return True
                last=-1; stable=0
                for _ in range(40):
                    current=sum(1 for x in responses if x.get("operation") in sync_ops)
                    if current==last: stable+=1
                    else: last=current; stable=0
                    if stable>=6: return True
                    if verification_required(page): return False
                    page.wait_for_timeout(250)
                return False
            stage="resume_upload"
            files.set_input_files({"name":"Resume.pdf","mimeType":"application/pdf","buffer":pdf})
            if u.hostname=="jobs.ashbyhq.com":
                synced=False
                for _ in range(20):
                    if any(x.get("operation")=="ApiSetFormValueToFile" and 200<=x["status"]<300 for x in responses):
                        synced=True; break
                    if verification_required(page): return "portal_review_human_verification_v2"
                    page.wait_for_timeout(500)
                if not synced: return "portal_review_resume_sync"
            else:
                page.wait_for_timeout(1000)
            if verification_required(page): return "portal_review_human_verification_v2"
            for _ in range(20):
                if buttons.is_enabled(): break
                page.wait_for_timeout(500)
            if not buttons.is_enabled(): return "portal_review_submit_disabled"
            if not wait_form_quiet():
                if verification_required(page): return "portal_review_human_verification_v2"
                return "portal_review_form_sync_busy"
            stage="submit"
            success=page.get_by_text(re.compile(r"^(?:thank you for applying|thanks for applying|(?:your )?application (?:has been )?(?:successfully )?(?:submitted|received))[.!]?$",re.I))
            def visible_success():
                return any(success.nth(i).is_visible() for i in range(min(success.count(),10)))
            already_visible=visible_success()
            diagnostic["attempted_at_utc"]=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
            submitted=True
            buttons.click(timeout=10000)
            stage="confirmation"
            retried_click=False
            for tick in range(38):
                if "success" in ashby_signals:
                    diagnostic["confirmation"]="ashby_form_submit_success"
                    return "portal_confirmed"
                if "blocked" in ashby_signals:
                    diagnostic["confirmation"]="ashby_submit_blocked"
                    return "portal_review_submit_blocked"
                if "validation" in ashby_signals:
                    diagnostic["confirmation"]="ashby_form_render_validation"
                    return "portal_review_server_validation"
                if not already_visible and visible_success():
                    diagnostic["confirmation"]="new_visible_success_message"
                    return "portal_confirmed"
                if verification_required(page):
                    return "portal_uncertain_human_verification_after_submit" if submit_responses() else "portal_review_human_verification_v2"
                if u.hostname=="jobs.ashbyhq.com" and tick==7 and not submit_responses() and not retried_click:
                    invalid_now=page.locator("input:invalid:visible, textarea:invalid:visible, select:invalid:visible, [aria-invalid=true]:visible")
                    if invalid_now.count()==0 and wait_form_quiet() and buttons.is_enabled() and not verification_required(page):
                        diagnostic["second_click_after_no_submit"]=True
                        buttons.click(timeout=10000)
                        retried_click=True
                page.wait_for_timeout(1000)
            invalid=page.locator("input:invalid:visible, textarea:invalid:visible, select:invalid:visible, [aria-invalid=true]:visible")
            diagnostic["invalid_field_count"]=invalid.count()
            labels=[]
            for i in range(min(invalid.count(),20)):
                try:
                    label=field_question(invalid.nth(i))
                    if label and label not in labels: labels.append(label[:180])
                except Exception:
                    pass
            diagnostic["invalid_fields"]=labels
            diagnostic["visible_alert_count"]=page.get_by_role("alert").count()
            diagnostic["final_host"]=urlparse(page.url).hostname
            diagnostic["final_path"]=(urlparse(page.url).path or "/")[:240]
            submit_responses=[x for x in responses if x.get("operation") in ASHBY_SUBMIT_OPS] if u.hostname=="jobs.ashbyhq.com" else responses
            codes=[x["status"] for x in submit_responses]
            if "success" in ashby_signals:
                diagnostic["confirmation"]="ashby_form_submit_success"
                return "portal_confirmed"
            if "blocked" in ashby_signals:
                diagnostic["confirmation"]="ashby_submit_blocked"
                return "portal_review_submit_blocked"
            if "validation" in ashby_signals:
                diagnostic["confirmation"]="ashby_form_render_validation"
                return "portal_review_server_validation"
            if invalid.count():
                return "portal_review_validation_failed"
            if u.hostname=="jobs.ashbyhq.com" and not submit_responses():
                return "portal_review_no_submit_operation"
            if any(x==409 for x in codes):
                return "portal_review_duplicate_possible"
            if any(x in (400,422) for x in codes):
                return "portal_review_server_validation"
            if any(x in (401,403) for x in codes):
                return "portal_review_access_denied"
            if any(x==429 for x in codes):
                return "portal_review_rate_limited"
            if any(x>=500 for x in codes):
                return "portal_review_server_error"
            if any(200<=x<300 for x in codes):
                return "portal_uncertain_submit_response"
            return "portal_uncertain_no_submission_response"
    except Exception as exc:
        print("Portal diagnostic:",stage,type(exc).__name__)
        return "portal_uncertain_"+stage if submitted else "portal_review_"+stage+"_error"
    finally:
        diagnostic["stage"]=stage
        if "responses" in locals(): diagnostic["post_responses"]=responses[:20]
