import socket
import unittest
from unittest.mock import patch

from app.fetch_url import _PublicRedirectHandler, _validate_public_url, direct_url


class UrlImportBoundary(unittest.TestCase):
    def test_loopback_and_private_literals_are_rejected(self):
        for url in (
            "http://127.0.0.1/document.pdf",
            "http://10.1.2.3/document.pdf",
            "http://169.254.169.254/latest/meta-data/",
            "http://[::1]/document.pdf",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                _validate_public_url(url)

    def test_hostname_resolving_to_private_space_is_rejected(self):
        resolved = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.10", 443))
        ]
        with patch("app.fetch_url.socket.getaddrinfo", return_value=resolved):
            with self.assertRaises(ValueError):
                _validate_public_url("https://files.example/document.pdf")

    def test_public_hostname_is_accepted(self):
        resolved = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ]
        with patch("app.fetch_url.socket.getaddrinfo", return_value=resolved):
            self.assertEqual(
                _validate_public_url("https://files.example/document.pdf"),
                "https://files.example/document.pdf",
            )

    def test_credentials_and_nonstandard_ports_are_rejected(self):
        for url in (
            "https://user:secret@files.example/document.pdf",
            "https://files.example:8443/document.pdf",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                _validate_public_url(url)

    def test_redirects_are_revalidated(self):
        handler = _PublicRedirectHandler()
        with self.assertRaises(ValueError):
            handler.redirect_request(
                None, None, 302, "Found", {}, "http://127.0.0.1/private"
            )

    def test_known_share_link_is_rewritten_without_changing_file_identity(self):
        url = "https://github.com/example/repo/blob/main/agreement.pdf"
        self.assertEqual(
            direct_url(url),
            "https://raw.githubusercontent.com/example/repo/main/agreement.pdf",
        )


if __name__ == "__main__":
    unittest.main()
