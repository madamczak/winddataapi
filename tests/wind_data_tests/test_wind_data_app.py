from playwright.sync_api import expect
import pytest


class TestWindDataAppGeneral:
    def test_to_have_url(self, page):
        expect(page).to_have_url('https://winddataapi.onrender.com/')

    def test_to_have_title(self, page):
        expect(page).to_have_title('Wind Farm Data ExplorerR')

    @pytest.mark.skip('The test was marked to skip')
    def test_to_skip(self, page):
        pass
