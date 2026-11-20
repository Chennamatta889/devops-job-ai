"""Conservative applicant-side browser adapter; never bypass challenges."""
import os, json, base64, re, io, imaplib, email, ssl
from urllib.parse import urlparse, parse_qs
from screening import fill_screening, unanswered_required, field_question, select_lever_location

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
def passive_recaptcha_frame(src, title, bounds):
    """Recognize only Google-owned informational/invisible anchor frames.

    Never classify a challenge frame or an unknown provider as passive.
    A passive anchor is not a verification result and does not disable or
    alter the site's verification. Active challenges still stop automation.
    """
    try:
        u=urlparse(src)
        if u.scheme!="https" or u.hostname not in {"www.google.com","www.recaptcha.net","recaptcha.google.com"} or u.username or u.password or u.port not in (None,443):
            return False
        if not re.fullmatch(r"/recaptcha/(?:api2|enterprise)/anchor",u.path):
            return False
        if "challenge" in title.lower():
            return False
        values=parse_qs(u.query).get("size",[])
        return values==["invisible"]
    except (TypeError,ValueError):
        return False

def verification_required(page):
    """Fail closed on visible challenges; ignore only recognized passive embeds."""
    selectors=page.get_by_text(re.compile(r"^(verify (?:that )?you are (?:a )?human|complete the (?:captcha|security check)|please (?:complete|solve) the captcha|checking your browser|security verification|i am not a robot|i'm not a robot)[.!]?$",re.I))
    for i in range(min(selectors.count(),20)):
        if selectors.nth(i).is_visible(): return True
    frames=page.locator('iframe[src*="captcha" i], iframe[src*="challenge" i], iframe[src*="turnstile" i], iframe[title*="captcha" i], iframe[title*="challenge" i]')
    for i in range(frames.count()):
        frame=frames.nth(i)
        if not frame.is_visible(): continue
        bounds=frame.bounding_box()
        if not bounds or bounds["width"]<2 or bounds["height"]<2: continue
        title=(frame.get_attribute("title") or "")
        src=(frame.get_attribute("src") or "")
        if passive_recaptcha_frame(src,title,bounds): continue
        return True
    return False

def validation_details(page):
    """Safe diagnostic categories and validity flags, never field values."""
    return page.locator("input:invalid:visible, textarea:invalid:visible, select:invalid:visible, [aria-invalid=true]:visible").evaluate_all(r"""els=>els.slice(0,20).map(el=>{
        const labels=Array.from(el.labels||[]).map(x=>x.innerText).join(' ');
        const prompt=(labels+' '+(el.getAttribute('aria-label')||'')+' '+(el.id||'')+' '+(el.name||'')).toLowerCase();
        const category=/phone|mobile/.test(prompt)?'phone':/country/.test(prompt)?'country':/email/.test(prompt)?'email':/linkedin/.test(prompt)?'linkedin':/resume|cv/.test(prompt)?'resume':/first.?name/.test(prompt)?'first_name':/last.?name/.test(prompt)?'last_name':/website/.test(prompt)?'website':'other';
        const flags=['valueMissing','typeMismatch','patternMismatch','tooLong','tooShort','rangeUnderflow','rangeOverflow','stepMismatch','badInput','customError'].filter(k=>el.validity?.[k]);
        if(el.getAttribute('aria-invalid')==='true')flags.push('ariaInvalid');
        return {category,flags};
    })""")

def greenhouse_india_selected(field):
    """Verify a rendered selection, never the transient search text.

    Greenhouse's dialing-code picker renders a flag and +91, not "India".
    A scoped selected-value element with India's flag and exactly +91 is proof.
    """
    return field.evaluate(r"""el=>{
        if(el.getAttribute('aria-expanded')==='true'||el.getAttribute('aria-invalid')==='true')return false;
        let parent=el.parentElement;
        for(let i=0;i<5&&parent;i++,parent=parent.parentElement){
            if(parent.matches('form,body,main')||parent.querySelectorAll('[role=combobox]').length>1)break;
            const nodes=Array.from(parent.querySelectorAll('[class*="singleValue"],[class*="single-value"],[aria-selected=true]')).filter(x=>x.getClientRects().length&&!x.closest('[role=listbox]')&&getComputedStyle(x).visibility!=='hidden');
            if(!nodes.length)continue;
            if(nodes.length!==1)return false;
            const node=nodes[0];
            const text=node.innerText.trim();
            const flags=node.querySelectorAll('.iti__flag');
            if(flags.length)return flags.length===1&&flags[0].classList.contains('iti__in')&&/^\+91$|^India\s*(?:\(\+91\)|\+91)?$/i.test(text);
            return /^India\s*(?:\(\+91\)|\+91)?$/i.test(text);
        }
        return false;
    }""")

def fill_greenhouse_country(page,data):
    """Select India only from an unambiguous visible option and confirmed facts."""
    facts=data.get("screening_answers") or {}
    country=str(data.get("country") or next((v for k,v in facts.items() if str(k).strip().lower() in ("country","country of residence")), "") if isinstance(facts,dict) else data.get("country") or "").strip().lower()
    digits=re.sub(r"\D","",str(data.get("phone") or ""))
    if re.fullmatch(r"91[6-9]\d{9}",digits) and str(data.get("phone")).strip().startswith("+"):
        national=digits[2:]
        if country and country not in ("india","in"): return None
    elif country in ("india","in") and re.fullmatch(r"[6-9]\d{9}",digits):
        national=digits
    else:
        return None
    if verification_required(page): return None
    field=page.get_by_role("combobox",name=re.compile(r"^country(?: code)?\s*\*?$",re.I))
    if field.count()!=1:
        field=page.get_by_label(re.compile(r"^country(?: code)?\s*\*?$",re.I))
    if field.count()!=1 or not field.is_visible() or not field.is_enabled(): return None
    tag=field.evaluate("el=>el.tagName.toLowerCase()")
    is_india=re.compile(r"^(?:India(?:\s*\(\+91\)|\s+\+91)?|\+91\s+India)$",re.I)
    if tag=="select":
        options=field.locator("option").evaluate_all("els=>els.map(e=>({label:e.textContent.trim(),value:e.value,selected:e.selected,disabled:e.disabled}))")
        candidates=[x for x in options if not x["disabled"] and is_india.fullmatch(x["label"])]
        if len(candidates)!=1: return None
        selected=[x for x in options if x["selected"] and x["value"]]
        if selected and selected[0]["value"]!=candidates[0]["value"]: return None
        if not candidates[0]["selected"]: field.select_option(value=candidates[0]["value"])
        return national if field.input_value()==candidates[0]["value"] else None
    # Only a labelled dropdown with a visible, exact country option is eligible.
    if field.get_attribute("role")!="combobox": return None
    field.click()
    if verification_required(page): return None
    if field.evaluate("el=>el.tagName.toLowerCase()==='input'") and field.is_editable():
        field.fill("India")
    options=page.get_by_role("option",name=is_india)
    for _ in range(12):
        if verification_required(page): return None
        visible=[options.nth(i) for i in range(options.count()) if options.nth(i).is_visible() and options.nth(i).is_enabled()]
        if len(visible)==1: break
        page.wait_for_timeout(150)
    if len(visible)!=1:
        field.press("Escape")
        return None
    visible[0].click()
    if verification_required(page): return None
    return national if greenhouse_india_selected(field) else None


def greenhouse_phone_state(page,data):
    """Read only the displayed country selection and actual phone value.

    The provider's international phone widget may format the national number
    with a trunk prefix. Never treat an empty field or wrong digits as complete.
    """
    expected=re.sub(r"\D","",str(data.get("phone") or ""))
    if not re.fullmatch(r"91[6-9]\d{9}",expected):
        return {"verified":False,"reason":"unsupported_number"}
    loc=page.locator('input#phone[type=tel]:visible')
    country=page.locator('input#country[role=combobox]:visible')
    if loc.count()!=1 or country.count()!=1:
        return {"verified":False,"reason":"phone_widget_unresolved"}
    c=greenhouse_india_selected(country)
    observed=loc.evaluate(r"""el=>{
        let api=null;
        try {
            api=window.intlTelInput?.getInstance?.(el)||window.intlTelInputGlobals?.getInstance?.(el)||null;
        }catch(e){}
        let selected='',number='',widgetValid=null;
        if(api){
            try {selected=String(api.getSelectedCountryData?.()?.iso2||'');number=String(api.getNumber?.()||'');}catch(e){}
            try {const v=api.isValidNumber?.();if(typeof v==='boolean')widgetValid=v;}catch(e){}
        }
        const widget=el.closest('.iti');
        const widgetExpected=!!widget||el.hasAttribute('data-intl-tel-input-id');
        let widgetSelectionVerified=!widgetExpected;
        if(widget){
            // Greenhouse supplies a separate visible country picker and hides this widget's redundant button; read only its scoped selected state.
            const buttons=Array.from(widget.querySelectorAll('button.iti__selected-country'));
            if(buttons.length===1){
                const b=buttons[0];
                const flags=b.querySelectorAll('.iti__flag');
                const label=b.getAttribute('aria-label')||'';
                widgetSelectionVerified=b.getAttribute('aria-expanded')!=='true'&&/^India$/i.test(b.getAttribute('title')||'')&&/\bselected India\s*\(\+91\)/i.test(label)&&flags.length===1&&flags[0].classList.contains('iti__in');
            }
        }
        return {digits:String(el.value||'').replace(/\D/g,''),number:number.replace(/\D/g,''),selected,widgetValid,widgetExpected,widgetSelectionVerified,valid:el.validity?.valid===true,ariaInvalid:el.getAttribute('aria-invalid')==='true'};
    }""")
    national=expected[2:]
    matches=observed["digits"] in {expected,national,"0"+national}
    widget_matches=not observed["number"] or observed["number"]==expected
    widget_country=(not observed["selected"] or observed["selected"].lower()=="in") and observed["widgetSelectionVerified"]
    verified=bool(c and matches and widget_matches and widget_country and observed["widgetValid"] is not False and observed["valid"] and not observed["ariaInvalid"])
    return {"verified":verified,"country_selected":bool(c),"digits_match":matches,"widget_number_match":widget_matches,"widget_country_match":widget_country,"widget_selection_verified":observed["widgetSelectionVerified"],"widget_valid":observed["widgetValid"],"native_valid":observed["valid"],"aria_invalid":observed["ariaInvalid"]}

def fill_contact_fields(page,data,greenhouse=False):
    """Only fill ordinary empty candidate inputs, stopping on active verification."""
    filled=0
    fields=(
        ("first_name",r"^first name\b"),
        ("last_name",r"^last name\b"),
        ("name",r"^(?:full |legal |your )?name\s*\*?$"),
        ("email",r"^email(?: address)?\b"),
        ("phone",r"^(?:phone|mobile)(?: number)?\b"),
        ("org",r"^current (?:company|employer)\b"),
        ("urls[LinkedIn]",r"^linkedin(?: profile| url)?\b"),
        ("urls[GitHub]",r"^github(?: profile| url)?\b"),
    )
    data_keys={"org":"current_company","urls[LinkedIn]":"linkedin","urls[GitHub]":"github"}
    national=fill_greenhouse_country(page,data) if greenhouse else None
    for key,label in fields:
        if verification_required(page): break
        value=national if key=="phone" and national else data.get(data_keys.get(key,key))
        if not value: continue
        loc=page.locator('input[name="'+key+'"]:visible,input[id="'+key+'"]:visible')
        if loc.count()!=1:
            loc=page.get_by_label(re.compile(label,re.I)).and_(page.locator("input:visible"))
        if key=="phone" and loc.count()!=1:
            loc=page.locator('input[type="tel"]:visible')
        if loc.count()==1 and loc.is_visible() and loc.is_enabled() and loc.get_attribute("readonly") is None:
            if loc.get_attribute("type") in ("hidden","checkbox","radio","file","password","submit","button"): continue
            present=loc.input_value().strip()
            # A bare dialing prefix is not a populated phone number.
            if key=="phone" and present in ("+91","+91-","+91 (") and re.fullmatch(r"\+91[6-9]\d{9}",str(data.get("phone") or "")):
                value=str(data["phone"])
            elif present: continue
            loc.fill(str(value));filled+=1
            if greenhouse and key=="phone":
                loc.press("Tab")
    return filled

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

def resume_attachment_state(page, files, filename):
    """Snapshot without waiting for an input that the application may remove."""
    native=files.evaluate_all("(els)=>({input_count:els.length, matching_file_count:els.reduce((n,e)=>n+Array.from(e.files||[]).filter(f=>f.name=== "+json.dumps(filename)+").length,0)})")
    previews=page.get_by_text(filename,exact=True).evaluate_all(r"""els=>els.map(el=>{
        const visible=e=>!!(e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden'&&getComputedStyle(e).display!=='none');
        if(!visible(el))return false;
        let parent=el;
        for(let i=0;i<4&&parent;i++,parent=parent.parentElement){
            if(parent.matches('form,body,main'))break;
            for(const b of parent.querySelectorAll('button,[role=button],a')){
                if(!visible(b))continue;
                const text=[b.innerText,b.getAttribute('aria-label'),b.getAttribute('title')].filter(Boolean).join(' ');
                if(/\b(remove|delete|clear|replace)\b/i.test(text))return true;
            }
        }
        return false;
    })""")
    native["preview_with_remove"]=sum(bool(x) for x in previews)
    native["attached"]=(native["input_count"]==1 and native["matching_file_count"]==1) or native["preview_with_remove"]==1
    return native

def verify_resume_attachment(page,files,filename,diagnostic):
    for _ in range(40):
        diagnostic["validation_step"]="resume_attachment_snapshot"
        if verification_required(page): return "verification"
        snapshot=resume_attachment_state(page,files,filename)
        diagnostic["resume_attachment"]=snapshot
        if snapshot["attached"]: return "attached"
        page.wait_for_timeout(250)
    return "unverified"

def required_after_resume(page,data=None,greenhouse=False,diagnostic=None):
    # Only called after the exact filename and a native file or removable preview are verified.
    missing=[label for label in unanswered_required(page)
             if not re.fullmatch(r"(?:resume(?:\s*/\s*cv)?|curriculum vitae)(?:\s*\*)?",label.strip(),re.I)]
    if greenhouse and data and page.locator('input#country[role=combobox]:visible').count()==1 and page.locator('input#phone[type=tel]:visible').count()==1:
        state=greenhouse_phone_state(page,data)
        if diagnostic is not None: diagnostic["phone_widget"]=state
        if state["verified"]:
            # React search inputs clear on selection. Validate the visible selection
            # and exact candidate number instead of treating search text as data.
            missing=[label for label in missing if not re.fullmatch(r"(?:phone(?: number)?|country(?: code)?)(?:\s*\*)?",label.strip(),re.I)]
        elif not any(re.fullmatch(r"phone(?: number)?(?:\s*\*)?",label.strip(),re.I) for label in missing):
            missing.append("Phone")
    return missing

def application_email_code_controls(page, job_url):
    """Identify only a visible post-submit job-board email code form, not login/MFA/CAPTCHA."""
    current=urlparse(page.url); target=urlparse(job_url)
    if current.scheme!="https" or current.hostname not in {"job-boards.greenhouse.io","boards.greenhouse.io"} or current.hostname!=target.hostname or current.path.rstrip("/")!=target.path.rstrip("/"):
        return None
    if verification_required(page): return None
    return email_code_form(page)

def email_code_form(page):
    """Strict scoped code input and verification action; never infer missing controls."""
    notice=re.compile(r"(?:verification|security|confirmation) code (?:was |has been )?sent to|(?:sent|emailed) (?:you )?(?:a |an |the )?(?:verification|security|confirmation) code|code (?:from|in) your email",re.I)
    forbidden=re.compile(r"\b(?:sign in|log in|login|password|two.factor authentication|multi.factor authentication|captcha|authenticator app)\b",re.I)
    label=re.compile(r"^(?:(?:enter (?:the |your )?)?(?:email |security |verification |confirmation )?code)(?:\s*\*)?$",re.I)
    action=re.compile(r"^(?:verify(?: (?:email|code|and submit))?|submit(?: (?:application|code))?|confirm(?: (?:email|code))?|continue)$",re.I)
    scopes=page.get_by_role("dialog").filter(has_text=notice)
    if scopes.count()==0: scopes=page.locator("form:visible").filter(has_text=notice)
    visible=[scopes.nth(i) for i in range(scopes.count()) if scopes.nth(i).is_visible()]
    if len(visible)!=1: return None
    scope=visible[0]
    if forbidden.search(scope.inner_text()) or scope.locator('input[type=password]').count(): return None
    field=scope.get_by_label(label).and_(scope.locator('input:visible:not([type=hidden]):not([type=password])'))
    if field.count()!=1: field=scope.locator('input[autocomplete="one-time-code"]:visible')
    button=scope.get_by_role("button",name=action)
    if field.count()!=1 or button.count()!=1 or not field.is_enabled() or not field.is_editable() or not button.is_visible(): return None
    return field,button

def enter_application_email_code(page, code, locate_controls, diagnostic, timeout_ms=12000):
    """Enter a human-provided code through normal UI events and wait for readiness.

    Never enable a disabled control, retry a code automatically, or act on CAPTCHA.
    The return value is a safe status category, never the code or a field value.
    """
    import time
    if verification_required(page): return "human_verification"
    controls=locate_controls()
    if not controls: return "form_unavailable"
    field,button=controls
    if field.input_value(): return "field_not_empty"
    # Some controlled inputs depend on per-key event handling.
    field.press_sequentially(code,delay=45,timeout=5000)
    diagnostic["email_code_typed"]=True
    if verification_required(page): return "human_verification"
    deadline=time.monotonic()+timeout_ms/1000
    while time.monotonic()<deadline:
        if verification_required(page): return "human_verification"
        controls=locate_controls()
        if controls:
            field,button=controls
            same=field.input_value()==code
            diagnostic["email_code_value_matches"]=same
            valid=field.evaluate("el=>el.validity?.valid!==false && el.getAttribute('aria-invalid')!=='true'")
            diagnostic["email_code_input_valid"]=valid
            enabled=button.is_enabled()
            diagnostic["email_verify_button_enabled"]=enabled
            if same and valid and enabled:
                # The final click uses ordinary actionability checks.
                if verification_required(page): return "human_verification"
                button.click(timeout=5000)
                diagnostic["email_verify_clicked"]=True
                return "clicked"
        page.wait_for_timeout(150)
    return "button_not_ready"

def portal_apply(job, profile, pdf, diagnostic=None, email_code_provider=None):
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
            stage="location_preflight"
            if u.hostname == "jobs.lever.co":
                location_result = select_lever_location(page, data, verification_required, diagnostic.setdefault("location_trace", {}))
                if location_result == "verification":
                    return "portal_review_human_verification_v2"
                if location_result == "unresolved":
                    if diagnostic["location_trace"].get("result") == "missing_profile_answer":
                        diagnostic["missing_fields"] = ["Current location"]
                        return "portal_review_missing_screening_v3"
                    return "portal_review_location_autocomplete"
            stage="contact_fields"
            diagnostic["contact_fields_filled"]=fill_contact_fields(page,data,greenhouse=u.hostname in {"job-boards.greenhouse.io","boards.greenhouse.io"})
            if verification_required(page): return "portal_review_human_verification_v2"
            stage="resume_field"
            files=page.locator('input[type=file][name="resume"], input[type=file][id="resume"], input[type=file][name="resumeFile"]')
            if files.count()==0:
                files=page.get_by_label(re.compile(r"resume|curriculum vitae",re.I)).and_(page.locator("input[type=file]"))
            if files.count()!=1: return "portal_review_resume_field"
            stage="screening"
            if verification_required(page): return "portal_review_human_verification_v2"
            print("Screening fields filled:",fill_screening(page,data,verification_required))
            if verification_required(page): return "portal_review_human_verification_v2"
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
            stage="final_validation"
            if verification_required(page): return "portal_review_human_verification_v2"
            attachment_result=verify_resume_attachment(page,files,"Resume.pdf",diagnostic)
            if attachment_result=="verification": return "portal_review_human_verification_v2"
            if attachment_result!="attached": return "portal_review_resume_sync"
            diagnostic["validation_step"]="required_controls"
            missing=required_after_resume(page,data,greenhouse=u.hostname in {'job-boards.greenhouse.io','boards.greenhouse.io'},diagnostic=diagnostic)
            if missing:
                diagnostic["missing_fields"]=missing
                return "portal_review_missing_screening_v3"
            diagnostic["validation_step"]="invalid_controls"
            invalid=page.locator("input:invalid:visible, textarea:invalid:visible, select:invalid:visible, [aria-invalid=true]:visible")
            if invalid.count():
                diagnostic["invalid_field_count"]=invalid.count()
                diagnostic["validation_details"]=validation_details(page)
                return "portal_review_validation_failed"
            for _ in range(20):
                if buttons.is_enabled(): break
                page.wait_for_timeout(500)
            if not buttons.is_enabled(): return "portal_review_submit_disabled"
            if not wait_form_quiet():
                if verification_required(page): return "portal_review_human_verification_v2"
                return "portal_review_form_sync_busy"
            stage="final_validation"
            if verification_required(page): return "portal_review_human_verification_v2"
            attachment_result=verify_resume_attachment(page,files,"Resume.pdf",diagnostic)
            if attachment_result=="verification": return "portal_review_human_verification_v2"
            if attachment_result!="attached": return "portal_review_resume_sync"
            diagnostic["validation_step"]="required_controls"
            missing=required_after_resume(page,data,greenhouse=u.hostname in {'job-boards.greenhouse.io','boards.greenhouse.io'},diagnostic=diagnostic)
            if missing:
                diagnostic["missing_fields"]=missing
                return "portal_review_missing_screening_v3"
            diagnostic["validation_step"]="invalid_controls"
            invalid=page.locator("input:invalid:visible, textarea:invalid:visible, select:invalid:visible, [aria-invalid=true]:visible")
            if invalid.count():
                diagnostic["invalid_field_count"]=invalid.count()
                diagnostic["validation_details"]=validation_details(page)
                return "portal_review_validation_failed"
            stage="submit"
            if verification_required(page): return "portal_review_human_verification_v2"
            success=page.get_by_text(re.compile(r"^(?:thank you for applying|thanks for applying|(?:your )?application (?:has been )?(?:successfully )?(?:submitted|received))[.!]?$",re.I))
            def visible_success():
                return any(success.nth(i).is_visible() for i in range(min(success.count(),10)))
            already_visible=visible_success()
            diagnostic["attempted_at_utc"]=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
            diagnostic["submit_clicked"]=True
            response_count_before_click=len(responses)
            submitted=True
            buttons.click(timeout=10000)
            stage="confirmation"
            email_code_used=False
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
                    return "portal_uncertain_human_verification_after_submit"
                if application_email_code_controls(page,url):
                    diagnostic["email_verification_required"]=True
                    if not email_code_used:
                        if email_code_provider is None:
                            return "portal_uncertain_email_verification_required"
                        stage="email_verification"
                        code=email_code_provider(page,lambda: application_email_code_controls(page,url) is not None)
                        if not code:
                            return "portal_uncertain_email_verification_expired"
                        diagnostic["email_code_received"]=True
                        outcome=enter_application_email_code(page,code,lambda: application_email_code_controls(page,url),diagnostic)
                        code=None
                        diagnostic["email_code_outcome"]=outcome
                        if outcome=="human_verification": return "portal_uncertain_human_verification_after_submit"
                        if outcome!="clicked": return "portal_uncertain_email_code_"+outcome
                        email_code_used=True
                        stage="confirmation"
                        # Observe the normal confirmation UI for a full bounded interval.
                        # The dialog may remain visible during server validation.
                        verify_deadline=__import__("time").monotonic()+38
                        while __import__("time").monotonic()<verify_deadline:
                            if not already_visible and visible_success():
                                diagnostic["confirmation"]="new_visible_success_message"
                                return "portal_confirmed"
                            if verification_required(page):
                                return "portal_uncertain_human_verification_after_submit"
                            page.wait_for_timeout(500)
                        return "portal_uncertain_email_code_not_confirmed"
                page.wait_for_timeout(1000)
            diagnostic["validation_step"]="invalid_controls"
            invalid=page.locator("input:invalid:visible, textarea:invalid:visible, select:invalid:visible, [aria-invalid=true]:visible")
            diagnostic["invalid_field_count"]=invalid.count()
            diagnostic["validation_details"]=validation_details(page)
            diagnostic["post_click_response_count"]=len(responses)-response_count_before_click
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
                return "portal_uncertain_validation_after_submit"
            if u.hostname=="jobs.ashbyhq.com" and not submit_responses():
                return "portal_uncertain_no_submit_operation"
            if any(x==409 for x in codes):
                return "portal_uncertain_duplicate_possible"
            if any(x in (400,422) for x in codes):
                return "portal_uncertain_http_validation_after_submit"
            if any(x in (401,403) for x in codes):
                return "portal_uncertain_access_denied_after_submit"
            if any(x==429 for x in codes):
                return "portal_uncertain_rate_limited_after_submit"
            if any(x>=500 for x in codes):
                return "portal_uncertain_server_error"
            if any(200<=x<300 for x in codes):
                return "portal_uncertain_submit_response"
            return "portal_uncertain_no_submission_response"
    except Exception as exc:
        diagnostic["exception_type"]=type(exc).__name__
        print("Portal diagnostic:",stage,diagnostic.get("validation_step",""),type(exc).__name__)
        return "portal_uncertain_"+stage if submitted else "portal_review_"+stage+"_error"
    finally:
        diagnostic["stage"]=stage
        if "responses" in locals(): diagnostic["post_responses"]=responses[:20]
