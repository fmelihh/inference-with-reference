import pytest

from app.storage import decode_upload


def test_decode_upload_normalizes_crlf():
    assert decode_upload("a.md", b"one\r\ntwo\r\n") == "one\ntwo\n"


@pytest.mark.parametrize(
    "name,data",
    [("a.pdf", b"x"), ("a.txt", b"\xff\xfe\x00"), ("a.txt", b"x" * (1_048_576 + 1))],
)
def test_decode_upload_rejects(name, data):
    with pytest.raises(ValueError):
        decode_upload(name, data)
