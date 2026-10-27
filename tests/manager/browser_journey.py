"""Run against browser_server.py, with an installed Playwright Chromium browser."""

import re
import sys
import time

from playwright.sync_api import expect, sync_playwright


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
        page.goto(f"http://127.0.0.1:{port}/#token=browser-fixture-token-at-least-32-characters")
        page.wait_for_load_state("networkidle")
        expect(page).to_have_title("ACED · Cycle manager")
        expect(page.get_by_role("heading", name="Cycles & experiments")).to_be_visible()
        assert "token=" not in page.url
        page.get_by_role("button", name="Make the first successful action easier").click()
        expect(page.get_by_role("heading", name="Working hypothesis")).to_be_visible()
        page.get_by_role("button", name="Hold scheduling").click()
        page.get_by_role("button", name="Confirm hold").click()
        expect(page.get_by_text("Scheduling is held.", exact=False)).to_be_visible()
        page.get_by_role("button", name="Resume scheduling").click()
        expect(page.get_by_role("button", name="Hold scheduling")).to_be_visible()
        page.get_by_role("tab", name="Approvals", exact=True).click()
        deadline = time.monotonic() + 100
        saw_chart = False
        while time.monotonic() < deadline:
            if page.get_by_role("button", name="Continue with new goal").count():
                break
            approve = page.get_by_role("button", name="Approve task")
            # Returning from the metrics tab remounts the inbox. Wait for its
            # request to render before deciding whether an approval is available.
            expect(
                approve.or_(
                    page.get_by_text("No approval requests for the current task.", exact=True)
                ).first
            ).to_be_visible()
            if approve.count() and approve.is_enabled():
                approve.click()
            page.wait_for_timeout(1000)
            # Observe the experiment separately from approving the next task.
            if not saw_chart and page.locator(".stages .current").inner_text().lower().endswith(
                "experiment"
            ):
                page.get_by_role("tab", name="Experiment", exact=True).click()
                with page.expect_response(lambda response: "/api/experiments/" in response.url):
                    page.get_by_role("button", name="Refresh metrics").click()
                if page.get_by_role("heading", name="Activation (%)").count():
                    page.screenshot(path="/tmp/aced-manager-desktop.png", full_page=True)
                    saw_chart = True
                page.get_by_role("tab", name="Approvals", exact=True).click()
        else:
            raise AssertionError(page.locator("main").inner_text())
        page.get_by_role("tab", name="Experiment", exact=True).click()
        page.get_by_label("Phase").select_option("main")
        expect(page.get_by_role("heading", name="Activation (%)")).to_be_visible()
        expect(page.locator(".recharts-surface").first).to_be_visible()
        page.screenshot(path="/tmp/aced-manager-desktop.png", full_page=True)
        page.get_by_role("tab", name="Cycle history", exact=True).click()
        expect(
            page.get_by_text("Fixture learning with explicit uncertainty", exact=True)
        ).to_be_visible()
        # A lost browser connection does not relaunch tasks or lose the session.
        page.reload()
        page.wait_for_load_state("networkidle")
        page.get_by_role("button", name="Make the first successful action easier").click()
        page.get_by_role("button", name="Continue with new goal").click()
        page.get_by_label("Measurable goal").fill("Continue learning from activation")
        page.get_by_label("Fixture learning with explicit uncertainty").check()
        page.get_by_role("button", name="Start run", exact=True).click()
        expect(
            page.get_by_role("heading", name="Continue learning from activation")
        ).to_be_visible()
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path="/tmp/aced-manager-mobile.png", full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.get_by_role("button", name="Request stop", exact=True).click()
        page.get_by_role("button", name="Confirm stop").click()
        expect(page.locator(".page-heading .badge")).to_have_text(re.compile("stopping|stopped"))
        assert not errors, errors
        browser.close()
        print(
            "Browser journey passed: approvals, charts, hold/resume, "
            "continuation, reconnect, stop, mobile."
        )


if __name__ == "__main__":
    main()
