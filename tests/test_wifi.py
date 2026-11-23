"""WiFi setup: nmcli parsing, joining, and the setup page."""
from __future__ import annotations

import json
import subprocess
import threading
import time
import urllib.request
from unittest.mock import MagicMock, patch

from spotifactory import wifi


class TestParseScan:
    def test_strongest_first_one_per_ssid_hidden_and_ours_left_out(self):
        out = "\n".join([
            "Home:WPA2:40",
            "Home:WPA2:70",
            ":WPA2:90",                      # hidden
            "Spotifactory::99",              # our own hotspot
            "Cafe::55",
            r"Joe\:s Net:WPA1 WPA2:30",      # escaped colon
            "Office:WPA2 802.1X:20",
            "New:WPA3:60",
            "Mixed:WPA2 WPA3:50",
        ])
        nets = wifi.parse_scan(out)
        assert [n.ssid for n in nets] == ["Home", "New", "Cafe", "Mixed", "Joe:s Net", "Office"]
        sec = {n.ssid: n.security for n in nets}
        assert sec == {"Home": "wpa", "New": "wpa3", "Cafe": "none", "Mixed": "wpa",
                       "Joe:s Net": "wpa", "Office": "enterprise"}

    def test_qr_payload(self):
        assert wifi.wifi_qr_payload() == "WIFI:T:nopass;S:Spotifactory;;"


def _cp(rc=0, out="", err=""):
    return subprocess.CompletedProcess([], rc, out, err)


class TestJoin:
    def test_wrong_password_deletes_only_the_new_profile(self):
        calls = []

        def nmcli(*args, **kw):
            calls.append(args)
            return ""

        with patch("spotifactory.wifi._nmcli", side_effect=nmcli), \
             patch("subprocess.run", return_value=_cp(4, err="Error: Connection activation failed: Secrets were required, but not provided")):
            try:
                wifi.join("Home", "nope", security="wpa")
                raise AssertionError("should fail")
            except wifi.JoinError as e:
                assert str(e) == "Wrong password?"
        added = next(a for a in calls if a[:2] == ("con", "add"))
        new_name = added[added.index("con-name") + 1]
        deletes = [a[2] for a in calls if a[:2] == ("con", "delete")]
        assert deletes == [new_name]

    def test_success_removes_older_profiles_for_that_network(self):
        calls = []

        def nmcli(*args, **kw):
            calls.append(args)
            if args[:2] == ("-t", "-f"):
                return "old-home:802-11-wireless\nother:802-11-wireless\nspotifactory-setup:802-11-wireless\n"
            if args[:1] == ("-g",):
                return "Home\n" if args[-1] == "old-home" else "Elsewhere\n"
            return ""

        with patch("spotifactory.wifi._nmcli", side_effect=nmcli), \
             patch("subprocess.run", return_value=_cp(0)), \
             patch("spotifactory.wifi.wait_for_internet", return_value=True):
            wifi.join("Home", "secret", security="wpa3")
        added = next(a for a in calls if a[:2] == ("con", "add"))
        assert "sae" in added
        deletes = [a[2] for a in calls if a[:2] == ("con", "delete")]
        assert deletes == ["old-home"]

    def test_not_found_after_rescans(self):
        with patch("spotifactory.wifi.scan", return_value=[]), patch("time.sleep"):
            try:
                wifi.join("Gone", "x")
                raise AssertionError("should fail")
            except wifi.JoinError as e:
                assert str(e) == "Network not found"

    def test_scan_until_found_retries(self):
        seen = [[], [], [wifi.Network("Home", "wpa", 50)]]
        with patch("spotifactory.wifi.scan", side_effect=seen), patch("time.sleep"):
            assert wifi.scan_until_found("Home").ssid == "Home"


class TestSetupStep:
    def _start(self, step):
        from spotifactory.tasks.base import TaskContext
        with patch("spotifactory.tasks.wifi_setup.steps._PORTS", (0,)):
            server = step._serve()
        return server, f"http://127.0.0.1:{server.server_address[1]}"

    def test_page_lists_networks_and_queues_connect(self):
        from spotifactory.tasks.wifi_setup.steps import WifiSetupStep
        step = WifiSetupStep()
        step.networks = [wifi.Network("Home", "wpa3", 70), wifi.Network("Cafe", "none", 40)]
        step.last_error = "Couldn't join Home (Wrong password?)"
        server, base = self._start(step)
        try:
            nets = json.load(urllib.request.urlopen(base + "/networks"))
            assert nets == [{"ssid": "Home", "security": "wpa"}, {"ssid": "Cafe", "security": "none"}]
            assert json.load(urllib.request.urlopen(base + "/status"))["error"].startswith("Couldn't join")
            req = urllib.request.Request(base + "/connect", method="POST",
                                         data=json.dumps({"ssid": "Home", "identity": "", "passphrase": "pw"}).encode(),
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req).read()
            assert step._requests.get(timeout=1) == ("Home", "pw", "")
            page = urllib.request.urlopen(base + "/").read()
            assert b"Choose your WiFi" in page
        finally:
            server.shutdown()
            server.server_close()

    def test_other_hosts_redirect_to_the_page(self):
        import http.client
        from spotifactory.tasks.wifi_setup.steps import WifiSetupStep
        step = WifiSetupStep()
        server, base = self._start(step)
        try:
            conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
            conn.request("GET", "/hotspot-detect.html", headers={"Host": "captive.apple.com"})
            r = conn.getresponse()
            assert r.status == 302 and r.getheader("Location") == step.session_url
        finally:
            server.shutdown()
            server.server_close()

    def test_cancel_stops_the_hotspot(self):
        from spotifactory.tasks.base import Cancel, TaskContext
        from spotifactory.tasks.wifi_setup.steps import WifiSetupStep
        step = WifiSetupStep()
        with patch("spotifactory.wifi.scan", return_value=[]), \
             patch("spotifactory.wifi.start_hotspot") as up, \
             patch("spotifactory.wifi.stop_hotspot") as down, \
             patch("spotifactory.wifi.try_saved_networks", return_value=False), \
             patch("spotifactory.tasks.wifi_setup.steps._PORTS", (0,)), \
             patch("spotifactory.tasks.wifi_setup.steps.time.sleep"):
            step.start(TaskContext(dry_run=False))
            wait = threading.Event()
            for _ in range(200):
                if step.qr_image is not None:
                    break
                wait.wait(0.02)
            assert step.qr_image is not None
            step.cancel()
            for _ in range(200):
                if step.is_done:
                    break
                wait.wait(0.05)
        assert isinstance(step.outcome, Cancel)
        up.assert_called_once()
        down.assert_called()
