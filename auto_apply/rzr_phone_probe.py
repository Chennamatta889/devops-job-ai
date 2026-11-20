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

def trace(page, label):
    details=page.locator('[aria-required=true]:visible,input:visible[required],textarea:visible[required],select:visible[required]').evaluate_all(r"""els=>els.map(el=>{
        const linked=el.tagName==='LABEL'?el.control:null;
        const controls=Array.from(new Set([...(linked?[linked]:[]),...el.querySelectorAll('input:not([type=hidden]),textarea,select')])).filter(c=>!c.disabled&&!c.readOnly);
        const text=[el.getAttribute('aria-label'),el.id,el.name,...Array.from(el.labels||[]).map(l=>l.innerText)].filter(Boolean).join(' ');
        return {tag:el.tagName,id:el.id,role:el.getAttribute('role'),type:el.type||null,label:text,required:el.required||false,ariaRequired:el.getAttribute('aria-required'),valueLength:typeof el.value==='string'?el.value.length:null,digitCount:typeof el.value==='string'?el.value.replace(/\D/g,'').length:null,attributeLength:el.getAttribute('value')?.length??null,valid:el.validity?.valid??null,ariaInvalid:el.getAttribute('aria-invalid'),controls:controls.map(c=>({type:c.type,role:c.getAttribute('role'),length:c.value?.length??null})),visible:!!el.getClientRects().length};
    }).filter(e=>/phone|country|mobile/i.test(e.label))""")
    missing=unanswered_required(page)
    print("PHONE TRACE",label,json.dumps({"required_controls":details,"phone_missing_labels":[x for x in missing if re.search(r'phone|mobile|country',x,re.I)],"invalid":validation_details(page)}))
    print("PHONE WIDGET",label,json.dumps(page.locator(".iti__selected-country,.iti__selected-dial-code,.iti__selected-flag").evaluate_all(r"""els=>els.filter(e=>e.getClientRects().length).map(e=>({label:e.getAttribute('aria-label'),title:e.getAttribute('title'),text:e.innerText}))""")))
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
        print("PHONE TRACE verification; stopped")
    else:
        trace(page,"before")
        fill_contact_fields(page,{"phone":FIXTURE},greenhouse=True)
        page.wait_for_timeout(250)
        trace(page,"production_fill")
        phone=page.locator('input[type=tel]#phone:visible')
        if phone.count()==1 and not verification_required(page):
            phone.fill("")
            phone.press_sequentially(FIXTURE,delay=25)
            phone.press("Tab")
            page.wait_for_timeout(450)
            trace(page,"typed_and_blurred")
        if not verification_required(page):
            country=page.locator('input#country[role=combobox]:visible')
            if country.count()==1:
                country.click()
                country.fill("India")
                page.wait_for_timeout(300)
                if not verification_required(page):
                    print("COUNTRY OPTIONS",json.dumps(page.get_by_role("option").evaluate_all("els=>els.filter(x=>x.getClientRects().length).map(x=>x.innerText).slice(0,10)")))
                    country.press("Escape")
    browser.close()
