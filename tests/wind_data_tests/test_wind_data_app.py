import requests
from playwright.sync_api import expect
import pytest
from pytest_check import check
from conftest import highlight


class TestWindDataAppUI:
    def test_to_have_url(self, page):
        expect(page).to_have_url('https://winddataapi.onrender.com/')

    def test_to_have_title(self, page):
        expect(page).to_have_title('Wind Farm Data ExplorerR')

    def test_title_text(self, page):
        locator = page.get_by_role("heading", name="🌬️ Wind Farm Data Explorer")
        highlight(locator)
        assert locator.inner_text() == '🌬️ Wind Farm Data Explorer'
        # expect(locator).to_have_text('️🌬️ Wind Farm Data Explorer')

    def test_query_tab_is_visible(self, page):
        locator = page.get_by_role("button", name="🔍 Query for Data")
        highlight(locator)
        expect(locator).to_be_visible()

    def test_date_from_is_not_editable(self, page):
        locator = page.get_by_role("textbox", name="Date From")
        highlight(locator)
        expect(locator).not_to_be_editable()

    def test_fetch_data(self, page):
        wind_farm_combobox = page.get_by_label("Wind Farm")
        highlight(wind_farm_combobox)
        wind_farm_combobox.select_option("kelmarsh")

        file_type_combobox = page.get_by_label("File Type")
        highlight(file_type_combobox)
        file_type_combobox.select_option("data")

        fetch_data_button = page.get_by_role("button", name="Fetch Data")
        highlight(fetch_data_button)
        fetch_data_button.click()

        rows_result = page.get_by_text("864 rows", exact=True)
        highlight(rows_result)
        expect(rows_result).to_have_text('864 rows')

    @pytest.mark.skip('The test was marked to skip')
    def test_to_skip(self, page):
        pass


class TestWindDataAppAPI:
    def test_get_health(self):
        url = r"https://winddataapi-backend.onrender.com/health"

        response = requests.get(url)

        check.equal(response.status_code, 200, 'Response status code is not 200')
        check.is_true(response.ok, 'Response is not "ok"')

    def test_get_wind_farms(self):
        url = r"https://winddataapi-backend.onrender.com/wind-farms"

        response = requests.get(url)

        check.equal(response.status_code, 200, 'Response status code is not 200')
        check.is_true(response.ok, 'Response is not "ok"')
        check.equal(response.text, '{"wind_farms":[{"name":"Kelmarsh","directory":"kelmarsh","turbine_count":6,"turbines":["turbine_1","turbine_2","turbine_3","turbine_4","turbine_5","turbine_6"]},{"name":"Penmanshiel","directory":"penmanshiel","turbine_count":15,"turbines":["turbine_1","turbine_10","turbine_11","turbine_12","turbine_13","turbine_14","turbine_15","turbine_2","turbine_3","turbine_4","turbine_5","turbine_6","turbine_7","turbine_8","turbine_9"]}]}', 'Response text is not expected')

    def test_get_wind_farms_response_time(self):
        url = r"https://winddataapi-backend.onrender.com/wind-farms"

        response = requests.get(url)
        response_time_seconds = response.elapsed.microseconds / 1_000_000
        threshold_seconds = 0.5
        check.is_true(response_time_seconds < threshold_seconds, f'Response time {response_time_seconds} seconds is greater than {threshold_seconds} seconds')
