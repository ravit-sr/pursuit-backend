from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch()
    for w in (320, 360, 390, 414):
        page = b.new_page(viewport={"width": w, "height": 1000})
        page.goto("http://127.0.0.1:8899/resume.html", wait_until="load")
        page.wait_for_timeout(300)
        page.evaluate("""
            document.querySelector('[data-page-skeleton]').style.display='none';
            document.querySelector('[data-page-content]').style.display='block';
            document.querySelector('.resume-list').innerHTML = `
                <div class="resume-item active-resume">
                    <span class="ri-icon">\U0001F4C4</span>
                    <div class="ri-info">
                        <strong>RavitSrivastava_InternshalaResume.pdf</strong>
                        <span>Uploaded Jul 26, 2026 \u00b7 33 KB</span>
                    </div>
                    <div class="ri-actions">
                        <span class="ri-active-badge">Active</span>
                        <button class="act-btn" data-tooltip="Download">\u2b07</button>
                        <button class="act-btn danger" data-tooltip="Delete">\U0001F5D1</button>
                    </div>
                </div>`;
        """)
        page.wait_for_timeout(150)
        overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        body_overflow = page.evaluate("document.body.scrollWidth - document.body.clientWidth")
        ri = page.query_selector(".resume-item.active-resume")
        badge = page.query_selector(".ri-active-badge")
        print(w, "docEl overflow:", overflow, "body overflow:", body_overflow)
        print(w, "resume-item rect:", ri.bounding_box() if ri else None)
        print(w, "badge rect:", badge.bounding_box() if badge else None)
        page.close()
    b.close()