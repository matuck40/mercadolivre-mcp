from mercadolivre_mcp.server import Server
from mercadolivre_mcp.tools import TOOLS

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-png-body"
JPEG = b"\xff\xd8\xff\xe0" + b"fake-jpeg-body"
WEBP = b"RIFF\x04\x00\x00\x00WEBPVP8 "
MAX_BYTES = 10 * 1024 * 1024


def run(client, arguments):
    server = Server(TOOLS, lambda: client)
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "ml_upload_picture", "arguments": arguments},
    }
    return server.handle(message)["result"]


def route_upload(fake_ml):
    fake_ml.route(
        "POST",
        "/pictures/items/upload",
        status=201,
        body={"id": "pic-new-1", "max_size": "1200x1200"},
    )


def test_upload_png_sends_multipart_and_returns_id(client, fake_ml, tmp_path):
    route_upload(fake_ml)
    path = tmp_path / "photo.png"
    path.write_bytes(PNG)
    result = run(client, {"file_path": str(path)})
    assert not result.get("isError"), result
    out = result["structuredContent"]
    assert out["picture_id"] == "pic-new-1"
    assert out["max_size"] == "1200x1200"
    assert "ml_update_item" in out["next_step"]
    (req,) = fake_ml.writes()
    assert req.path == "/pictures/items/upload"
    assert req.headers["Content-Type"].startswith("multipart/form-data; boundary=")
    assert b'name="file"; filename="photo.png"' in req.body
    assert b"Content-Type: image/png" in req.body
    assert PNG in req.body


def test_upload_accepts_jpeg_and_webp(client, fake_ml, tmp_path):
    route_upload(fake_ml)
    for name, data, ctype in (("a.bin", JPEG, b"image/jpeg"), ("b.bin", WEBP, b"image/webp")):
        path = tmp_path / name
        path.write_bytes(data)
        assert not run(client, {"file_path": str(path)}).get("isError")
        assert b"Content-Type: " + ctype in fake_ml.writes()[-1].body


def test_upload_refuses_relative_path(client, fake_ml):
    result = run(client, {"file_path": "photo.png"})
    assert result["isError"]
    assert "absolute path" in result["content"][0]["text"]
    assert fake_ml.writes() == []


def test_upload_refuses_non_image(client, fake_ml, tmp_path):
    path = tmp_path / "key.png"
    path.write_bytes(b"-----BEGIN OPENSSH PRIVATE KEY-----\nsecret\n")
    result = run(client, {"file_path": str(path)})
    assert result["isError"]
    assert "BEGIN" not in result["content"][0]["text"]
    assert fake_ml.writes() == []


def test_upload_refuses_riff_that_is_not_webp(client, fake_ml, tmp_path):
    path = tmp_path / "a.webp"
    path.write_bytes(b"RIFF\x04\x00\x00\x00WAVEfmt ")
    assert run(client, {"file_path": str(path)})["isError"]
    assert fake_ml.writes() == []


def test_upload_refuses_directory(client, fake_ml, tmp_path):
    result = run(client, {"file_path": str(tmp_path)})
    assert result["isError"]
    assert fake_ml.writes() == []


def test_upload_refuses_missing_file(client, fake_ml, tmp_path):
    assert run(client, {"file_path": str(tmp_path / "nope.png")})["isError"]
    assert fake_ml.writes() == []


def test_upload_refuses_too_large(client, fake_ml, tmp_path):
    path = tmp_path / "big.png"
    path.write_bytes(PNG + b"\0" * MAX_BYTES)
    result = run(client, {"file_path": str(path)})
    assert result["isError"]
    assert "10 MB" in result["content"][0]["text"]
    assert fake_ml.writes() == []


def test_upload_content_type_from_magic(client, fake_ml, tmp_path):
    route_upload(fake_ml)
    path = tmp_path / "a.jpg"
    path.write_bytes(PNG)
    assert not run(client, {"file_path": str(path)}).get("isError")
    assert b"Content-Type: image/png" in fake_ml.writes()[0].body
