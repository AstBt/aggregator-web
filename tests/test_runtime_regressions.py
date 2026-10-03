import base64
import io
import os
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "subscribe"))

import clash
import httpclient
import pipeline
import process
import push
import subconverter
import utils
import workflow
from config.models import CrawlConfig, CrawlPersist, NodeInput, ProcessConfig, ProxyConfig, SiteConfig, StorageConfig, StorageItem, TaskParams, TelegramChannelConfig, TelegramConfig
from crawl import engine
from crawl.channels import telegram
from crawl.extract import extract_subscribes
from crawl.helpers import check_status, is_expired
from crawl.models import ChannelResult, CrawlContext


class Response(io.BytesIO):
    def __init__(self, body=b"ok", status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}

    def getcode(self):
        return self.status

    def getheader(self, name):
        return self.headers.get(name.lower())


class HttpRoutingTests(unittest.TestCase):
    def test_loopback_bypasses_all_proxy_settings(self):
        for url in ("http://127.0.0.1:9090/version", "http://localhost:9090/version", "http://[::1]:9090/version"):
            with self.subTest(url=url), patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1"}, clear=True):
                with patch("httpclient._opener") as factory:
                    factory.return_value.open.return_value = Response()
                    httpclient.open_url(url, proxy="http://127.0.0.1:2")
                    self.assertEqual(factory.call_args.args[0], "")

    def test_proxy_transport_failure_retries_direct_with_fresh_request(self):
        preferred, direct = MagicMock(), MagicMock()
        preferred.open.side_effect = urllib.error.URLError("proxy disconnected")
        direct.open.return_value = Response()
        request = urllib.request.Request("https://example.com/data", data=b"body", method="PATCH")
        with patch("httpclient._opener", side_effect=[preferred, direct]) as factory:
            httpclient.open_url(request, proxy="http://127.0.0.1:7897")
        self.assertEqual([c.args[0] for c in factory.call_args_list], ["http://127.0.0.1:7897", ""])
        first, second = preferred.open.call_args.args[0], direct.open.call_args.args[0]
        self.assertIsNot(first, second)
        self.assertEqual(second.data, b"body")
        self.assertEqual(second.get_method(), "PATCH")

    def test_proxy_gateway_error_falls_back_but_token_404_does_not(self):
        for status, calls in ((502, 2), (403, 2), (404, 1), (422, 1)):
            with self.subTest(status=status):
                preferred = MagicMock()
                preferred.open.side_effect = urllib.error.HTTPError("https://example.com/", status, "error", {}, io.BytesIO())
                direct = MagicMock()
                with patch("httpclient._opener", side_effect=[preferred, direct]) as factory:
                    if calls == 1:
                        with self.assertRaises(urllib.error.HTTPError):
                            httpclient.open_url("https://example.com/", proxy="http://127.0.0.1:7897")
                    else:
                        httpclient.open_url("https://example.com/", proxy="http://127.0.0.1:7897")
                    self.assertEqual(factory.call_count, calls)

    def test_probe_accepts_empty_204_and_sets_bypass(self):
        with patch.dict(os.environ, {"NO_PROXY": "intranet.local"}, clear=True):
            with patch("httpclient.open_url", return_value=Response(b"", 204)):
                address = httpclient.configure_proxy(True, "http://127.0.0.1:7897", "https://example.com/204")
            self.assertEqual(address, "http://127.0.0.1:7897")
            self.assertEqual(os.environ["https_proxy"], address)
            self.assertIn("intranet.local", os.environ["NO_PROXY"])
            self.assertIn("127.0.0.1", os.environ["no_proxy"])

    def test_probe_403_does_not_disable_working_proxy(self):
        error = urllib.error.HTTPError("https://api.github.com/zen", 403, "Forbidden", {}, io.BytesIO())
        with patch.dict(os.environ, {}, clear=True), patch("httpclient.open_url", side_effect=error):
            self.assertEqual(httpclient.configure_proxy(True, "http://127.0.0.1:7897", "https://api.github.com/zen"), "http://127.0.0.1:7897")

    def test_probe_transport_failure_clears_upper_and_lowercase_proxies(self):
        with patch.dict(os.environ, {key: "http://old-proxy:1" for key in httpclient._PROXY_ENV}, clear=True):
            with patch("httpclient.open_url", side_effect=urllib.error.URLError("offline")):
                self.assertEqual(httpclient.configure_proxy(True, "http://127.0.0.1:7897", "https://example.com/"), "")
            self.assertFalse(any(os.environ.get(key) for key in httpclient._PROXY_ENV))

    def test_config_roundtrip_preserves_proxy(self):
        config = ProcessConfig.parse({"crawl": {"proxy": {"enable": True, "address": "http://127.0.0.1:7897"}}})
        restored = ProcessConfig.parse(config.to_dict())
        self.assertEqual(restored.crawl.proxy, config.crawl.proxy)

    def test_http_get_retry_does_not_duplicate_query(self):
        with patch("httpclient.open_url", side_effect=[urllib.error.URLError("offline"), Response()]) as opener:
            self.assertEqual(utils.http_get("https://example.com/path", params={"page": 2}, retry=2), "ok")
        self.assertEqual([call.args[0].full_url for call in opener.call_args_list], ["https://example.com/path?page=2"] * 2)


class SubscriptionValidationTests(unittest.TestCase):
    def test_proxy_keyword_and_layer_one_thresholds(self):
        content = base64.b64encode(b"trojan://password@example.com:443#node")
        headers = {"subscription-userinfo": f"total={10 * 1024 ** 3}; upload=0; download=0"}
        with patch("httpclient.open_url", return_value=Response(content, headers=headers)) as opener:
            self.assertEqual(check_status("https://example.com/sub", retry=1, remain=5, proxy="http://127.0.0.1:7897"), (True, False))
            self.assertEqual(opener.call_args.kwargs["proxy"], "http://127.0.0.1:7897")
        with patch("httpclient.open_url", return_value=Response(content, headers={"subscription-userinfo": "total=1"})):
            self.assertEqual(check_status("https://example.com/sub", retry=1, remain=5), (False, False))

    def test_transport_failure_is_not_expiration(self):
        with patch("httpclient.open_url", side_effect=urllib.error.URLError("offline")):
            self.assertEqual(check_status("https://example.com/sub", retry=1), (False, False))

    def test_header_values_are_data_not_executable_code(self):
        with patch("builtins.eval", side_effect=AssertionError("must not evaluate network data")):
            self.assertEqual(is_expired("total=10737418240; upload=0; download=0", remain=5), (True, False))
            is_expired("total=__import__('os').system('false')")


class TelegramExtractionTests(unittest.TestCase):
    def test_uri_case_and_html_query_parameters_survive(self):
        link = "trojan://SeCrEt@server.example.com:443?security=tls&sni=Example.COM&type=grpc&serviceName=MyService#Node"
        result = extract_subscribes(f'<a href="{link.replace("&", "&amp;")}">node</a>', include_nodes=True)
        self.assertEqual(result.nodes.uris, [link])

    def test_real_pagination_and_homepage_reuse(self):
        config = TelegramChannelConfig(push_to=["free"])
        first = "trojan://AbC@server.example.com:443#First <a href='/s/channel?before=93'>Older</a>"
        second = "trojan://DeF@server.example.com:443#Second <a href='/s/channel?before=93'>Older</a>"
        with patch("utils.http_get", side_effect=[first, second]) as get:
            result = telegram._crawl_channel("channel", config, 5, True)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[0].kwargs["url"], "https://t.me/s/channel")
        self.assertEqual(get.call_args_list[1].kwargs["url"], "https://t.me/s/channel?before=93")
        self.assertEqual(len(result.nodes.uris), 2)

    def test_channel_fetch_is_not_blocked_by_tme_homepage_probe(self):
        config = TelegramConfig(channels={"channel": TelegramChannelConfig(push_to=["free"])})
        ctx = CrawlContext(0, True, 5, "", TaskParams(), None, None, display=False)
        with patch("utils.http_get", return_value="trojan://Secret@server.example.com:443#Node") as get:
            result = telegram.TelegramChannel().crawl(config, ctx)
        self.assertEqual(len(result.nodes.uris), 1)
        self.assertTrue(all("/s/channel" in call.kwargs["url"] for call in get.call_args_list))


class ControllerTests(unittest.TestCase):
    def test_delay_check_is_direct_and_uses_only_configured_target(self):
        with patch("httpclient.open_url", return_value=Response(b'{"delay":0}')) as opener:
            self.assertTrue(clash.check({"name": "node"}, "127.0.0.1:9090", 12000, "https://example.com/204", 5000))
        self.assertEqual(opener.call_count, 1)
        self.assertTrue(opener.call_args.kwargs["direct"])
        self.assertEqual(opener.call_args.kwargs["timeout"], 14)
        self.assertNotIn("youtube", opener.call_args.args[0].full_url)

    def test_node_timeout_is_dead_but_bad_controller_is_infrastructure_error(self):
        for code in (503, 502):
            exc = urllib.error.HTTPError("http://127.0.0.1/delay", code, "error", {}, io.BytesIO())
            with self.subTest(code=code), patch("httpclient.open_url", side_effect=exc):
                if code == 503:
                    self.assertFalse(clash.check({"name": "node"}, "127.0.0.1:9090", 5000, "https://example.com/204", 5000))
                else:
                    with self.assertRaises(clash.ControllerError):
                        clash.check({"name": "node"}, "127.0.0.1:9090", 5000, "https://example.com/204", 5000)

    def test_controller_connection_failure_is_not_node_death(self):
        with patch("httpclient.open_url", side_effect=urllib.error.URLError("controller offline")):
            with self.assertRaises(clash.ControllerError):
                clash.check({"name": "node"}, "127.0.0.1:9090", 5000, "https://example.com/204", 5000)

    def test_wait_detects_core_exit(self):
        process = MagicMock(returncode=1)
        process.poll.return_value = 1
        with self.assertRaises(clash.ControllerError):
            pipeline._wait_for_controller(process, "127.0.0.1:9090")

    def test_duplicate_nodes_preserve_all_subscription_sources(self):
        nodes = [
            {"name": name, "server": "server.example.com", "port": 443, "type": "trojan", "password": "Secret", "sub": url}
            for name, url in (("A", "https://one.example.com/sub"), ("B", "https://two.example.com/sub"))
        ]
        result = clash.filter_proxies(nodes)["proxies"]
        self.assertEqual(len(result), 1)
        self.assertEqual(set(clash.subscription_sources(result[0])), {"https://one.example.com/sub", "https://two.example.com/sub"})

    def test_check_config_does_not_bind_user_proxy_port(self):
        import tempfile
        import yaml
        with tempfile.TemporaryDirectory() as directory:
            clash.generate_config(directory, [], "probe.yaml", controller="127.0.0.1:12345")
            config = yaml.safe_load((Path(directory) / "probe.yaml").read_text(encoding="utf8"))
        self.assertEqual(config["external-controller"], "127.0.0.1:12345")
        self.assertNotIn("mixed-port", config)


class PublicationTests(unittest.TestCase):
    def config(self):
        item = StorageItem(username="test", gist_id="id", filename="pool.json")
        return ProcessConfig(
            storage=StorageConfig(engine="gist", items={"pool": item}),
            crawl=CrawlConfig(persist=CrawlPersist(subscribe="pool")),
            sites=[
                SiteConfig(name="one", nodes=NodeInput(subscribe="https://one.example.com/sub"), push_to=["free"]),
                SiteConfig(name="two", nodes=NodeInput(subscribe="https://two.example.com/sub"), push_to=["free"]),
            ],
        )

    def test_pool_is_built_in_memory_and_written_once_without_cdn_read(self):
        backend = push.PushToGist("dummy")
        with patch.object(backend, "push_to", return_value=True) as publish, patch("utils.http_get", side_effect=AssertionError("no read-back")):
            workflow.filter_pool(self.config(), backend, {"https://one.example.com/sub"})
        import json
        payload = json.loads(publish.call_args.kwargs["content"])
        self.assertEqual(set(payload), {"https://one.example.com/sub"})
        self.assertEqual(publish.call_count, 1)
        self.assertEqual(payload["https://one.example.com/sub"]["errors"], 0)

    def test_refresh_cannot_overwrite_pool(self):
        backend = push.PushToGist("dummy")
        with patch.object(backend, "push_to") as publish, patch("utils.http_get", side_effect=AssertionError("no CDN read")):
            workflow.refresh(self.config(), backend, {"https://one.example.com/sub": False})
        publish.assert_not_called()

    def test_empty_verified_pool_is_explicit_json_not_blank(self):
        backend = push.PushToGist("dummy")
        with patch.object(backend, "push_to", return_value=True) as publish:
            workflow.filter_pool(self.config(), backend, set())
        self.assertEqual(publish.call_args.kwargs["content"], "{}")

    def test_backend_rejects_empty_conversion_without_request(self):
        backend = push.PushToGist("dummy")
        with patch("httpclient.open_url") as request:
            self.assertFalse(backend.push_to("", StorageItem(gist_id="id", filename="mixed.txt")))
            self.assertFalse(backend.push_to(" \n", StorageItem(gist_id="id", filename="mixed.txt")))
        request.assert_not_called()

    def test_crawl_does_not_publish_unverified_candidates(self):
        backend = push.PushToGist("dummy")
        with patch.object(backend, "push_to") as publish, patch("push.get_instance", return_value=backend), patch("crawl.engine.load_records", return_value={}), patch("utils.multi_thread_run", return_value=[(True, False)]):
            result = ChannelResult()
            result.add_subscribe("https://one.example.com/sub", "GIST", TaskParams(push_to=["free"]))
            fake_channel = MagicMock()
            fake_channel.crawl.return_value = result
            config = CrawlConfig(gist=MagicMock(enable=True), persist=CrawlPersist(subscribe="pool"))
            with patch.dict(engine.CHANNELS, {"gist": fake_channel}):
                sites = engine.run(config, self.config().storage, display=False)
        self.assertEqual(len(sites), 1)
        publish.assert_not_called()

    def test_scattered_nodes_keep_target_groups_through_engine(self):
        result = extract_subscribes("trojan://Secret@server.example.com:443#node", push_to=["free"], include_nodes=True)
        channel = MagicMock()
        channel.crawl.return_value = result
        with patch.dict(engine.CHANNELS, {"telegram": channel}):
            sites = engine.run(CrawlConfig(telegram=MagicMock(enable=True)), storage=None, display=False)
        self.assertEqual(sites[0].push_to, ["free"])
        self.assertEqual(sites[0].nodes.uris, result.nodes.uris)

    def test_subconverter_runs_from_its_own_directory(self):
        with patch("utils.chmod"), patch("utils.cmd", return_value=(True, "")) as command:
            self.assertTrue(subconverter.convert("subconverter-windows-amd.exe", "unit"))
        self.assertEqual(command.call_args.kwargs["cwd"], subconverter.getpath())


if __name__ == "__main__":
    unittest.main()
