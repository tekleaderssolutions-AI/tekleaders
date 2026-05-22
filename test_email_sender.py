from unittest.mock import patch, MagicMock

from email_sender import send_email


def test_send_email_sets_cc_and_envelope():
    to = "candidate@example.com"
    extra_cc = "interviewer@example.com"
    subject = "Test Subject"
    body = "<p>Hello</p>"

    with patch("smtplib.SMTP") as mock_smtp_cls:
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        result = send_email(
            to_email=to, subject=subject, html_body=body, cc_email=extra_cc
        )

        mock_smtp_cls.assert_called_once()
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once()

        assert mock_server.sendmail.call_count == 1
        from_addr, envelope, raw = mock_server.sendmail.call_args[0]
        assert to in envelope
        assert extra_cc in envelope
        assert "raghavendra.v@tekleaders.com" in envelope
        assert "sajida.baig@tekleaders.com" in envelope
        assert "janaki.vijinigiri@tekleaders.com" in envelope
        assert "Cc:" in raw
        assert result["success"] is True
        assert len(result.get("cc", [])) >= 3
