"""Public ATS preflight: never upload a resume, send personal data, or submit an application."""
import json
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from portal import verification_required
from screening import select_lever_location

URL="https://jobs.lever.co/lingarogroup/b4aa26da-1f29-42d0-818a-93577800bc6b/apply"
def main():
    counts={"maps_requests":0,"maps_failed":0,"maps_http_errors":0}
    trace={}
    def is_maps(url):
        host=urlparse(url).hostname or ""
        return host in {"maps.googleapis.com","maps.gstatic.com","places.googleapis.com"}
    def request(r):
        if is_maps(r.url): counts["maps_requests"]+=1
    def failed(r):
        if is_maps(r.url): counts["maps_failed"]+=1
    def response(r):
        if is_maps(r.url) and r.status>=400: counts["maps_http_errors"]+=1
    with sync_playwright() as p:
        browser=p.chromium.launch()
        page=browser.new_page()
        page.on("request",request)
        page.on("requestfailed",failed)
        page.on("response",response)
        try:
            page.goto(URL,wait_until="domcontentloaded",timeout=45000)
            page.wait_for_timeout(2000)
            if verification_required(page):
                result="verification"
            else:
                # Public city fixture only; no account or candidate profile is accessed.
                result=select_lever_location(page,{"current_location":"Hyderabad, Telangana, India"},verification_required,trace)
            print("Read-only preflight:",json.dumps({"result":result,"location":trace,"network":counts},sort_keys=True))
        except Exception as exc:
            print("Read-only preflight:",json.dumps({"result":"error","error_type":type(exc).__name__,"location":trace,"network":counts},sort_keys=True))
        finally:
            browser.close()

if __name__=="__main__":
    main()
