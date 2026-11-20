"""Read-only public employer page probe. Synthetic attachment; all non-read HTTP blocked."""
import io,json,re
from playwright.sync_api import sync_playwright
from pypdf import PdfWriter
from portal import verification_required,resume_attachment_state
URL="https://job-boards.greenhouse.io/rzr/jobs/4254732009"
with sync_playwright() as p:
    browser=p.chromium.launch()
    context=browser.new_context(service_workers="block")
    blocked=[]
    def guard(route):
        if route.request.method not in ("GET","HEAD","OPTIONS"):
            blocked.append(route.request.method)
            return route.abort()
        return route.continue_()
    context.route("**/*",guard)
    page=context.new_page()
    page.goto(URL,wait_until="domcontentloaded",timeout=45000)
    page.wait_for_timeout(2000)
    link=page.get_by_role("link",name=re.compile(r"^apply(?: now| for this job)?$",re.I))
    if link.count()==1 and link.is_visible(): link.click(timeout=5000)
    if verification_required(page):
        print("PROBE: human verification; stopped.")
    else:
        files=page.locator('input[type=file][name="resume"],input[type=file][id="resume"],input[type=file][name="resumeFile"]')
        if files.count()==0: files=page.get_by_label(re.compile("resume|curriculum vitae",re.I)).and_(page.locator("input[type=file]"))
        print("PROBE before:",json.dumps(resume_attachment_state(page,files,"Resume.pdf")))
        if files.count()==1:
            pdf=PdfWriter()
            pdf.add_blank_page(width=72,height=72)
            out=io.BytesIO();pdf.write(out)
            files.set_input_files({"name":"Resume.pdf","mimeType":"application/pdf","buffer":out.getvalue()},timeout=5000)
            page.wait_for_timeout(1200)
            print("PROBE after:",json.dumps(resume_attachment_state(page,files,"Resume.pdf")))
            print("PROBE blocked non-read request count:",len(blocked))
            from playwright.sync_api import TimeoutError
            try:
                files.evaluate("el=>el.files && el.files.length>0",timeout=500)
                print("PROBE old locator still resolved")
            except TimeoutError:
                print("PROBE old locator timed out after upload")
    browser.close()
