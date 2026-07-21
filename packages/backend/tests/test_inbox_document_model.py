import uuid

from backend.models.inbox_document import InboxDocument


def test_inbox_document_fields():
    doc = InboxDocument(
        id=str(uuid.uuid4()),
        task_id="abc123",
        title="Test",
        participants="user1,user2",
        cc_recipients="",
        attachment_urls="[]",
    )
    assert doc.task_id == "abc123"
    assert doc.fwd == 0
    assert doc.skip == 0
    assert doc.forward_time is None


def test_inbox_document_all_fields():
    doc = InboxDocument(
        id=str(uuid.uuid4()),
        task_id="xyz",
        creator="张三",
        send_time="2026-07-21 08:00",
        title="通知标题",
        participants="李四,王五",
        cc_recipients="赵六",
        summary="内容摘要",
        attachment_urls='[{"filename":"a.pdf","url":"https://..."}]',
        fwd=1,
        skip=0,
        forward_time=None,
    )
    assert doc.creator == "张三"
