import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

ROOT=Path(__file__).resolve().parent.parent
FEED=ROOT/"data"/"jobs.json"
OUT=ROOT/"data"/"verification-status.json"
SUPPORTED={"job-boards.greenhouse.io","boards.greenhouse.io","jobs.lever.co","jobs.ashbyhq.com"}
LIMIT=max(1,min(int(os.getenv("VERIFICATION_PROBE_LIMIT","60")),100))
CONCURRENCY=max(1,min(int(os.getenv("VERIFICATION_PROBE_CONCURRENCY","5")),10))
TTL_HOURS=max(1,min(int(os.getenv("VERIFICATION_PROBE_TTL_HOURS","24")),168))

CHALLENGE_TEXT=[
    "verify you are human",
    "verify that you are human",
    "complete the captcha",
    "complete the security check",
    "checking your browser",
    "security verification",
    "i am not a robot",
    "i'm not a robot",
    "human verification",
]

def utcnow():
    return datetime.now(timezone.utc)

def parse_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z","+00:00"))
    except Exception:
        return None

def load_json(path,default):
    try:
        data=json.loads(path.read_text(encoding="utf-8"))
        return data
    except Exception:
        return default

def candidate_url(job):
    url=str(job.get("url") or "").strip()
    try:
        parsed=urlparse(url)
    except Exception:
        return ""
    if parsed.scheme!="https" or (parsed.hostname or "").lower() not in SUPPORTED:
        return ""
    if (parsed.hostname or "").lower()=="jobs.lever.co":
        base=url.split("?")[0].rstrip("/")
        if not base.endswith("/apply"):
            url=base+"/apply"
    return url

async def challenge_present(page):
    selectors=[
        'iframe[src*="captcha" i]',
        'iframe[src*="challenge" i]',
        'iframe[src*="turnstile" i]',
        'iframe[title*="captcha" i]',
        'iframe[title*="challenge" i]',
    ]
    for selector in selectors:
        loc=page.locator(selector)
        for i in range(await loc.count()):
            frame=loc.nth(i)
            try:
                if not await frame.is_visible():
                    continue
                box=await frame.bounding_box()
                if not box or box["width"]<2 or box["height"]<2:
                    continue
                title=(await frame.get_attribute("title") or "").lower()
                src=(await frame.get_attribute("src") or "").lower()
                if "recaptcha" in (title+" "+src) and box["width"]<=100 and box["height"]<=100 and "challenge" not in title and "/bframe" not in src:
                    continue
                return True
            except Exception:
                continue
    try:
        text=(await page.locator("body").inner_text(timeout=3000)).lower()[:120000]
    except Exception:
        text=""
    return any(phrase in text for phrase in CHALLENGE_TEXT)

async def application_form_visible(page):
    selectors=[
        'input[type="email"]',
        'input[type="file"]',
        'button:has-text("Submit Application")',
        'button:has-text("Apply for this job")',
        'form',
    ]
    for selector in selectors:
        loc=page.locator(selector)
        for i in range(min(await loc.count(),5)):
            try:
                if await loc.nth(i).is_visible():
                    return True
            except Exception:
                pass
    return False

async def probe_one(browser,sem,job):
    async with sem:
        url=candidate_url(job)
        result={
            "job_id":str(job.get("id") or ""),
            "url":str(job.get("url") or ""),
            "checked_at_utc":utcnow().isoformat(),
            "status":"unknown",
            "reason":"probe_failed",
        }
        if not url:
            result["reason"]="unsupported_url"
            return result
        context=await browser.new_context(ignore_https_errors=False)
        page=await context.new_page()
        try:
            await page.goto(url,wait_until="domcontentloaded",timeout=18000)
            await page.wait_for_timeout(1500)
            if await challenge_present(page):
                result.update(status="verification_detected",reason="visible_challenge")
                return result
            if await application_form_visible(page):
                result.update(status="no_verification_detected",reason="application_form_visible")
                return result
            result.update(status="unknown",reason="application_form_not_confirmed")
            return result
        except PlaywrightTimeoutError:
            result.update(status="unknown",reason="navigation_timeout")
            return result
        except Exception as exc:
            result.update(status="unknown",reason=type(exc).__name__)
            return result
        finally:
            await context.close()

async def main():
    feed=load_json(FEED,{})
    jobs=[j for j in feed.get("jobs",[]) if j.get("auto_apply_supported") and candidate_url(j)]
    old=load_json(OUT,{"jobs":{}})
    cached=old.get("jobs",{}) if isinstance(old,dict) else {}
    cutoff=utcnow()-timedelta(hours=TTL_HOURS)

    pending=[]
    for job in jobs:
        item=cached.get(str(job.get("id") or ""),{})
        checked=parse_time(item.get("checked_at_utc"))
        if not checked or checked<cutoff:
            pending.append(job)

    pending.sort(key=lambda j:(str(cached.get(str(j.get("id") or ""),{}).get("checked_at_utc") or ""),str(j.get("published") or "")))
    selected=pending[:LIMIT]

    print("Verification probe candidates:",len(jobs),"pending:",len(pending),"selected:",len(selected))
    if selected:
        async with async_playwright() as p:
            browser=await p.chromium.launch(headless=True)
            sem=asyncio.Semaphore(CONCURRENCY)
            results=await asyncio.gather(*(probe_one(browser,sem,job) for job in selected))
            await browser.close()
        for item in results:
            cached[item["job_id"]]=item

    live_ids={str(j.get("id") or "") for j in jobs}
    cached={k:v for k,v in cached.items() if k in live_ids}
    counts={}
    for value in cached.values():
        status=value.get("status","unknown")
        counts[status]=counts.get(status,0)+1
    payload={
        "generated_at_utc":utcnow().isoformat(),
        "note":"Observed status only. Human verification may still appear later or vary by session/IP.",
        "counts":counts,
        "jobs":cached,
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("Verification status counts:",counts)

if __name__=="__main__":
    asyncio.run(main())
