"""Screening answers use explicit candidate facts, never guessed declarations."""
import re
def normalize(s):
    return re.sub(r"[^a-z0-9]+"," ",str(s or "").lower()).strip()
def answer_for(question, profile):
    q=normalize(question)
    if not q: return None
    answers=profile.get("screening_answers",{})
    if isinstance(answers,dict):
        for key,value in answers.items():
            if normalize(key)==q and isinstance(value,(str,int,float,bool)):
                return value
    fields=(
        (r"^(?:what is your )?(?:current (?:company|employer|organization)|company name)$","current_company"),
        (r"^(?:what is your )?(?:current location|current city|city of residence)$","current_location"),
        (r"^(?:what is your )?(?:notice period in days|notice period days|how many days is your notice period)$","notice_period_days"),
        (r"^(?:what is your )?(?:total (?:work |professional )?experience in years|total years of experience|years of professional experience|how many years of (?:total |professional |work )?experience do you have)$","experience_years"),
        (r"^(?:what is your )?(?:linkedin profile|linkedin profile url|linkedin url)$","linkedin"),
        (r"^(?:what is your )?(?:github profile|github profile url|github url)$","github"),
        (r"^(?:what is your )?(?:highest qualification|highest educational qualification)$","education"),
    )
    for pattern,key in fields:
        if re.fullmatch(pattern,q) and profile.get(key) is not None and profile.get(key)!="":
            return profile[key]
    return None
def as_text(value):
    if isinstance(value,bool): return "Yes" if value else "No"
    return str(value)
def field_question(field):
    return field.evaluate("""el => {
        const labels=Array.from(el.labels||[]).map(l=>l.innerText);
        const ids=(el.getAttribute('aria-labelledby')||'').split(/\\s+/).filter(Boolean);
        const aria=ids.map(id=>document.getElementById(id)?.innerText||'');
        const group=el.closest('fieldset');
        const legend=group?.querySelector('legend')?.innerText||'';
        return (el.getAttribute('aria-label')||aria.join(' ')||labels.join(' ')||legend||'').trim();
    }""")
def fill_screening(page,profile):
    fields=page.locator('input:visible:not([type=hidden]):not([type=submit]):not([type=button]):not([type=file]):not([type=checkbox]):not([type=radio]), textarea:visible, select:visible')
    filled=0
    for i in range(fields.count()):
        field=fields.nth(i)
        if not field.is_enabled() or field.get_attribute("readonly") is not None: continue
        tag=field.evaluate("el => el.tagName.toLowerCase()")
        if field.input_value().strip() and tag!="select": continue
        question=field_question(field)
        answer=answer_for(question,profile)
        if answer is None: continue
        value=as_text(answer)
        if tag=="select":
            options=field.locator("option").evaluate_all("els => els.map(e => ({label:e.textContent.trim(), value:e.value, disabled:e.disabled}))")
            choices=[o for o in options if not o["disabled"] and o["value"] and normalize(o["label"])==normalize(value)]
            if len(choices)!=1: continue
            field.select_option(value=choices[0]["value"])
        else:
            field.fill(value)
        filled+=1
    return filled
