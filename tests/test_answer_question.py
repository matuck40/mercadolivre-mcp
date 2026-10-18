from mercadolivre_mcp.server import Server
from mercadolivre_mcp.tools import TOOLS

QUESTION = {
    "id": 123,
    "text": "Does it come in blue?",
    "status": "UNANSWERED",
    "answer": None,
}
NOTICE = (
    "Nothing was sent. Show this preview to the user and call again "
    "with confirm=true only after they approve it."
)


def run(client, arguments):
    server = Server(TOOLS, lambda: client)
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "ml_answer_question", "arguments": arguments},
    }
    return server.handle(message)["result"]


def route_question(fake_ml, question=QUESTION):
    fake_ml.route("GET", "/questions/123", body=question)
    fake_ml.route("POST", "/answers", body={"id": 123, "status": "ANSWERED"})


def test_answer_preview_makes_no_write_request(client, fake_ml):
    route_question(fake_ml)
    result = run(client, {"question_id": 123, "text": "Yes, in blue."})
    assert not result.get("isError"), result
    out = result["structuredContent"]
    assert fake_ml.writes() == []
    assert out["preview"] is True
    assert out["request"] == {
        "method": "POST",
        "path": "/answers",
        "body": {"question_id": 123, "text": "Yes, in blue."},
    }
    assert out["notice"] == NOTICE


def test_answer_preview_shows_question(client, fake_ml):
    route_question(fake_ml, {**QUESTION, "answer": {"text": "Old answer"}})
    out = run(client, {"question_id": 123, "text": "New answer"})["structuredContent"]
    assert out["question_id"] == 123
    assert out["before"] == {
        "question": "Does it come in blue?",
        "status": "UNANSWERED",
        "existing_answer": "Old answer",
    }
    assert out["after"] == {"answer": "New answer"}


def test_answer_preview_without_existing_answer(client, fake_ml):
    route_question(fake_ml)
    out = run(client, {"question_id": 123, "text": "Yes"})["structuredContent"]
    assert out["before"]["existing_answer"] is None


def test_answer_confirm_posts_same_body_as_preview(client, fake_ml):
    route_question(fake_ml)
    args = {"question_id": 123, "text": "Yes, in blue."}
    preview = run(client, args)["structuredContent"]
    out = run(client, {**args, "confirm": True})["structuredContent"]
    (req,) = fake_ml.writes()
    assert req.method == "POST"
    assert req.path == preview["request"]["path"]
    assert req.json == preview["request"]["body"]
    assert out["preview"] is False
    assert out["request"] == preview["request"]
    assert out["result"] == {"id": 123, "status": "ANSWERED"}


def test_answer_text_too_long_is_is_error(client, fake_ml):
    route_question(fake_ml)
    result = run(client, {"question_id": 123, "text": "x" * 2001, "confirm": True})
    assert result["isError"] is True
    assert fake_ml.requests == []


def test_answer_empty_text_is_is_error(client, fake_ml):
    route_question(fake_ml)
    result = run(client, {"question_id": 123, "text": "", "confirm": True})
    assert result["isError"] is True
    assert fake_ml.requests == []


def test_answer_whitespace_text_is_is_error(client, fake_ml):
    route_question(fake_ml)
    result = run(client, {"question_id": 123, "text": "   \n ", "confirm": True})
    assert result["isError"] is True
    assert fake_ml.requests == []


def test_answer_question_id_must_be_integer(client, fake_ml):
    route_question(fake_ml)
    for bad in ("123", 1.5, 0, True):
        result = run(client, {"question_id": bad, "text": "Yes"})
        assert result["isError"] is True, bad
    assert fake_ml.requests == []


def test_answer_post_error_is_is_error(client, fake_ml):
    fake_ml.route("GET", "/questions/123", body=QUESTION)
    fake_ml.route("POST", "/answers", status=400, body={"message": "already answered"})
    result = run(client, {"question_id": 123, "text": "Yes", "confirm": True})
    assert result["isError"] is True
    assert "already answered" in result["content"][0]["text"]


def test_tool_order_and_description():
    names = list(TOOLS)
    assert names.index("ml_upload_picture") < names.index("ml_answer_question")
    tool = TOOLS["ml_answer_question"]
    assert "confirm=true" in tool.description
    assert "public" in tool.description
    assert tool.annotations == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    }
