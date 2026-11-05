"""External links open in a new, opener-free tab; internal routes and downloads stay in place."""
import pytest

from test_reader_controls import _write_reader_report, reader_browser  # noqa: F401


@pytest.mark.parametrize("width", [1500, 390])
def test_native_external_link_policy_covers_dynamic_and_download_links(tmp_path, reader_browser, width):
    from playwright.sync_api import expect

    def external_reference(spec):
        spec["properties"]["subject"]["obsHtml"]["reference"]["linkProperty"] = "item.url"
        subject = tmp_path / "subject.md"
        subject.write_text(subject.read_text(encoding="utf-8").replace(
            "  id: S-1\n", "  id: S-1\n  url: https://example.invalid/table-subject\n"),
            encoding="utf-8")

    output = _write_reader_report(tmp_path, external_reference)
    page = reader_browser.new_page(viewport={"width": width, "height": 1000})
    try:
        page.goto(output.as_uri())
        page.evaluate("obsPages.setPaged(true); obsReport.activateChapter('chapter')")
        page.evaluate("""() => {
            const host=document.createElement('p');
            host.innerHTML='<a href="https://example.invalid/prose">External prose</a> '+
                '<a href="//example.invalid/protocol-relative">Protocol-relative web page</a> '+
                '<a href="#chapter">Internal route</a> '+
                '<a href="https://example.invalid/source" data-source-download>Source download</a> '+
                '<a href="https://example.invalid/original" download>Download file</a>';
            document.querySelector('[data-active-chapter] .paper-content').append(host);
        }""")
        external = page.get_by_role("link", name="External prose", exact=True)
        expect(external).to_have_attribute("target", "_blank")
        expect(external).to_have_attribute("rel", "noopener noreferrer")
        expect(page.get_by_role("link", name="Protocol-relative web page")).to_have_attribute("target", "_blank")
        expect(page.get_by_role("link", name="Protocol-relative web page")).to_have_attribute(
            "rel", "noopener noreferrer")
        assert page.get_by_role("link", name="Internal route").get_attribute("target") is None
        assert page.get_by_role("link", name="Download file").get_attribute("target") is None
        assert page.get_by_role("link", name="Source download").get_attribute("target") is None
        page.context.route("https://example.invalid/**", lambda route: route.fulfill(
            status=200, content_type="text/html", body="<title>External test destination</title>"))
        original_url = page.url
        with page.expect_popup() as popup:
            external.click()
        popup.value.wait_for_load_state()
        assert popup.value.evaluate("window.opener") is None
        assert page.url == original_url
        popup.value.close()
        page.evaluate("obsReport.activateChapter('chapter')")
        table = page.locator("[data-active-chapter] [data-data-table='chapter-base-1']")
        table_source = table.locator("td a[href='https://example.invalid/table-subject']").first
        with page.expect_popup(timeout=5000) as table_popup:
            table_source.click()
        table_popup.value.wait_for_load_state()
        assert table_popup.value.evaluate("window.opener") is None
        assert page.url == original_url
        table_popup.value.close()
        assert table.locator("[data-detail-owner]").count() == 0
        table.locator(".data-table-tree-toggle").first.click()
        source = table.locator("[data-detail-owner] a[href='https://example.org/subject']").first
        expect(source).to_have_attribute("target", "_blank")
        expect(source).to_have_attribute("rel", "noopener noreferrer")
    finally:
        page.close()
