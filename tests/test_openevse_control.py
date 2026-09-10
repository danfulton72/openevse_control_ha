"""End-to-end tests against the fake charger."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError

from custom_components.openevse_control.const import DOMAIN

SELECT = "select.openevse_7f3a_charge_mode"
RATE = "number.openevse_7f3a_charge_rate"
BTN_ON = "button.openevse_7f3a_enable_charge"
BTN_AUTO = "button.openevse_7f3a_auto_charge"
BTN_OFF = "button.openevse_7f3a_disable_charge"


async def _setup(hass: HomeAssistant, url: str, **extra) -> MockConfigEntry:
    options = extra.pop("options", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="mac-aabbcc7f3a12",
        title="openevse-7f3a",
        data={"url": url, "verify_ssl": True, **extra},
        options=options,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _press(hass, entity_id):
    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)


async def _rate(hass, amps):
    await hass.services.async_call(
        "number", "set_value", {"entity_id": RATE, "value": amps}, blocking=True
    )


async def _mode(hass, option):
    await hass.services.async_call(
        "select", "select_option", {"entity_id": SELECT, "option": option}, blocking=True
    )


# ---------------------------------------------------------------- config flow


async def test_user_flow_bare_host_defaults_to_http(hass, evse):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"url": evse.url.removeprefix("http://") + "/", "verify_ssl": True},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "openevse-7f3a"
    assert result["data"] == {"url": evse.url, "verify_ssl": True}
    assert result["result"].unique_id == "mac-aabbcc7f3a12"


@pytest.mark.parametrize(
    ("url", "field", "error"),
    [
        ("ftp://1.2.3.4", "url", "invalid_url"),
        ("http://127.0.0.1:1", "base", "cannot_connect"),
    ],
)
async def test_user_flow_errors(hass, url, field, error):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": url, "verify_ssl": True}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {field: error}


async def test_user_flow_not_openevse(hass, evse):
    evse.junk = True
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": evse.url, "verify_ssl": True}
    )
    assert result["errors"] == {"base": "not_openevse"}


async def test_user_flow_auth(hass, evse_auth):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"url": evse_auth.url, "verify_ssl": True, "username": "admin", "password": "nope"},
    )
    assert result["errors"] == {"base": "invalid_auth"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"url": evse_auth.url, "verify_ssl": True, "username": "admin", "password": "s3cret"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["username"] == "admin"
    assert result["data"]["password"] == "s3cret"


async def test_https_verify_on_rejects_self_signed_verify_off_accepts(hass, evse_https):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": evse_https.url, "verify_ssl": True}
    )
    assert result["errors"] == {"base": "ssl_error"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": evse_https.url, "verify_ssl": False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"url": evse_https.url, "verify_ssl": False}
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).state == "auto"


async def test_reconfigure_changes_url(hass, evse):
    entry = await _setup(hass, "http://10.9.9.9")  # wrong address -> fails setup
    assert entry.state is ConfigEntryState.SETUP_RETRY
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": evse.url, "verify_ssl": False}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {"url": evse.url, "verify_ssl": False}
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def test_bad_password_starts_reauth(hass, evse_auth):
    entry = await _setup(hass, evse_auth.url, username="admin", password="old")
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]
    result = await hass.config_entries.flow.async_configure(
        flows[0]["flow_id"], {"username": "admin", "password": "s3cret"}
    )
    assert result["reason"] == "reauth_successful"
    assert entry.data["password"] == "s3cret"
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


# ------------------------------------------------ entities mirror the web page


async def test_initial_state(hass, evse):
    await _setup(hass, evse.url)
    sel = hass.states.get(SELECT)
    assert sel.state == "auto"
    assert sel.attributes["options"] == ["enable", "auto", "disable"]
    rate = hass.states.get(RATE)
    assert rate.state == "12"
    assert (rate.attributes["min"], rate.attributes["max"]) == (6, 12)
    assert rate.attributes["unit_of_measurement"] == "A"
    for button in (BTN_ON, BTN_AUTO, BTN_OFF):
        assert hass.states.get(button) is not None


async def test_buttons_send_what_the_web_ui_sends(hass, evse):
    await _setup(hass, evse.url)

    await _press(hass, BTN_ON)
    assert evse.writes()[-1] == ("POST", {"state": "active", "charge_current": 12})
    assert hass.states.get(SELECT).state == "enable"
    assert hass.states.get(SELECT).attributes["controlled_by"] == "manual"

    await _press(hass, BTN_OFF)
    assert evse.writes()[-1] == ("POST", {"state": "disabled", "charge_current": 12})
    assert hass.states.get(SELECT).state == "disable"

    await _press(hass, BTN_AUTO)
    assert evse.writes()[-1] == ("DELETE", None)
    assert hass.states.get(SELECT).state == "auto"

    # AUTO with nothing to release sends nothing
    n = len(evse.writes())
    await _press(hass, BTN_AUTO)
    assert len(evse.writes()) == n


async def test_select_entity(hass, evse):
    await _setup(hass, evse.url)
    await _mode(hass, "disable")
    assert evse.manual["state"] == "disabled"
    assert hass.states.get(SELECT).state == "disable"
    await _mode(hass, "auto")
    assert evse.manual is None


async def test_charge_rate_in_auto(hass, evse):
    await _setup(hass, evse.url)

    await _rate(hass, 8)
    assert evse.writes()[-1] == ("POST", {"charge_current": 8, "auto_release": True})
    assert hass.states.get(RATE).state == "8"
    assert hass.states.get(SELECT).state == "auto"  # rate alone doesn't change mode

    # v5.1.5 removes charge_current but preserves auto_release=true.
    await _rate(hass, 12)
    assert evse.writes()[-1] == ("POST", {"auto_release": True})
    assert hass.states.get(RATE).state == "12"


async def test_charge_rate_keeps_enable_and_enable_keeps_rate(hass, evse):
    await _setup(hass, evse.url)
    await _press(hass, BTN_ON)
    await _rate(hass, 9)
    assert evse.writes()[-1] == (
        "POST",
        {"state": "active", "charge_current": 9, "auto_release": True},
    )
    assert hass.states.get(SELECT).state == "enable"
    # Disable keeps the 9 A the user chose (web UI does the same)
    await _press(hass, BTN_OFF)
    assert evse.writes()[-1] == ("POST", {"state": "disabled", "charge_current": 9})


async def test_auto_release_option(hass, evse):
    await _setup(hass, evse.url, options={"scan_interval": 30, "auto_release": False})
    await _rate(hass, 7)
    assert evse.writes()[-1] == ("POST", {"charge_current": 7, "auto_release": False})


async def test_picks_up_changes_made_in_web_ui(hass, evse):
    entry = await _setup(hass, evse.url)
    evse.manual = {"state": "disabled", "charge_current": 10, "auto_release": False}
    evse.bump()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).state == "disable"
    assert hass.states.get(RATE).state == "10"


async def test_polling_is_cheap_when_nothing_changes(hass, evse):
    entry = await _setup(hass, evse.url)
    evse.log.clear()
    await entry.runtime_data.async_refresh()
    assert [p for _, p, _ in evse.log] == ["/status"]


# ------------------------------------------ same locks as the web page's UI


async def test_rate_locked_in_eco(hass, evse):
    entry = await _setup(hass, evse.url)
    evse.status["divertmode"] = 2
    await entry.runtime_data.async_refresh()
    with pytest.raises(ServiceValidationError, match="Eco"):
        await _rate(hass, 8)


async def test_rate_locked_by_higher_priority_claim(hass, evse):
    entry = await _setup(hass, evse.url)
    evse.other_claims = [{"client": 65548, "priority": 5000, "charge_current": 6}]
    evse.bump()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(RATE).attributes["controlled_by"] == "shaper"
    with pytest.raises(ServiceValidationError, match="shaper"):
        await _rate(hass, 8)


async def test_rate_allowed_over_lower_priority_claim(hass, evse):
    entry = await _setup(hass, evse.url)
    evse.other_claims = [{"client": 65540, "priority": 100, "charge_current": 6}]
    evse.bump()
    await entry.runtime_data.async_refresh()
    await _rate(hass, 10)
    assert evse.manual["charge_current"] == 10


async def test_mode_locked_by_limit(hass, evse):
    entry = await _setup(hass, evse.url)
    evse.other_claims = [{"client": 65542, "priority": 1100, "state": "disabled"}]
    evse.bump()
    await entry.runtime_data.async_refresh()
    with pytest.raises(ServiceValidationError, match="limit"):
        await _press(hass, BTN_ON)


async def test_unload(hass, evse):
    entry = await _setup(hass, evse.url)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


# ------------------------------------------------ exact v5.1.5 compatibility


async def test_v4_config_flow_is_supported(hass, evse_v4):
    """V4-era WiFi firmware is accepted when its JSON RAPI bridge works."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": evse_v4.url, "verify_ssl": True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "openevse-7f3a"
    assert result["result"].unique_id == "mac-aabbcc7f3a12"


async def test_v4_entities_and_current_range(hass, evse_v4):
    """V4 exposes only meaningful modes and obtains current limits from $GC."""
    await _setup(hass, evse_v4.url)

    select = hass.states.get(SELECT)
    assert select.state == "enable"
    assert select.attributes["options"] == ["enable", "disable"]
    assert hass.states.get(BTN_ON) is not None
    assert hass.states.get(BTN_OFF) is not None
    assert hass.states.get(BTN_AUTO) is None

    rate = hass.states.get(RATE)
    assert rate.state == "12"
    assert (rate.attributes["min"], rate.attributes["max"]) == (6, 32)
    assert "$GC" in evse_v4.rapi_log


async def test_v4_commands_match_web_ui(hass, evse_v4):
    """V4 control uses the same RAPI commands as the firmware web UI."""
    await _setup(hass, evse_v4.url)
    evse_v4.rapi_log.clear()

    await _press(hass, BTN_OFF)
    assert evse_v4.rapi_writes()[-1] == "$FS"
    assert hass.states.get(SELECT).state == "disable"

    await _press(hass, BTN_ON)
    assert evse_v4.rapi_writes()[-1] == "$FE"
    assert hass.states.get(SELECT).state == "enable"

    await _rate(hass, 16)
    assert evse_v4.rapi_writes()[-1] == "$SC 16"
    assert hass.states.get(RATE).state == "16"


async def test_v4_pause_can_use_hard_disable(hass, evse_v4):
    """Respect V4's pause_uses_disabled configuration option."""
    evse_v4.config["pause_uses_disabled"] = True
    await _setup(hass, evse_v4.url)
    evse_v4.rapi_log.clear()

    await _press(hass, BTN_OFF)
    assert evse_v4.rapi_writes()[-1] == "$FD"


async def test_v4_steady_poll_is_status_only(hass, evse_v4):
    """Legacy capability and current-range discovery are cached."""
    entry = await _setup(hass, evse_v4.url)
    evse_v4.log.clear()
    evse_v4.rapi_log.clear()

    await entry.runtime_data.async_refresh()
    assert [path for _, path, _ in evse_v4.log] == ["/status"]
    assert evse_v4.rapi_log == []


async def test_auto_release_false_clears_current_only_override_at_max(hass, evse):
    """Mirror the special v5.1.5 GUI branch for auto_release=false."""
    await _setup(hass, evse.url, options={"auto_release": False})
    await _rate(hass, 8)
    assert evse.manual == {"charge_current": 8, "auto_release": False}
    await _rate(hass, 12)
    assert evse.writes()[-1] == ("DELETE", None)
    assert evse.manual is None


async def test_rfid_state_lock_uses_status_authentication(hass, evse):
    """RFID-owned state is locked until /status reports an authenticated tag."""
    entry = await _setup(hass, evse.url)
    evse.other_claims = [{"client": 65546, "priority": 1030, "state": "disabled"}]
    evse.bump()
    await entry.runtime_data.async_refresh()
    with pytest.raises(ServiceValidationError, match="rfid"):
        await _press(hass, BTN_ON)

    evse.status["rfid_auth"] = "test-tag"
    await entry.runtime_data.async_refresh()
    await _press(hass, BTN_ON)
    assert evse.writes()[-1][0] == "POST"


async def test_config_version_refreshes_current_limit(hass, evse):
    """Changes made in the charger UI are picked up using config_version."""
    entry = await _setup(hass, evse.url)
    evse.config["max_current_soft"] = 16
    evse.status["max_current"] = 16
    evse.bump_config()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(RATE).attributes["max"] == 16


async def test_command_error_is_reported(hass, evse):
    """Unexpected firmware failures become Home Assistant action errors."""
    from homeassistant.exceptions import HomeAssistantError

    await _setup(hass, evse.url)
    await _press(hass, BTN_ON)
    evse.override_delete_failure = "unexpected failure"
    with pytest.raises(HomeAssistantError, match="OpenEVSE"):
        await _press(hass, BTN_AUTO)
