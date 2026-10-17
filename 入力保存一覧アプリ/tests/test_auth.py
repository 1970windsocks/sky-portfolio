import auth
import audit


def test_generate_api_token_is_logged_to_audit_trail():
    """第67課題(脅威モデリング): 資格情報の発行は追跡できる必要がある。
    トークン発行時に監査ログへ記録されることを確認する。"""
    success, message = auth.create_user("tokenuser", "tokenuser@example.com", "pass1234")
    assert success, message

    auth.generate_api_token("tokenuser")

    entries = audit.recent_entries(20)
    assert any(
        e["action"] == "api_token_generated" and e["username"] == "tokenuser" for e in entries
    )


def test_generate_api_token_regeneration_is_logged_each_time():
    success, message = auth.create_user("tokenuser2", "tokenuser2@example.com", "pass1234")
    assert success, message

    auth.generate_api_token("tokenuser2")
    auth.generate_api_token("tokenuser2")

    entries = audit.recent_entries(20)
    count = sum(
        1
        for e in entries
        if e["action"] == "api_token_generated" and e["username"] == "tokenuser2"
    )
    assert count == 2
