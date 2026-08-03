import unittest

from app.cloudflare import CloudflareError, require_resource_id
from app.node_naming import HostnameValidationError, collision_hostname, validate_managed_hostname
from app.node_provisioning import tunnel_configuration_is_empty


class NodeNamingTests(unittest.TestCase):
    def test_managed_hostname_accepts_one_safe_label(self) -> None:
        self.assertEqual(
            validate_managed_hostname("ismail-mac.gettingstarted.app", "gettingstarted.app"),
            "ismail-mac.gettingstarted.app",
        )

    def test_managed_hostname_rejects_urls_and_nested_labels(self) -> None:
        for value in (
            "https://node.gettingstarted.app",
            "nested.node.gettingstarted.app",
            "node.gettingstarted.app:443",
            "*.gettingstarted.app",
        ):
            with self.subTest(value=value), self.assertRaises(HostnameValidationError):
                validate_managed_hostname(value, "gettingstarted.app")

    def test_collision_hostname_stays_within_dns_label_limit(self) -> None:
        preferred = f"{'a' * 63}.gettingstarted.app"
        result = collision_hostname(preferred, "gettingstarted.app", "abcdef")
        self.assertLessEqual(len(result.split(".", 1)[0]), 63)
        self.assertTrue(result.endswith("-abcdef.gettingstarted.app"))


class CloudflareBoundaryTests(unittest.TestCase):
    def test_resource_ids_cannot_escape_api_paths(self) -> None:
        for value in ("../dns_records", "id/connection", "", "id?query=true"):
            with self.subTest(value=value), self.assertRaises(CloudflareError):
                require_resource_id(value, "resource")

    def test_only_empty_catch_all_tunnel_is_adoptable(self) -> None:
        self.assertTrue(tunnel_configuration_is_empty({"ingress": []}))
        self.assertTrue(
            tunnel_configuration_is_empty({"ingress": [{"service": "http_status:404"}]})
        )
        self.assertFalse(
            tunnel_configuration_is_empty(
                {
                    "ingress": [
                        {"hostname": "existing.example.com", "service": "http://localhost:8080"},
                        {"service": "http_status:404"},
                    ]
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
