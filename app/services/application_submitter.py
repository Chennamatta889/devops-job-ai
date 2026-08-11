from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


@dataclass
class SubmissionResult:
    status: str
    message: str
    final_url: str = ""
    submitted: bool = False


CAPTCHA_RE = re.compile(r"captcha|recaptcha|hcaptcha|verify you are human|human verification", re.I)
LOGIN_RE = re.compile(r"sign in|log in|login|create an account", re.I)
SUCCESS_RE = re.compile(r"application submitted|application has been submitted|thank you for applying|thanks for applying|application received|successfully applied", re.I)


def _profile_values(profile):
    parts = (profile.name or "").strip().split()
    first_name = parts[0] if parts else ""
    last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

    email = os.getenv("CANDIDATE_EMAIL", "")
    phone = os.getenv("CANDIDATE_PHONE", "")
    return {
        "first_name": first_name,
        "last_name": last_name,
        "full_name": profile.name or "",
        "email": email,
        "phone": phone,
        "location": profile.preferred_locations or "",
    }


def _make_resume_pdf(text: str) -> Path:
    fd, raw_path = tempfile.mkstemp(prefix="tailored_resume_", suffix=".pdf")
    os.close(fd)
    path = Path(raw_path)

    styles = getSampleStyleSheet()
    story = []
    for block in (text or "").split("\n"):
        line = block.strip()
        if not line:
            story.append(Spacer(1, 8))
        else:
            story.append(Paragraph(line.replace("&", "&amp;"), styles["BodyText"]))
            story.append(Spacer(1, 3))

    SimpleDocTemplate(
        str(path), pagesize=A4, rightMargin=42, leftMargin=42, topMargin=42, bottomMargin=42
    ).build(story)
    return path


def _first_visible(page, selectors):
    for selector in selectors:
        locator = page.locator(selector)
        try:
            if locator.count() and locator.first.is_visible():
                return locator.first
        except Exception:
            continue
    return None


def _fill(locator, value: str):
    if not locator or not value:
        return False
    try:
        locator.fill(value, timeout=2500)
        return True
    except Exception:
        return False


def _fill_common_fields(page, profile):
    values = _profile_values(profile)
    selectors = {
        "first_name": [
            'input[name*="first" i]', 'input[id*="first" i]', 'input[autocomplete="given-name"]',
            'input[placeholder*="first name" i]'
        ],
        "last_name": [
            'input[name*="last" i]', 'input[id*="last" i]', 'input[autocomplete="family-name"]',
            'input[placeholder*="last name" i]'
        ],
        "full_name": [
            'input[name="name" i]', 'input[name*="full_name" i]', 'input[id="name" i]',
            'input[placeholder*="full name" i]', 'input[autocomplete="name"]'
        ],
        "email": ['input[type="email"]', 'input[name*="email" i]', 'input[id*="email" i]'],
        "phone": ['input[type="tel"]', 'input[name*="phone" i]', 'input[id*="phone" i]'],
        "location": ['input[name*="location" i]', 'input[id*="location" i]', 'input[placeholder*="location" i]'],
    }

    filled = 0
    for key, candidates in selectors.items():
        if key in {"first_name", "last_name"} and _first_visible(page, selectors["full_name"]):
            continue
        locator = _first_visible(page, candidates)
        if _fill(locator, values[key]):
            filled += 1
    return filled


def _fill_cover_letter(page, cover_letter: str):
    if not cover_letter:
        return False
    locator = _first_visible(page, [
        'textarea[name*="cover" i]', 'textarea[id*="cover" i]',
        'textarea[placeholder*="cover" i]', 'textarea[name*="message" i]'
    ])
    return _fill(locator, cover_letter)


def _attach_resume(page, pdf_path: Path):
    inputs = page.locator('input[type="file"]')
    for index in range(inputs.count()):
        try:
            item = inputs.nth(index)
            if item.is_visible() or index == 0:
                item.set_input_files(str(pdf_path))
                return True
        except Exception:
            continue
    return False


def _dismiss_overlays(page):
    """Close common popups/modals that can intercept clicks on external job pages."""
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass

    selectors = [
        '[aria-label="Close"]',
        '[aria-label="close"]',
        'button:has-text("Close")',
        '.mfp-close',
        '.modal-close',
        '[data-dismiss="modal"]',
    ]
    for selector in selectors:
        locator = page.locator(selector)
        try:
            count = locator.count()
            for index in range(min(count, 3)):
                item = locator.nth(index)
                if item.is_visible():
                    item.click(timeout=1500, force=True)
                    page.wait_for_timeout(200)
        except Exception:
            continue


def _find_apply_link(page):
    """Find an external/application link before considering generic submit buttons."""
    candidates = [
        'a:has-text("Apply now")',
        'a:has-text("Apply Now")',
        'a:has-text("Apply")',
        'button:has-text("Apply now")',
        'button:has-text("Apply Now")',
        'button:has-text("Apply")',
    ]
    return _first_visible(page, candidates)


def _find_submit_button(page):
    """Find a real application submit control, never the Adzuna search button."""
    candidates = [
        'form button:has-text("Submit application")',
        'form button:has-text("Submit Application")',
        'form button:has-text("Submit")',
        'form input[type="submit"]',
        'button:has-text("Submit application")',
        'button:has-text("Submit Application")',
        'button:has-text("Submit")',
        'input[type="submit"]',
    ]
    for selector in candidates:
        locator = page.locator(selector)
        try:
            count = locator.count()
            for index in range(count):
                item = locator.nth(index)
                if not item.is_visible():
                    continue
                element_id = (item.get_attribute("id") or "").lower()
                name = (item.get_attribute("name") or "").lower()
                if element_id == "search-btn" or "search" in element_id or "search" in name:
                    continue
                return item
        except Exception:
            continue
    return None


def submit_application(application, artifact, profile) -> SubmissionResult:
    """Attempt a permitted browser submission after explicit approval.

    This intentionally does not bypass CAPTCHA, MFA, login walls, bot checks,
    or other access controls. Those cases are returned as MANUAL_ACTION_REQUIRED.
    """
    storage_state = os.getenv("PLAYWRIGHT_STORAGE_STATE", "").strip()
    timeout_ms = int(os.getenv("APPLICATION_BROWSER_TIMEOUT_MS", "15000"))
    headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() != "false"

    resume_pdf = _make_resume_pdf(artifact.tailored_resume or "")

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            context_kwargs = {}
            if storage_state and Path(storage_state).exists():
                context_kwargs["storage_state"] = storage_state
            context = browser.new_context(**context_kwargs)
            page = context.new_page()
            page.set_default_timeout(timeout_ms)

            try:
                page.goto(application.apply_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1500)
            except PlaywrightTimeoutError:
                pass

            # Adzuna can display an inline search/modal overlay on job pages. It can
            # intercept pointer events and also contains a search submit button.
            _dismiss_overlays(page)

            # If the supplied URL is an Adzuna listing, first follow the actual
            # employer/application link. Do not mistake Adzuna's search button for
            # the job application's submit button.
            hostname = (urlparse(page.url).hostname or "").lower()
            if "adzuna." in hostname:
                apply_link = _find_apply_link(page)
                if apply_link:
                    try:
                        apply_link.click(timeout=5000)
                        page.wait_for_timeout(1800)
                    except Exception:
                        try:
                            href = apply_link.get_attribute("href")
                            if href:
                                page.goto(href, wait_until="domcontentloaded", timeout=30000)
                                page.wait_for_timeout(1500)
                        except Exception:
                            pass
                    _dismiss_overlays(page)

            final_url = page.url
            body_text = page.locator("body").inner_text(timeout=5000)

            if CAPTCHA_RE.search(body_text) or CAPTCHA_RE.search(final_url):
                return SubmissionResult("MANUAL_ACTION_REQUIRED", "CAPTCHA/human verification detected.", final_url)
            if LOGIN_RE.search(body_text) and not page.locator('input[type="email"]').count():
                return SubmissionResult("MANUAL_ACTION_REQUIRED", "Login/account creation is required before applying.", final_url)

            _fill_common_fields(page, profile)
            _fill_cover_letter(page, artifact.cover_letter or "")
            _attach_resume(page, resume_pdf)

            submit_button = _find_submit_button(page)
            if not submit_button:
                return SubmissionResult("MANUAL_ACTION_REQUIRED", "No supported application submit button was detected.", final_url)

            submit_button.click(timeout=timeout_ms)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=15000)
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(1500)

            final_url = page.url
            confirmation_text = page.locator("body").inner_text(timeout=5000)
            if CAPTCHA_RE.search(confirmation_text) or CAPTCHA_RE.search(final_url):
                return SubmissionResult("MANUAL_ACTION_REQUIRED", "CAPTCHA/human verification appeared during submission.", final_url)
            if SUCCESS_RE.search(confirmation_text):
                return SubmissionResult("SUBMITTED", "Application submission confirmed by the destination page.", final_url, True)

            return SubmissionResult("SUBMISSION_UNCONFIRMED", "The form was submitted, but no standard confirmation message was detected.", final_url)
    except Exception as exc:
        return SubmissionResult("FAILED", f"Browser submission failed: {type(exc).__name__}: {exc}")
    finally:
        try:
            resume_pdf.unlink(missing_ok=True)
        except Exception:
            pass
