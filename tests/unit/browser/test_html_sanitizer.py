from __future__ import annotations

from flight_hunter.browser.html_extractor import sanitize_dom_html_for_fixture


def test_sanitize_dom_html_for_fixture_removes_active_code_and_secret_fields() -> None:
    fake_secret = "sk-" + "proj_123456789012345678901234"
    raw_html = f"""
    <html>
      <head>
        <meta name="csrf-token" content="very-secret">
        <script>window.token = "sk-secret-token-value";</script>
        <style>.hidden {{ display: none; }}</style>
      </head>
      <body onload="steal()">
        <form method="post" action="https://www.tutu.ru/pay?session=secret-session">
          <input type="hidden" name="session_token" value="secret-session-token">
          <a href="https://user:pass@example.com/path?token=secret#frag" onclick="track()">
            Buy ticket
          </a>
          Contact test@example.com bearer {fake_secret}
        </form>
      </body>
    </html>
    """

    sanitized = sanitize_dom_html_for_fixture(raw_html)

    assert "<script" not in sanitized
    assert "<style" not in sanitized
    assert "onload" not in sanitized
    assert "onclick" not in sanitized
    assert "very-secret" not in sanitized
    assert "secret-session" not in sanitized
    assert "secret-session-token" not in sanitized
    assert "user:pass" not in sanitized
    assert "token=secret" not in sanitized
    assert "test@example.com" not in sanitized
    assert fake_secret not in sanitized
    assert 'method="get"' in sanitized
    assert 'action="https://www.tutu.ru/pay"' in sanitized
    assert 'href="https://example.com/path"' in sanitized
    assert "[redacted-email]" in sanitized
    assert "[redacted-secret]" in sanitized
