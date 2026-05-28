from __future__ import annotations

import atexit
import base64
import getpass
import json
import logging
import os
import queue
import re
import threading
import time
import uuid
from datetime import datetime

import pytest
import requests
from playwright.sync_api import sync_playwright
from pytest_check import check
from pytest_metadata.plugin import metadata_key

# Grafana Loki configuration
# Credentials - set these environment variables
LOKI_INSTANCE_ID = os.environ.get("GRAFANA_LOKI_INSTANCE_ID", "1380423")
TOKEN = os.environ.get("GRAFANA_TOKEN",
                       "glc_eyJvIjoiMTU3NTg3MCIsIm4iOiJzdGFjay0xNDIyNjI5LWludGVncmF0aW9uLXRlc3R0b2tlbiIsImsiOiIxUVJKQzROdExFMmMwOTlxQjg3a3hHMjciLCJtIjp7InIiOiJwcm9kLWV1LW5vcnRoLTAifX0=")

# Push endpoints — copy from your Grafana Cloud stack details page
LOKI_URL = os.environ.get("GRAFANA_LOKI_URL",
                          "https://logs-prod-025.grafana.net/loki/api/v1/push")
ENV = os.environ.get("ENVIRONMENT", "test")

APP_NAME = "wind_data_tests"

LOKI_ENABLED = bool(LOKI_INSTANCE_ID and TOKEN)

SESSION_ID = str(uuid.uuid4().hex[:8])
START_TIME = time.time()

# Basic auth header for Grafana Cloud
_loki_b64 = base64.b64encode(f"{LOKI_INSTANCE_ID}:{TOKEN}".encode()).decode()

# ── Loki log handler (queue-based, reliable delivery) ─────────────────────────
_log_queue: queue.Queue = queue.Queue()


def _loki_worker():
    """Background thread: drain the queue and push batches to Loki."""
    headers = {
        "Authorization": f"Basic {_loki_b64}",
        "Content-Type": "application/json",
    }
    while True:
        item = _log_queue.get()
        if item is None:  # sentinel → shut down
            _log_queue.task_done()
            break
        try:
            response = requests.post(LOKI_URL, data=json.dumps(item),
                                     headers=headers, timeout=10)
            if response.status_code != 204:
                print(f"Loki push failed: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"Loki push error: {e}")
        _log_queue.task_done()


_worker_thread = threading.Thread(target=_loki_worker, daemon=True)
_worker_thread.start()


def _flush_loki():
    """Block until every queued log has been pushed to Loki."""
    _log_queue.join()


atexit.register(_flush_loki)


class _LokiHandler(logging.Handler):
    """Enqueues log records; the background worker pushes them to Loki."""

    def emit(self, record: logging.LogRecord):
        if not LOKI_ENABLED:
            return
        try:
            payload = {
                "streams": [{
                    "stream": {
                        "app": APP_NAME,
                        "level": record.levelname.lower(),
                        "env": ENV,
                    },
                    "values": [[str(int(record.created * 1e9)), self.format(record)]],
                }]
            }
            _log_queue.put(payload)
        except Exception as e:
            print(f"Loki emit error: {e}")


# Add Grafana handler to root logger
grafana_handler = _LokiHandler()
grafana_handler.setFormatter(logging.Formatter("%(message)s"))
logging.root.addHandler(grafana_handler)


# def pytest_runtest_setup(item):
#     parts = [item.module.__name__]
#     if getattr(item, 'cls', None) is not None:
#         parts.append(item.cls.__name__)
#     parts.append(item.name)
#     logging.info(f'TEST Start: {"::".join(parts)}')
#
#
# def pytest_runtest_teardown(item):
#     parts = [item.module.__name__]
#     if getattr(item, 'cls', None) is not None:
#         parts.append(item.cls.__name__)
#     parts.append(item.name)
#     logging.info(f'TEST Finish: {"::".join(parts)}')


def pytest_runtest_logreport(report):
    """Log test results (pass/fail/skip) to Grafana."""

    parts = [report.nodeid]
    status = report.outcome

    if report.when == 'call':
        if status == 'passed':
            logging.info(f'TEST PASSED ({int(report.duration)}s) [{SESSION_ID}]: {"::".join(parts)}')
        elif status == 'failed':
            logging.error(
                f'TEST FAILED ({int(report.duration)}s) [{SESSION_ID}]: {"::".join(parts)}: {report.longreprtext}')
    elif report.when == 'setup' and report.outcome == 'skipped':
        logging.warning(
            f'TEST SKIPPED ({int(report.duration)}s) [{SESSION_ID}]: {"::".join(parts)}: {report.longreprtext}')


def pytest_addoption(parser):
    parser.addoption("--url", action="store", default="https://winddataapi.onrender.com/", help="Base URL for tests")


def pytest_configure(config):
    config.stash[metadata_key]['Datetime'] = str(datetime.strftime(datetime.now(), '%Y-%m-%d %H:%M:%S'))
    config.stash[metadata_key]['Designer'] = 'Tester'
    config.stash[metadata_key]['Test type'] = 'Automated'
    config.stash[metadata_key]['Tester'] = getpass.getuser()
    config.stash[metadata_key]['Environment'] = 'DEV'
    config.stash[metadata_key]['URL'] = config.getoption("--url")
    config.stash[metadata_key]['SESION_ID'] = SESSION_ID


@pytest.fixture(scope="module")
def browser(request):
    browser_name = request.config.getoption("--browser")[0]
    headed = request.config.getoption("--headed")
    slow_mo = request.config.getoption("--slowmo")
    with sync_playwright() as p:
        browser = getattr(p, browser_name).launch(headless=not (headed), slow_mo=slow_mo, args=["--start-maximized"],
                                                  downloads_path='.')
        request.config.stash[metadata_key]["browser"] = f'{browser.browser_type.name} {browser.version}'
        request.config.stash[metadata_key]["browser headed"] = headed
        request.config.stash[metadata_key]["browser slow motion"] = slow_mo
        request.config.stash[metadata_key]["browser slow motion"] = slow_mo
        yield browser
        browser.close()


@pytest.fixture(scope="module")
def page(browser, request):
    url = request.config.getoption("--url")
    context = browser.new_context(no_viewport=True)
    page = context.new_page()
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page.goto(url)
    yield page
    context.tracing.stop(path="trace.zip")
    context.close()


def get_locator_attributes(locator, get_checked, get_editable, get_value, get_expanded):
    exist = True if locator.count() > 0 else False
    if exist:
        highlight(locator, color='yellow')
        visible = locator.is_visible()
        enabled = locator.is_enabled()
        text = locator.inner_text()
        value = None
        if get_value:
            value = locator.input_value()
        checked = None
        editable = None
        if get_checked:
            checked = locator.is_checked()
        if get_editable:
            editable = locator.is_editable()
        expanded = None
        if get_expanded:
            expanded_ = locator.get_attribute("aria-expanded")
            if expanded_ == 'true':
                expanded = True
            elif expanded_ == 'false':
                expanded = False
            else:
                expanded = None
        return {'exist': exist, 'visible': visible, 'enabled': enabled, 'text': text, 'value': value,
                'expanded': expanded,
                'checked': checked,
                'editable': editable
                }
    else:
        return {'exist': exist, 'visible': None, 'enabled': None, 'text': None, 'value': None, 'expanded': None,
                'checked': None,
                'editable': None
                }


def check_locator_attributes(locator, exist=True, visible=True, enabled=True, text=None, value=None, text_re=None,
                             checked=None, editable=None, expanded=None):
    get_checked = False
    get_editable = False
    get_value = False
    get_expanded = False
    if checked is not None:
        get_checked = True
    if editable is not None:
        get_editable = True
    if value is not None:
        get_value = True
    if expanded is not None:
        get_expanded = True
    attribs = get_locator_attributes(locator, get_checked=get_checked, get_editable=get_editable, get_value=get_value,
                                     get_expanded=get_expanded)
    overall_check_statuses = []
    if attribs['exist']:
        highlight(locator, color='orange')
        exist_msg = f'Locator: {locator} does not exist' if exist else f'Locator: {locator} exists'
        visible_msg = f'Locator: {locator} is not visible' if visible else f'Locator {locator} is visible'
        enabled_msg = f'Locator {locator} is not enabled' if enabled else f'Locator {locator} is enabled'
        checked_msg = f'Locator {locator} is not checked' if checked else f'Locator {locator} is checked'
        expanded_msg = f'Locator {locator} is not expanded' if expanded else f'Locator {locator} is expanded'
        editable_msg = f'Locator {locator} is not editable' if editable else f'Locator {locator} is editable'

        overall_check_statuses.append(check.equal(attribs['exist'], exist, exist_msg))
        overall_check_statuses.append(
            check.equal(attribs['visible'], visible, visible_msg))
        overall_check_statuses.append(check.equal(attribs['enabled'], enabled, enabled_msg))

        if checked is not None:
            overall_check_statuses.append(
                check.equal(attribs['checked'], checked, checked_msg))
        if expanded is not None:
            overall_check_statuses.append(
                check.equal(attribs['expanded'], expanded, expanded_msg))
        if editable is not None:
            overall_check_statuses.append(
                check.equal(attribs['editable'], editable, editable_msg))

        if text is not None:
            overall_check_statuses.append(
                check.equal(attribs['text'], text, f'Locator: {locator} text does not match expected'))
        if value is not None:
            overall_check_statuses.append(
                check.equal(attribs['value'], value, f'Locator: {locator} value does not match expected'))
        if text_re is not None:
            overall_check_statuses.append(
                check.is_true(bool(re.search(text_re, attribs['text'])),
                              f"Locator: {locator} text: {attribs['text']} does not match regex '{text_re}'"))

        if not all(overall_check_statuses):
            highlight(locator, color='red')
        else:
            highlight(locator, color='lightgreen')

    else:
        check.equal(attribs['exist'], exist, f'Locator: {locator} exist')


def highlight(locator, thickness=3, style='solid', color='orange'):
    locator.evaluate(
        f"element => {{element.style.outline = '{str(thickness)}px {style} {color}';element.style.outlineOffset = '1px'}}")


def pytest_sessionfinish(session, exitstatus):
    """Log the overall test session results."""

    duration = time.time() - START_TIME

    terminal_reporter = session.config.pluginmanager.get_plugin("terminalreporter")

    passed = len(terminal_reporter.stats.get("passed", []))
    failed = len(terminal_reporter.stats.get("failed", []))
    skipped = len(terminal_reporter.stats.get("skipped", []))

    total = passed + failed + skipped
    pass_rate = (passed / total * 100) if total else 0.0

    overall_status = "PASSED" if failed == 0 else "FAILED"

    session_log = f"SESSION {overall_status} ({int(duration)}s): session_id={SESSION_ID} duration_s={int(duration)} passed={passed} failed={failed} skipped={skipped} total={total} pass_rate_perc={round(pass_rate, 2)}"

    if overall_status == "PASSED":
        logging.info(session_log)
    elif overall_status == "FAILED":
        logging.error(session_log)
