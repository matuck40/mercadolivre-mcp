import io
import json
import os
import socket
import stat
import subprocess
import sys

import pytest

from mercadolivre_mcp import cli
from mercadolivre_mcp.config import Config

TOKEN = {
    "access_token": "test-access",
    "refresh_token": "test-refresh",
    "expires_in": 21600,
    "user_id": 42,
}


def _state_path(config):
    return config.secrets_dir / "oauth_state"


def _token_requests(fake_ml):
    return [r for r in fake_ml.requests if r.path == "/oauth/token"]


def _save_state(config, value="saved-state"):
    config.secrets_dir.mkdir(parents=True, exist_ok=True)
    _state_path(config).write_text(value)


def _body(request):
    body = request.body
    return body.decode() if isinstance(body, bytes) else str(body)


def test_auth_url_prints_url_and_saves_state(config, capsys):
    assert cli.main(["auth", "url"], config=config) == 0
    out = capsys.readouterr().out
    state = _state_path(config).read_text()
    assert state
    assert f"state={state}" in out
    assert "client_id=test-client" in out
    assert "mercadolivre-mcp auth code" in out
    assert stat.S_IMODE(_state_path(config).stat().st_mode) == 0o600


def test_auth_url_missing_env_exits_2(tmp_path, capsys):
    assert cli.main(["auth", "url"], config=Config(secrets_dir=tmp_path)) == 2
    assert "ML_CLIENT_ID" in capsys.readouterr().err


def test_auth_code_with_bare_code(config, fake_ml, capsys):
    fake_ml.route("POST", "/oauth/token", body=TOKEN)
    _save_state(config)
    assert cli.main(["auth", "code", "TG-abc"], config=config) == 0
    captured = capsys.readouterr()
    assert "Authorized. Token saved to" in captured.out
    assert "(user_id 42)" in captured.out
    assert "not verified" in captured.err
    assert "code=TG-abc" in _body(_token_requests(fake_ml)[0])
    assert (config.secrets_dir / "token.json").exists()
    assert _state_path(config).read_text() == ""


def test_auth_code_with_redirect_url_and_matching_state(config, fake_ml, capsys):
    fake_ml.route("POST", "/oauth/token", body=TOKEN)
    _save_state(config, "s1")
    url = "https://example.test/callback?code=TG-xyz&state=s1"
    assert cli.main(["auth", "code", url], config=config) == 0
    captured = capsys.readouterr()
    assert "not verified" not in captured.err
    assert "code=TG-xyz" in _body(_token_requests(fake_ml)[0])
    assert _state_path(config).read_text() == ""


def test_auth_code_state_mismatch_exits_2(config, fake_ml, capsys):
    _save_state(config, "s1")
    url = "https://example.test/callback?code=TG-xyz&state=other"
    assert cli.main(["auth", "code", url], config=config) == 2
    assert "State mismatch: run `mercadolivre-mcp auth url` again." in capsys.readouterr().err
    assert _token_requests(fake_ml) == []


def test_auth_code_never_prints_token(config, fake_ml, capsys):
    fake_ml.route("POST", "/oauth/token", body=TOKEN)
    _save_state(config)
    cli.main(["auth", "code", "TG-abc"], config=config)
    captured = capsys.readouterr()
    for secret in ("test-access", "test-refresh"):
        assert secret not in captured.out
        assert secret not in captured.err


def test_auth_code_failure_exits_2(config, fake_ml, capsys):
    fake_ml.route("POST", "/oauth/token", status=400, body={"error": "invalid_grant"})
    assert cli.main(["auth", "code", "TG-bad"], config=config) == 2
    assert "invalid_grant" in capsys.readouterr().err


def _closed_port_config(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    return Config(
        secrets_dir=tmp_path / "secrets",
        client_id="test-client",
        client_secret="test-secret",
        redirect_uri="https://example.test/callback",
        api_base=base,
        auth_base=base,
    )


def test_auth_code_network_error_exits_2_without_traceback(tmp_path, capsys):
    config = _closed_port_config(tmp_path)
    assert cli.main(["auth", "code", "TG-code"], config=config) == 2
    err = capsys.readouterr().err
    assert "Network error" in err
    assert "Traceback" not in err


def test_auth_url_needs_no_network(tmp_path, capsys):
    config = _closed_port_config(tmp_path)
    assert cli.main(["auth", "url"], config=config) == 0
    assert "Traceback" not in capsys.readouterr().err


def test_serve_without_env_lists_tools(tmp_path):
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    stdin = io.StringIO("".join(json.dumps(m) + "\n" for m in messages))
    buf = io.StringIO()
    assert cli.main([], config=Config(secrets_dir=tmp_path), stdin=stdin, stdout=buf) == 0
    responses = [json.loads(line) for line in buf.getvalue().splitlines()]
    assert len(responses[-1]["result"]["tools"]) == 10


def test_serve_broken_pipe_ends_quietly(tmp_path):
    class BrokenOut:
        def write(self, _text):
            raise BrokenPipeError

        def flush(self):
            pass

    stdin = io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}) + "\n")
    assert cli.main([], config=Config(secrets_dir=tmp_path), stdin=stdin, stdout=BrokenOut()) == 0


def _spawn(tmp_path):
    env = {"PATH": os.environ.get("PATH", ""), "ML_SECRETS_DIR": str(tmp_path)}
    return subprocess.Popen(  # noqa: S603 - fixed argv, test only
        [sys.executable, "-m", "mercadolivre_mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )


PING = b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n'


def test_real_broken_pipe_exits_0_with_empty_stderr(tmp_path):
    proc = _spawn(tmp_path)
    proc.stdout.close()
    try:
        _, err = proc.communicate(PING * 2, timeout=30)
    finally:
        proc.kill()
    assert proc.returncode == 0
    assert err == b""


def test_non_utf8_stdin_line_does_not_crash(tmp_path):
    proc = _spawn(tmp_path)
    out, err = proc.communicate(b"\xff\xfe not json\n" + PING, timeout=30)
    assert proc.returncode == 0, err
    lines = [json.loads(line) for line in out.decode().splitlines()]
    assert lines[0]["error"]["code"] == -32700
    assert lines[1]["id"] == 1


def test_auth_without_subcommand_is_usage_error():
    with pytest.raises(SystemExit) as exc:
        cli.main(["auth"])
    assert exc.value.code == 2
