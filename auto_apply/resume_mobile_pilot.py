"""Resume prefill in the same user-authorized live browser. Never submit."""
from datetime import datetime, timezone
from urllib.parse import urlparse
import re
from uuid import UUID
from playwright.sync_api import sync_playwright
from cloud_handoff import SteelSessions, valid_url, HandoffError
from portal import HOSTS, candidate_data, verification_required
from supabase_worker import rest_get,get_profile,get_resume,download_resume,get_screening_answers,enrich_matching_profile,patch_attempt,CONSENT_VERSION
from mobile_pilot import update

def run():
    rows=rest_get("mobile_handoff_requests",{"attempt_id":"eq.6","status":"eq.READY","reason":"eq.human_verification","select":"*"})
    if len(rows)!=1: raise HandoffError("existing_session_unavailable")
    row=rows[0]; aid=row["attempt_id"]
    if datetime.fromisoformat(row["expires_at"].replace("Z","+00:00"))<=datetime.now(timezone.utc):
        raise HandoffError("existing_session_expired")
    attempts=rest_get("application_attempts",{"id":f"eq.{aid}","status":"eq.ASSISTANCE_REQUIRED","select":"*"})
    if len(attempts)!=1: raise HandoffError("application_no_longer_pending")
    attempt=attempts[0]
    viewer=row["viewer_url"]
    if not valid_url(viewer,"https",{"api.steel.dev"}): raise HandoffError("invalid_viewer")
    match=re.fullmatch(r"/v1/sessions/([0-9a-fA-F-]{36})/player(?:/.*)?",urlparse(viewer).path)
    if not match: raise HandoffError("session_id_unavailable")
    sid=str(UUID(match.group(1)))
    session=SteelSessions().call("GET","/"+sid)
    if session.get("status")!="live" or session.get("id")!=sid or not valid_url(session.get("websocketUrl"),"wss",{"connect.steel.dev"}):
        raise HandoffError("provider_session_not_live")
    expected=urlparse(attempt["apply_url"])
    filled=0; attached=False; blocked=False
    with sync_playwright() as p:
        browser=p.chromium.connect_over_cdp(session["websocketUrl"],timeout=20000)
        if len(browser.contexts)!=1 or len(browser.contexts[0].pages)!=1: raise HandoffError("unexpected_browser_pages")
        page=browser.contexts[0].pages[0]
        actual=urlparse(page.url)
        if not valid_url(page.url,"https",HOSTS) or actual.hostname!=expected.hostname or actual.path.rstrip("/")!=expected.path.rstrip("/"):
            raise HandoffError("application_page_changed")
        # Check the existing page, never navigate or interact with verification.
        if verification_required(page):
            print("Human verification still detected; no fields changed.")
            return
        profile=get_profile(attempt["user_id"]); resume=get_resume(attempt["user_id"])
        if not profile or not resume or not profile.get("auto_apply_enabled") or profile.get("consent_version")!=CONSENT_VERSION:
            raise HandoffError("candidate_profile_unavailable")
        pdf=download_resume(resume["storage_path"])
        if not pdf.startswith(b"%PDF-"): raise HandoffError("invalid_resume")
        data=candidate_data(enrich_matching_profile(profile),pdf)
        fields=[("first_name",r"^first name\b"),("last_name",r"^last name\b"),("name",r"^(?:full |legal |your )?name\s*\*?$"),("email",r"^email(?: address)?\b"),("phone",r"^(?:phone|mobile)(?: number)?\b"),("linkedin",r"^linkedin(?: profile| url)?\b")]
        for key,label in fields:
            if verification_required(page): blocked=True; break
            if not data.get(key): continue
            loc=page.get_by_label(re.compile(label,re.I))
            if loc.count()!=1: loc=page.locator('input[name="'+key+'"],input[id="'+key+'"]')
            if loc.count()==1 and loc.is_visible() and loc.is_enabled() and not loc.input_value().strip():
                loc.fill(str(data[key]));filled+=1
        if not verification_required(page):
            files=page.locator('input[type=file][name="resume"],input[type=file][id="resume"],input[type=file][name="resumeFile"]')
            if files.count()==0: files=page.get_by_label(re.compile(r"resume|curriculum vitae",re.I)).and_(page.locator("input[type=file]"))
            if files.count()==1:
                if files.evaluate("el=>el.files.length")==0:
                    files.set_input_files({"name":"Resume.pdf","mimeType":"application/pdf","buffer":pdf})
                attached=bool(files.evaluate("el=>el.files.length"))
        blocked=verification_required(page)
        # Leave browser alive; user owns all remaining actions and submission.
    patch={"fields_filled":row["fields_filled"]+filled,"resume_attached":row["resume_attached"] or attached,"reason":"human_verification" if blocked else "review_remaining_fields"}
    update(aid,"READY",patch)
    patch_attempt(aid,"ASSISTANCE_REQUIRED",{"message":f"Resumed existing session: {filled} additional contact fields filled; resume attachment detected: {'yes' if attached else 'no'}. Review and submit yourself.","updated_at":datetime.now(timezone.utc).isoformat()})
    print("Existing session prefill:",filled,"contact fields; resume attached:",attached,"verification detected:",blocked)
if __name__=="__main__":
    try: run()
    except HandoffError as exc: raise SystemExit(str(exc)) from None
    except Exception as exc: raise SystemExit("resume_error:"+type(exc).__name__) from None
