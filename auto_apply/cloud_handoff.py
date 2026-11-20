"""Opt-in Steel adapter. Never submit, bypass verification, or log capability URLs.

The caller must authorize a candidate's data transfer to the provider and store
the returned capability in a private, owner-scoped, short-lived session record.
Not connected to the production queue until that access-control layer is ready.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from uuid import UUID
import os
import re
import requests
from portal import HOSTS, candidate_data, verification_required
from screening import fill_screening, unanswered_required

API="https://api.steel.dev/v1/sessions"
MAX_SECONDS=600

class HandoffError(RuntimeError):
    pass

@dataclass(frozen=True)
class Handoff:
    session_id: str
    viewer_url: str=field(repr=False)
    expires_at: datetime
    reason: str
    resume_attached: bool
    fields_filled: int

def valid_url(url,scheme,hosts):
    try:
        u=urlparse(url)
        return u.scheme==scheme and u.hostname in hosts and not u.username and not u.password and u.port in (None,443)
    except (TypeError,ValueError):
        return False

class SteelSessions:
    def __init__(self,key=None,http=None):
        self.key=key or os.getenv("STEEL_API_KEY","")
        self.http=http or requests.Session()
        if not self.key:
            raise HandoffError("provider_not_configured")
    def call(self,method,path="",body=None):
        try:
            response=self.http.request(method,API+path,headers={"steel-api-key":self.key},json=body,timeout=30,allow_redirects=False)
            if not 200<=response.status_code<300:
                raise HandoffError("provider_http_"+str(response.status_code))
            return response.json()
        except HandoffError:
            raise
        except Exception:
            raise HandoffError("provider_request_failed") from None
    def create(self,seconds=MAX_SECONDS):
        seconds=max(60,min(MAX_SECONDS,int(seconds)))
        started=datetime.now(timezone.utc)
        result=self.call("POST",body={"headless":False,"timeout":seconds*1000,"recording":False,"solveCaptcha":False,"useProxy":False,"persistProfile":False,"debugConfig":{"interactive":True}})
        try:
            sid=str(UUID(result["id"]))
        except (KeyError,TypeError,ValueError):
            raise HandoffError("invalid_session_id") from None
        if result.get("status")!="live" or not valid_url(result.get("websocketUrl"),"wss",{"connect.steel.dev"}) or not valid_url(result.get("debugUrl"),"https",{"api.steel.dev"}):
            self.release(sid)
            raise HandoffError("invalid_provider_session")
        return sid,result["websocketUrl"],result["debugUrl"],started+timedelta(seconds=seconds)
    def release(self,session_id):
        self.call("POST","/"+str(UUID(session_id))+"/release",{})

def prepare_handoff(job,profile,pdf,*,consent=False,client=None):
    """Create one isolated, prefilled session, then disconnect automation.

    This function never clicks Submit. Caller MUST protect viewer_url as a
    bearer secret, not expose it in public logs, and release it on completion.
    If verification appears before prefill, the user receives a partial form.
    """
    if consent is not True: raise HandoffError("explicit_provider_consent_required")
    if not isinstance(pdf,bytes) or not pdf.startswith(b"%PDF-"): raise HandoffError("invalid_resume")
    url=job.get("apply_url") or job.get("url","")
    if not valid_url(url,"https",HOSTS): raise HandoffError("unsupported_employer")
    if urlparse(url).hostname=="jobs.lever.co":
        url=url.split("?",1)[0].rstrip("/")
        if not url.endswith("/apply"): url+="/apply"
    data=candidate_data(profile,pdf)
    if not all(data.get(k) for k in ("name","email","phone")): raise HandoffError("candidate_contact_required")
    client=client or SteelSessions()
    sid,cdp,viewer,expiry=client.create()
    keep=False
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser=p.chromium.connect_over_cdp(cdp,timeout=30000)
            # Use the provider's existing isolated context and page so the live
            # viewer sees the same page, never a second temporary context.
            if len(browser.contexts)!=1: raise HandoffError("unexpected_browser_contexts")
            context=browser.contexts[0]
            page=context.pages[0] if len(context.pages)==1 else None
            if page is None: raise HandoffError("unexpected_browser_pages")
            page.goto(url,wait_until="domcontentloaded",timeout=45000)
            if not valid_url(page.url,"https",HOSTS): raise HandoffError("unexpected_employer_redirect")
            if not verification_required(page) and urlparse(url).hostname in {"job-boards.greenhouse.io","boards.greenhouse.io"}:
                link=page.get_by_role("link",name=re.compile(r"^apply(?: now| for this job)?$",re.I))
                if link.count()==1 and link.is_visible(): link.click(timeout=10000)
            if not valid_url(page.url,"https",HOSTS): raise HandoffError("unexpected_employer_redirect")
            page.wait_for_timeout(1500)
            filled=0
            attached=False
            if not verification_required(page):
                fields={"name":"name","first_name":"first_name","last_name":"last_name","email":"email","phone":"phone","org":"current_company","urls[LinkedIn]":"linkedin"}
                for name,key in fields.items():
                    if verification_required(page): break
                    loc=page.locator('input[name="'+name+'"], input[id="'+name+'"]')
                    if data.get(key) and loc.count()==1 and loc.is_visible() and loc.is_enabled() and not loc.input_value().strip():
                        loc.fill(str(data[key]));filled+=1
                if not verification_required(page):
                    filled+=fill_screening(page,data,verification_required)
                if not verification_required(page):
                    files=page.locator('input[type=file][name="resume"],input[type=file][id="resume"],input[type=file][name="resumeFile"]')
                    if files.count()==0:
                        files=page.get_by_label(re.compile(r"resume|curriculum vitae",re.I)).and_(page.locator("input[type=file]"))
                    if files.count()==1:
                        files.set_input_files({"name":"Resume.pdf","mimeType":"application/pdf","buffer":pdf})
                        attached=bool(files.evaluate("el=>el.files.length"))
                # Never submit and never guess an autocomplete selection.
            reason="human_verification" if verification_required(page) else "review_remaining_fields"
            if not valid_url(page.url,"https",HOSTS): raise HandoffError("unexpected_employer_redirect")
            # Do not call browser.close(): disconnect Playwright, leave the
            # provider session alive until the bounded expiry or release.
        if expiry<=datetime.now(timezone.utc): raise HandoffError("session_expired_during_prefill")
        keep=True
        return Handoff(sid,viewer,expiry,reason,attached,filled)
    except HandoffError:
        raise
    except Exception:
        raise HandoffError("prefill_failed") from None
    finally:
        if not keep:
            try: client.release(sid)
            except Exception: pass

def smoke():
    """Synthetic fixture only. No employer, resume, or candidate data."""
    from playwright.sync_api import sync_playwright
    client=SteelSessions()
    sid,cdp,viewer,expiry=client.create(120)
    try:
        with sync_playwright() as p:
            browser=p.chromium.connect_over_cdp(cdp,timeout=30000)
            page=browser.contexts[0].pages[0]
            page.set_content('<label>Fixture<input id="fixture"></label>')
            page.locator("#fixture").fill("synthetic fixture")
        # Reconnect to the same provider browser; prove DOM state survives
        # detachment, not merely cookie restoration.
        with sync_playwright() as p:
            browser=p.chromium.connect_over_cdp(cdp,timeout=30000)
            assert browser.contexts[0].pages[0].locator("#fixture").input_value()=="synthetic fixture"
        print("Provider smoke: live URL present and in-memory field survived reconnect; interactive mobile control still requires user testing.")
    finally:
        client.release(sid)

if __name__=="__main__":
    try: smoke()
    except HandoffError as exc: raise SystemExit(str(exc)) from None
    except Exception: raise SystemExit("provider_smoke_failed") from None
