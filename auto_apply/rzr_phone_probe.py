"""Public phone component diagnosis; no applicant data or submit, non-read traffic blocked."""
import json,re
from playwright.sync_api import sync_playwright
from portal import verification_required, fill_contact_fields, validation_details
from screening import unanswered_required
URL="https://job-boards.greenhouse.io/rzr/jobs/4254732009"
# A synthetic, non-user value is used only in browser memory; no form submission.
FIXTURE="+919876543210"
def snapshot(page):
    return page.locator('input:visible,select:visible,[aria-required=true]:visible,label:visible').evaluate_all(r"""els=>els.filter(el=>{
        const text=[el.id,el.name,el.getAttribute('aria-label'),el.getAttribute('autocomplete'),el.tagName==='LABEL'?el.innerText:'',...Array.from(el.labels||[]).map(l=>l.innerText)].filter(Boolean).join(' ');
        return /phone|mobile|country|tel/i.test(text)||el.type==='tel'||el.getAttribute('role')==='combobox'&&/country/i.test(text);
    }).map(el=>{
        const desc=x=>({tag:x.tagName,type:x.type||null,id:x.id||null,name:x.name||null,role:x.getAttribute('role'),ariaRequired:x.getAttribute('aria-required'),required:!!x.required,disabled:!!x.disabled,readOnly:!!x.readOnly,valueLength:typeof x.value==='string'?x.value.length:null,digitCount:typeof x.value==='string'?x.value.replace(/\D/g,'').length:null,ariaInvalid:x.getAttribute('aria-invalid'),valid:x.validity?.valid??null,pattern:x.getAttribute('pattern'),linkedControl:x.control?.id||null});
        return {...desc(el),label:el.tagName==='LABEL'?el.innerText:null,children:Array.from(el.querySelectorAll('input,select')).map(desc),parent:el.parentElement?{tag:el.parentElement.tagName,ariaRequired:el.parentElement.getAttribute('aria-required'),labels:Array.from(el.parentElement.querySelectorAll('label')).map(l=>({text:l.innerText,for:l.htmlFor})).slice(0,4),controls:Array.from(el.parentElement.querySelectorAll('input,select')).map(desc).slice(0,6)}:null};
    }).slice(0,20)""")
def phone_missing(page):
    return any(re.search(r'\bphone\b|\bmobile\b',x,re.I) for x in unanswered_required(page))
with sync_playwright() as p:
    browser=p.chromium.launch()
    context=browser.new_context(service_workers="block")
    context.route("**/*",lambda route: route.continue_() if route.request.method in ("GET","HEAD","OPTIONS") else route.abort())
    page=context.new_page()
    page.goto(URL,wait_until="domcontentloaded",timeout=45000)
    page.wait_for_timeout(2000)
    link=page.get_by_role("link",name=re.compile(r"^apply(?: now| for this job)?$",re.I))
    if link.count()==1 and link.is_visible(): link.click(timeout=5000)
    if verification_required(page):
        print("PHONE PROBE: human verification; stopped.")
    else:
        print("PHONE PROBE before:",json.dumps(snapshot(page)))
        print("PHONE PROBE missing before:",phone_missing(page))
        print("PHONE PROBE fill count:",fill_contact_fields(page,{"phone":FIXTURE},greenhouse=True))
        page.wait_for_timeout(300)
        print("PHONE PROBE after:",json.dumps(snapshot(page)))
        print("PHONE PROBE missing after:",phone_missing(page))
        print("PHONE PROBE invalid categories:",json.dumps(validation_details(page)))
        print("PHONE PROBE required markers:",json.dumps(page.locator('[aria-required=true]:visible').evaluate_all(r"""els=>els.filter(el=>/phone|mobile/i.test([el.getAttribute('aria-label'),el.id,el.innerText].filter(Boolean).join(' '))&&el.innerText.length<200).map(el=>({tag:el.tagName,role:el.getAttribute('role'),label:el.getAttribute('aria-label'),text:el.innerText.slice(0,100),html:el.outerHTML.slice(0,1200)})).slice(0,5)""")))
    browser.close()
