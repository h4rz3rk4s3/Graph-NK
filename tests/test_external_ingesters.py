"""
Tests for the v0.8 curated-dataset ingesters (pure parsers + dry-run plumbing).

These cover the format readers and normalization with synthetic tmp files and
the shared engine's dry-run path. DISCLAIMER: they do NOT contact Mongo/Redis/
Neo4j — the DRY-RUN path of run_external_ingest performs no writes. Real
ingestion is the user's job (validation first, then a real run).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from miner.external_common import (
    make_record_id,
    namespaced_login,
    run_external_ingest,
)
from miner.gitter_ingester import iter_gittercom_records, iter_livechat_records
from miner.numfocus_ingester import _event_issue_or_pr
from miner.openment_ingester import _attach_comments, _load_issues, _load_project_map

# ── external_common ───────────────────────────────────────────────────────────


def test_make_record_id_namespaced():
    assert (
        make_record_id("jira_issue", "Apache Jira", "HBASE-1234")
        == "jira_issue:apache-jira:HBASE-1234"
    )
    assert (
        make_record_id("chat_message", "disco", "Clojurians", "clojure", "2020")
        == "chat_message:disco:Clojurians:clojure:2020"
    )


def test_namespaced_login():
    assert namespaced_login("slack", "preethac-slack", "Melvin") == "slack:preethac-slack:Melvin"
    # collision-safe across corpora
    assert namespaced_login("slack", "other", "Melvin") != namespaced_login(
        "slack", "preethac-slack", "Melvin"
    )


@pytest.mark.asyncio
async def test_run_external_ingest_dry_run_sync_iterator():
    docs = [{"record_id": f"r{i}", "text": f"t{i}"} for i in range(3)]

    def event_for(doc, mid):
        return {"item_type": "chat_message", "mongo_id": mid}

    kept = await run_external_ingest(
        docs=iter(docs),
        collection="x",
        key_field="record_id",
        event_for=event_for,
        dry_run=True,
    )
    assert kept == 3


@pytest.mark.asyncio
async def test_run_external_ingest_dry_run_async_iterator():
    async def gen():
        for i in range(3):
            yield {"record_id": f"a{i}", "text": "t"}

    kept = await run_external_ingest(
        docs=gen(),
        collection="x",
        key_field="record_id",
        event_for=lambda d, m: {"mongo_id": m},
        dry_run=True,
    )
    assert kept == 3


@pytest.mark.asyncio
async def test_run_external_ingest_dry_run_honours_max_and_filter():
    docs = [{"record_id": f"r{i}", "text": "t", "keep": i % 2 == 0} for i in range(6)]
    kept = await run_external_ingest(
        docs=iter(docs),
        collection="x",
        key_field="record_id",
        event_for=lambda d, m: {},
        dry_run=True,
        max_records=2,
        filter_fn=lambda d: d["keep"],
    )
    assert kept == 2


# ── gitter ────────────────────────────────────────────────────────────────────


def test_gittercom_parses_by_position(tmp_path: Path):
    p = tmp_path / "airbnb.csv"
    # header is misleadingly "message,time,user,message"; read by position.
    p.write_text('message,time,user,message\nmsg1,2015-12-09T22:29:01Z,gilligan,":)"\n')
    docs = list(iter_gittercom_records(str(p)))
    assert len(docs) == 1
    assert docs[0]["record_id"].startswith("chat_message:gittercom:airbnb:")
    assert docs[0]["text"] == ":)"
    assert docs[0]["author_login"] == "gitter:gittercom:gilligan"
    assert docs[0]["channel"] == "airbnb"


def test_livechat_parses_timestamped_lines(tmp_path: Path):
    p = tmp_path / "angular_angular_chatFormat.ascii.txt"
    p.write_text(
        "[2016-01-01 00:13:35] <crystalbyte> Happy new year\n"
        "[2016-01-01 02:20:22] <brandom> Can two services depend on each other\n"
        "? continuation line (skipped)\n"
    )
    docs = list(iter_livechat_records(str(p)))
    assert len(docs) == 2
    assert docs[0]["text"] == "Happy new year"
    assert docs[0]["channel"] == "angular_angular_chatFormat"
    assert docs[1]["sequence"] == 2


# ── numfocus ──────────────────────────────────────────────────────────────────


def test_numfocus_event_issue_or_pr():
    ev = {"action": "OpenIssue", "details": {"issue": {"number": 5, "title": "A real title"}}}
    assert _event_issue_or_pr(ev) == ("issue", ev["details"]["issue"])

    ev2 = {"action": "PushCommits", "details": {"push": {"commits": 1}}}
    assert _event_issue_or_pr(ev2) is None  # no text


# ── openment ──────────────────────────────────────────────────────────────────


def test_openment_groups_comments_under_issue(tmp_path: Path):
    issues_csv = tmp_path / "issues_pull_requests.csv"
    issues_csv.write_text(
        "issue_pr_id,author_id,type,title,body,status,creation_day,close_day\n"
        '"ABC","u1","issue","Ti","Bo","open","1","2"\n'
    )
    project_map_path = tmp_path / "project_issue_pr_map.csv"
    project_map_path.write_text("project_id,issue_pr_id\nP1,ABC\n")
    comments_csv = tmp_path / "comments.csv"
    comments_csv.write_text(
        "comment_id,issue_pr_id_x,author_id_x,text_x,creation_day_x\n"
        '"c1","ABC","u2","a comment",3\n'
    )
    issues = _load_issues(str(issues_csv))
    _attach_comments(issues, str(comments_csv))
    assert len(issues["ABC"]["comments_data"]) == 1
    assert issues["ABC"]["comments_data"][0]["body"] == "a comment"


def test_openment_project_map(tmp_path: Path):
    p = tmp_path / "project_issue_pr_map.csv"
    p.write_text("project_id,issue_pr_id\nP1,ABC\nP2,DEF\n")
    assert _load_project_map(str(p)) == {"ABC": "P1", "DEF": "P2"}


def test_openment_project_roles(tmp_path: Path):
    from miner.openment_ingester import _load_project_roles

    p = tmp_path / "project_roles.csv"
    p.write_text(
        "project_id,user_id,role\nP1,mentor1,mentor\nP1,mentee1,mentee\nP2,mentor2,mentor\n"
    )
    roles = _load_project_roles(str(p))
    assert roles == {"P1": {"mentor1": "mentor", "mentee1": "mentee"}, "P2": {"mentor2": "mentor"}}


def test_openment_roles_carried_into_doc_metadata(tmp_path: Path):
    from miner.openment_ingester import (
        _attach_comments,
        _load_issues,
        _load_project_map,
        _load_project_roles,
        iter_openment_docs,
    )

    issues_csv = tmp_path / "issues_pull_requests.csv"
    issues_csv.write_text(
        "issue_pr_id,author_id,type,title,body,status,creation_day,close_day\n"
        '"ABC","mentor1","issue","Ti","Bo","open","1","2"\n'
    )
    project_map_path = tmp_path / "project_issue_pr_map.csv"
    project_map_path.write_text("project_id,issue_pr_id\nP1,ABC\n")
    comments_csv = tmp_path / "comments.csv"
    comments_csv.write_text(
        "comment_id,issue_pr_id_x,author_id_x,text_x,creation_day_x\n"
        '"c1","ABC","mentee1","a comment",3\n'
    )
    roles_csv = tmp_path / "project_roles.csv"
    roles_csv.write_text("project_id,user_id,role\nP1,mentor1,mentor\nP1,mentee1,mentee\n")

    issues = _load_issues(str(issues_csv))
    _attach_comments(issues, str(comments_csv))
    roles = _load_project_roles(str(roles_csv))
    docs = iter_openment_docs(issues, _load_project_map(str(project_map_path)), roles)
    doc = docs[0]
    assert doc["metadata"]["roles"] == {"mentor1": "mentor", "mentee1": "mentee"}


# ── slack / disco XML ─────────────────────────────────────────────────────────


def _write_slack_xml(tmp_path: Path, name: str, messages: list[tuple[str, str, str]]) -> Path:
    p = tmp_path / "data" / "pythondev" / "2018" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    inner = "\n".join(
        (
            f'<message conversation_id="{conv}">'
            f"<ts>{ts}</ts><user>{user}</user><text>{text}</text></message>"
        )
        for conv, ts, user, text in messages
    )
    p.write_text(
        f"<slack><team_domain>pythondev</team_domain><channel_name>help</channel_name>{inner}</slack>"
    )
    return p


def test_slack_xml_parses_messages(_unit):
    from miner.slack_ingester import iter_slack_records

    p = _write_slack_xml(
        _unit,
        "merged-pythondev-help.xml",
        [
            ("1", "2017-06-16T10:51:34", "Melvin", "how do i do this"),
            ("1", "2017-06-16T10:52:00", "Beula", "like this"),
        ],
    )
    docs = list(iter_slack_records(str(p)))
    assert len(docs) == 2
    assert docs[0]["record_id"].startswith("chat_message:preethac-slack:pythondev:help")
    assert docs[0]["conversation_id"] == "1"
    assert docs[0]["author_login"] == "slack:preethac-slack:Melvin"
    assert docs[0]["text"] == "how do i do this"


def test_slack_skips_no_user_message(_unit):
    from miner.slack_ingester import iter_slack_records

    p = _unit / "data" / "pythondev" / "2018" / "merged-pythondev-help.xml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "<slack><team_domain>d</team_domain><channel_name>c</channel_name>"
        "<message><ts>1</ts><user>u</user><text>ok</text></message>"
        "<message><ts>2</ts><text>no user</text></message></slack>"
    )
    docs = list(iter_slack_records(str(p)))
    assert len(docs) == 1


def test_discord_xml_matches_slack_shape(_unit):
    from miner.discord_ingester import iter_discord_records

    p = _unit / "data" / "clojurians" / "2020" / "clojure_2020.xml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "<discord><team_domain>Clojurians</team_domain><channel_name>clojure</channel_name>"
        "<message><ts>2020-02-15T23:02:46</ts><user>Ezrajames</user>"
        "<text>stm is really cool</text></message>"
        "</discord>"
    )
    docs = list(iter_discord_records(str(p)))
    assert len(docs) == 1
    assert docs[0]["record_id"].startswith("chat_message:disco:Clojurians")
    assert docs[0]["text"] == "stm is really cool"
    assert docs[0]["conversation_id"] is None  # base .xml has no conversation labels


# ── irc ───────────────────────────────────────────────────────────────────────


def test_irc_parse_ubuntu_and_newdomain_lines():
    from miner.irc_ingester import parse_line

    assert parse_line("[12:18] <tweaked> HrdwrBoB: ok how many partitions?") == (
        "ubuntu",
        "12:18",
        "tweaked",
        "HrdwrBoB: ok how many partitions?",
    )
    assert parse_line("rust 2018-05-29 [21:20:37] <talchas> but I don't know that I'd bother") == (
        "rust",
        "2018-05-29T21:20:37",
        "talchas",
        "but I don't know that I'd bother",
    )


def test_irc_window_emits_reply_and_conversation(_unit):
    from miner.irc_ingester import iter_irc_records_from_window

    ascii_p = _unit / "dev" / "2004-11-15_03.ascii.txt"
    ascii_p.parent.mkdir(parents=True, exist_ok=True)
    ascii_p.write_text(
        "[12:18] <a> first message\n[12:19] <b> reply to first\n[12:20] <a> and another\n"
    )
    annot_p = _unit / "dev" / "2004-11-15_03.annotation.txt"
    annot_p.write_text("2 1 - \n")  # message line 2 replies to line 1
    docs = list(iter_irc_records_from_window(str(ascii_p), str(annot_p)))
    assert len(docs) == 3
    by_text = {d["text"]: d for d in docs}
    assert by_text["reply to first"]["reply_to"] == [by_text["first message"]["record_id"]]
    # messages 1 and 2 are union'd into one conversation component
    c1 = by_text["first message"]["conversation_id"]
    c2 = by_text["reply to first"]["conversation_id"]
    assert c1 is not None and c1 == c2


# ── curated email ─────────────────────────────────────────────────────────────


def _write_entity_jl(tmp_path: Path, name: str, records: list[dict]) -> Path:
    p = tmp_path / "ffmpeg" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) for r in records))
    return p


def test_curated_email_mailinglist_record(_unit):
    from miner.curated_email_ingester import iter_records

    p = _write_entity_jl(
        _unit,
        "ffmpeg_mailinglist.jl",
        [
            {
                "msg_id": "<m@x>",
                "subject": "[FFmpeg-devel] subject",
                "content": "body",
                "date": "2019-06-11 16:25:29",
                "sender_name": "A",
                "original_id": "ffmpeg-mailinglist-1",
            },
        ],
    )
    docs = list(iter_records(str(p)))
    assert len(docs) == 1
    assert docs[0]["urn"].startswith("curatedemail:ffmpeg:")
    assert docs[0]["subject"] == "[FFmpeg-devel] subject"
    assert docs[0]["body_text"] == "body"
    assert docs[0]["lang"] == "en"


def test_curated_email_patch_excludes_code_diff(_unit):
    """code_diff is code, not authored NL discourse — never becomes a TextUnit."""
    from miner.curated_email_ingester import iter_records

    p = _write_entity_jl(
        _unit,
        "ffmpeg_patch.jl",
        [
            {
                "name": "cover",
                "msg_content": "cover text",
                "code_diff": "+++ huge diff",
                "original_id": "ffmpeg-patch-1",
            },
        ],
    )
    docs = list(iter_records(str(p)))
    assert docs[0]["body_text"] == "cover text"  # msg_content, NOT code_diff
    assert "huge diff" not in docs[0]["body_text"]


def test_curated_email_drops_no_subject(_unit):
    from miner.curated_email_ingester import iter_records

    p = _write_entity_jl(
        _unit,
        "ffmpeg_comment.jl",
        [
            {"msg_content": "no subject", "original_id": "c1"},
        ],
    )
    assert list(iter_records(str(p))) == []


def test_curated_email_sample_rate(_unit):
    from miner.curated_email_ingester import iter_records

    records = [
        {"subject": f"Sub {i}", "msg_content": f"Body {i}", "original_id": f"c{i}"}
        for i in range(100)
    ]
    p = _write_entity_jl(_unit, "ozlabs_comment.jl", records)
    all_docs = list(iter_records(str(p), sample_rate=1.0))
    assert len(all_docs) == 100

    sampled_docs = list(iter_records(str(p), sample_rate=0.4484))
    # Sampled count should be approximately 45% (e.g. 35-55)
    assert 30 <= len(sampled_docs) <= 60


def test_curated_email_skips_oversized_body(_unit):
    """Bodies > DEFAULT_MAX_WORDS are dropped so the raw doc stays under Mongo's
    16 MiB BSON limit (kernel-comment-24774599 crash, CHANGELOG 2026-08-18)."""
    from miner.curated_email_ingester import DEFAULT_MAX_WORDS, iter_records

    small = {"subject": "small", "msg_content": "a few words", "original_id": "c1"}
    big = {
        "subject": "big",
        "msg_content": " ".join(["word"] * (DEFAULT_MAX_WORDS + 1)),
        "original_id": "c2",
    }
    p = _write_entity_jl(_unit, "ffmpeg_comment.jl", [small, big])

    docs = list(iter_records(str(p)))
    assert len(docs) == 1
    assert docs[0]["metadata"]["original_id"] == "c1"

    # max_words=None disables the guard entirely.
    docs_all = list(iter_records(str(p), max_words=None))
    assert len(docs_all) == 2

    # A custom threshold drops a body above it and keeps one below.
    docs_custom = list(iter_records(str(p), max_words=DEFAULT_MAX_WORDS + 1))
    assert len(docs_custom) == 2


# ── stack overflow (needs openpyxl) ───────────────────────────────────────────


def test_so_workbook_dedup_by_text(_unit):
    openpyxl = pytest.importorskip("openpyxl")
    from miner.stackoverflow_ingester import iter_so_records

    p = _unit / "Emotions_GoldSandard_andAnnotation.xlsx"
    wb = openpyxl.Workbook()
    for sheet_name in ("Love_all", "Joy_all"):
        ws = wb.create_sheet(sheet_name)
        ws.append(["Group", "Set", None, "Text", "rater 1", "rater 2", "rater 3", "Gold Label"])
        ws.append(["A", "Second", 1, "the same physical post text", "X", None, "X", "LOVE"])
        ws.append(["A", "Second", 2, "a distinct post", None, "x", None, ""])
    wb.save(p)

    docs = list(iter_so_records(str(p)))
    texts = {d["text"] for d in docs}
    # "the same physical post text" appears in BOTH sheets but is emitted once.
    assert len(docs) == 2
    assert texts == {"the same physical post text", "a distinct post"}
    assert all(d["post_type"] == "text" for d in docs)


# ── sotorrent ─────────────────────────────────────────────────────────────────


def test_sotorrent_html_to_text():
    from miner.sotorrent_ingester import html_to_text

    raw = """
    <p>I want to use a <code>Track-Bar</code> to change opacity &amp; color.</p>
    <p>Here is my code:</p>
    <pre class="lang-cs"><code>decimal trans = 0.5m;</code></pre>
    <p>What&#39;s wrong?</p>
    <script>alert('bad');</script>
    <style>body { color: red; }</style>
    """
    cleaned = html_to_text(raw)
    assert "Track-Bar" not in cleaned  # inline <code> stripped
    assert "decimal trans" not in cleaned  # <pre><code> block stripped
    assert "bad" not in cleaned  # <script> stripped
    assert "color: red" not in cleaned  # <style> stripped
    assert "opacity & color." in cleaned  # &amp; entity unescaped
    assert "What's wrong?" in cleaned  # &#39; entity unescaped


def test_sotorrent_parse_mysql_insert_tuples():
    from miner.sotorrent_ingester import parse_mysql_insert_tuples

    line = (
        r"INSERT INTO `Posts` VALUES (1,1,NULL,NULL,'2020-01-01 10:00:00',NULL,10,100,"
        r"'<p>Body with \'escaped quotes\' and \\n newline</p>',42,'Alice',NULL,NULL,"
        r"NULL,NULL,'Question 1','<tag>',1,0,0,NULL,NULL),"
        r"(2,2,NULL,1,'2020-01-01 11:00:00',NULL,5,NULL,'<p>Answer</p>',43,'Bob',"
        r"NULL,NULL,NULL,NULL,NULL,NULL,0,0,0,NULL,NULL);"
    )
    rows = list(parse_mysql_insert_tuples(line))
    assert len(rows) == 2
    assert rows[0][0] == 1
    assert rows[0][1] == 1
    assert rows[0][4] == "2020-01-01 10:00:00"
    assert rows[0][5] is None
    assert "escaped quotes" in rows[0][8]
    assert rows[0][9] == 42
    assert rows[0][15] == "Question 1"

    assert rows[1][0] == 2
    assert rows[1][1] == 2
    assert rows[1][3] == 1
    assert rows[1][8] == "<p>Answer</p>"


def test_sotorrent_iter_records_and_linking(tmp_path: Path):
    from miner.sotorrent_ingester import iter_sotorrent_records

    row_q = (
        "(100,1,101,NULL,'2020-01-01 10:00:00',NULL,15,200,"
        "'<p>Question body with <code>some_code()</code></p>',10,'User1',"
        "NULL,NULL,NULL,NULL,'How to test?','<python>',1,0,0,NULL,NULL)"
    )
    row_a = (
        "(101,2,NULL,100,'2020-01-01 11:00:00',NULL,8,NULL,'<p>Answer body</p>',"
        "20,'User2',NULL,NULL,NULL,NULL,NULL,NULL,0,0,0,NULL,NULL)"
    )
    row_del = (
        "(102,1,NULL,NULL,'2020-01-01 12:00:00','2020-01-02 00:00:00',0,0,"
        "'<p>Deleted</p>',10,'User1',NULL,NULL,NULL,NULL,'Deleted','<tag>',0,0,0,NULL,NULL)"
    )
    row_wiki = (
        "(103,5,NULL,NULL,'2020-01-01 13:00:00',NULL,0,0,'<p>TagWiki</p>',10,'User1',"
        "NULL,NULL,NULL,NULL,'TagWiki','<tag>',0,0,0,NULL,NULL)"
    )
    sql_content = f"""
    CREATE TABLE `Posts` (
      `Id` int NOT NULL,
      `PostTypeId` tinyint DEFAULT NULL,
      `AcceptedAnswerId` int DEFAULT NULL,
      `ParentId` int DEFAULT NULL,
      `CreationDate` datetime DEFAULT NULL,
      `DeletionDate` datetime DEFAULT NULL,
      `Score` int DEFAULT NULL,
      `ViewCount` int DEFAULT NULL,
      `Body` mediumtext,
      `OwnerUserId` int DEFAULT NULL,
      `OwnerDisplayName` varchar(40) DEFAULT NULL,
      `LastEditorUserId` int DEFAULT NULL,
      `LastEditorDisplayName` varchar(40) DEFAULT NULL,
      `LastEditDate` datetime DEFAULT NULL,
      `LastActivityDate` datetime DEFAULT NULL,
      `Title` varchar(250) DEFAULT NULL,
      `Tags` varchar(150) DEFAULT NULL,
      `AnswerCount` int DEFAULT '0',
      `CommentCount` int DEFAULT '0',
      `FavoriteCount` int DEFAULT '0',
      `ClosedDate` datetime DEFAULT NULL,
      `CommunityOwnedDate` datetime DEFAULT NULL,
      PRIMARY KEY (`Id`)
    ) ENGINE=InnoDB;

    INSERT INTO `Posts` VALUES
    {row_q},
    {row_a},
    {row_del},
    {row_wiki};
    """
    p = tmp_path / "Posts.sql"
    p.write_text(sql_content)

    docs = list(iter_sotorrent_records(str(p), stride=1, min_score=None))
    assert len(docs) == 2  # deleted (102) and TagWiki (103) are excluded

    q_doc = docs[0]
    assert q_doc["record_id"] == "so_post:sotorrent:100"
    assert q_doc["post_type"] == "question"
    assert q_doc["artefact_kind"] == "so_question"
    assert q_doc["title"] == "How to test?"
    assert q_doc["text"] == "Question body with"
    assert q_doc["author_login"] == "stackoverflow:sotorrent:10"
    assert q_doc["created_at"] == "2020-01-01T10:00:00Z"
    assert q_doc["question_id"] == "100"
    assert q_doc["parent_post_id"] is None
    assert q_doc["question_record_id"] is None
    assert "StackOverflowQuestion" in q_doc["artefact_labels"]

    a_doc = docs[1]
    assert a_doc["record_id"] == "so_post:sotorrent:101"
    assert a_doc["post_type"] == "answer"
    assert a_doc["artefact_kind"] == "so_answer"
    assert a_doc["title"] is None
    assert a_doc["text"] == "Answer body"
    assert a_doc["author_login"] == "stackoverflow:sotorrent:20"
    assert a_doc["created_at"] == "2020-01-01T11:00:00Z"
    assert a_doc["question_id"] == "100"
    assert a_doc["parent_post_id"] == "100"
    assert a_doc["question_record_id"] == "so_post:sotorrent:100"
    assert "StackOverflowAnswer" in a_doc["artefact_labels"]


def test_sotorrent_stride_and_min_score_filter(tmp_path: Path):
    from miner.sotorrent_ingester import iter_sotorrent_records

    # Generate 14 posts with varying IDs and scores
    # stride=7 matches Id=7, 14, 21...
    rows = []
    for i in range(1, 22):
        score = 0 if i == 7 else (5 if i == 14 else 1)
        r = (
            f"({i},1,NULL,NULL,'2020-01-01 10:00:00',NULL,{score},100,"
            f"'<p>Post {i}</p>',1,'U1',NULL,NULL,NULL,NULL,'Title {i}','<tag>',0,0,0,NULL,NULL)"
        )
        rows.append(r)
    sql_content = f"""
    CREATE TABLE `Posts` (
      `Id` int NOT NULL,
      `PostTypeId` tinyint DEFAULT NULL,
      `AcceptedAnswerId` int DEFAULT NULL,
      `ParentId` int DEFAULT NULL,
      `CreationDate` datetime DEFAULT NULL,
      `DeletionDate` datetime DEFAULT NULL,
      `Score` int DEFAULT NULL,
      `ViewCount` int DEFAULT NULL,
      `Body` mediumtext,
      `OwnerUserId` int DEFAULT NULL,
      `OwnerDisplayName` varchar(40) DEFAULT NULL,
      `LastEditorUserId` int DEFAULT NULL,
      `LastEditorDisplayName` varchar(40) DEFAULT NULL,
      `LastEditDate` datetime DEFAULT NULL,
      `LastActivityDate` datetime DEFAULT NULL,
      `Title` varchar(250) DEFAULT NULL,
      `Tags` varchar(150) DEFAULT NULL,
      `AnswerCount` int DEFAULT '0',
      `CommentCount` int DEFAULT '0',
      `FavoriteCount` int DEFAULT '0',
      `ClosedDate` datetime DEFAULT NULL,
      `CommunityOwnedDate` datetime DEFAULT NULL,
      PRIMARY KEY (`Id`)
    ) ENGINE=InnoDB;

    INSERT INTO `Posts` VALUES
    {",\n    ".join(rows)};
    """
    p = tmp_path / "Posts.sql"
    p.write_text(sql_content)

    # Stride 7 only (min_score=None): matches Id=7, 14, 21 -> 3 posts
    docs_stride = list(iter_sotorrent_records(str(p), stride=7, min_score=None))
    assert [d["external_id"] for d in docs_stride] == ["7", "14", "21"]

    # Stride 7 + min_score=1: Id=7 has score=0 -> filtered out, matches Id=14 and 21 -> 2 posts
    docs_stratified = list(iter_sotorrent_records(str(p), stride=7, min_score=1))
    assert [d["external_id"] for d in docs_stratified] == ["14", "21"]


@pytest.mark.asyncio
async def test_sotorrent_dry_run_with_max(tmp_path: Path):
    from miner.sotorrent_ingester import ingest

    r1 = (
        "(7,1,NULL,NULL,'2020-01-01 10:00:00',NULL,10,100,'<p>Post 1</p>',1,'U1',"
        "NULL,NULL,NULL,NULL,'Title 1','<tag>',0,0,0,NULL,NULL)"
    )
    r2 = (
        "(14,1,NULL,NULL,'2020-01-01 11:00:00',NULL,10,100,'<p>Post 2</p>',2,'U2',"
        "NULL,NULL,NULL,NULL,'Title 2','<tag>',0,0,0,NULL,NULL)"
    )
    r3 = (
        "(21,1,NULL,NULL,'2020-01-01 12:00:00',NULL,10,100,'<p>Post 3</p>',3,'U3',"
        "NULL,NULL,NULL,NULL,'Title 3','<tag>',0,0,0,NULL,NULL)"
    )
    sql_content = f"""
    CREATE TABLE `Posts` (
      `Id` int NOT NULL,
      `PostTypeId` tinyint DEFAULT NULL,
      `AcceptedAnswerId` int DEFAULT NULL,
      `ParentId` int DEFAULT NULL,
      `CreationDate` datetime DEFAULT NULL,
      `DeletionDate` datetime DEFAULT NULL,
      `Score` int DEFAULT NULL,
      `ViewCount` int DEFAULT NULL,
      `Body` mediumtext,
      `OwnerUserId` int DEFAULT NULL,
      `OwnerDisplayName` varchar(40) DEFAULT NULL,
      `LastEditorUserId` int DEFAULT NULL,
      `LastEditorDisplayName` varchar(40) DEFAULT NULL,
      `LastEditDate` datetime DEFAULT NULL,
      `LastActivityDate` datetime DEFAULT NULL,
      `Title` varchar(250) DEFAULT NULL,
      `Tags` varchar(150) DEFAULT NULL,
      `AnswerCount` int DEFAULT '0',
      `CommentCount` int DEFAULT '0',
      `FavoriteCount` int DEFAULT '0',
      `ClosedDate` datetime DEFAULT NULL,
      `CommunityOwnedDate` datetime DEFAULT NULL,
      PRIMARY KEY (`Id`)
    ) ENGINE=InnoDB;

    INSERT INTO `Posts` VALUES
    {r1},
    {r2},
    {r3};
    """
    p = tmp_path / "Posts.sql"
    p.write_text(sql_content)

    kept = await ingest(path=str(p), max_records=2, dry_run=True)
    assert kept == 2


# ── external_common: path splitting + linear progress accounting ─────────────


def test_data_path_parts_splits_community_period(tmp_path: Path):
    from miner.external_common import data_path_parts

    # DISCO / Slack layout: <root>/data/<community>/<period>/<file>
    p = tmp_path / "data" / "clojurians" / "2020" / "clojure_2020.xml"
    assert data_path_parts(str(p)) == ("clojurians", "2020", "clojure_2020.xml")
    # a deep dataset root (with its own dirs) must not confuse the extraction
    p2 = tmp_path / "DISCO-A Dataset" / "data" / "clojurians" / "2020" / "a.xml"
    assert data_path_parts(str(p2)) == ("clojurians", "2020", "a.xml")
    # degenerate path (no data/ component) falls back safely
    assert data_path_parts(str(tmp_path / "orphan.xml")) == (
        "unknown",
        "unknown",
        "orphan.xml",
    )


def test_discord_record_id_uses_real_period(_unit):
    from miner.discord_ingester import iter_discord_records

    p = _unit / "data" / "clojurians" / "2020" / "clojure_2020.xml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "<discord><team_domain>Clojurians</team_domain><channel_name>clojure</channel_name>"
        "<message><ts>2020-02-15T23:02:46</ts><user>Ezrajames</user>"
        "<text>stm is really cool</text></message></discord>"
    )
    docs = list(iter_discord_records(str(p)))
    assert len(docs) == 1
    # Pre-fix the relative path cut one dir short of data/, so "period" became
    # the channel filename ("clojure_2020") and community became "2020".
    assert docs[0]["metadata"]["file_period"] == "2020"
    assert docs[0]["metadata"]["team_domain"] == "Clojurians"
    assert ":2020:" in docs[0]["record_id"]


def test_slack_record_id_contains_year(_unit):
    from miner.slack_ingester import iter_slack_records

    p = _unit / "data" / "pythondev" / "2018" / "merged-pythondev-help.xml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "<slack><team_domain>pythondev</team_domain><channel_name>help</channel_name>"
        '<message conversation_id="1"><ts>1</ts><user>u</user><text>ok</text></message></slack>'
    )
    docs = list(iter_slack_records(str(p)))
    assert len(docs) == 1
    # Pre-fix community/period always fell back to "unknown" ("...:help:unknown:1").
    assert docs[0]["metadata"]["file_period"] == "2018"
    assert ":help:2018:1" in docs[0]["record_id"]


def test_alt_author_name_handles_dict_and_string():
    from miner.jira_ingester import _alt_author_name

    # Pre-fix a user dict was stringified into "-name-:-johndoe-" by sanitise_token.
    assert _alt_author_name({"name": "johndoe", "displayName": "John Doe"}) == "johndoe"
    assert _alt_author_name({"displayName": "John Doe"}) == "John Doe"
    assert _alt_author_name({"username": "jdoe"}) == "jdoe"
    assert _alt_author_name("johndoe") == "johndoe"
    assert _alt_author_name("") is None
    assert _alt_author_name(None) is None


# ── Alternative Jira normalization (nested Jira REST /search shape) ──────────


def _alt_jira_doc(**fields):
    """Synthetic doc matching the real dataset shape: top-level `key`, the rest
    nested under `fields` (see miner/jira_ingester.py ALTI_FIELD_MAP)."""
    base = {
        "fields": {
            "summary": "Summary",
            "description": "Description",
            "status": {"name": "Open"},
            "creator": {"name": "uuid-creator"},
            "created": "2024-01-01T00:00:00Z",
            "project": {"name": "Spring Framework"},
            "comments": [
                {
                    "body": "First!",
                    "created": "2024-01-02T00:00:00Z",
                    "author": {"name": "uuid-commenter"},
                }
            ],
        }
    }
    base["fields"].update(fields)
    return base


def test_alt_normalize_nested_rest_shape():
    from miner.jira_ingester import normalize_alternative_doc

    raw = {"key": "SPRING-1", **_alt_jira_doc()}
    doc = normalize_alternative_doc(raw, "SpringFramework")

    assert doc is not None
    assert doc["record_id"] == "jira_issue:alternative-jira:SpringFramework:SPRING-1"
    assert doc["external_id"] == "SPRING-1"
    assert doc["title"] == "Summary"
    assert doc["body"] == "Description"
    assert doc["state"] == "Open"
    assert doc["created_at"] == "2024-01-01T00:00:00Z"
    assert doc["metadata"]["jira_instance"] == "SpringFramework"
    # venue carries the Jira instance so projects can't merge across instances
    assert doc["venue_id"] == "jira:alternative-jira:springframework:spring-framework"
    assert doc["comments"][0]["body"] == "First!"
    assert doc["comments"][0]["created_at"] == "2024-01-02T00:00:00Z"
    # each comment keeps its own author, not the issue creator
    assert doc["comments"][0]["author_login"] == "jira:alternative-jira:uuid-commenter"


def test_alt_normalize_no_text_returns_none():
    from miner.jira_ingester import normalize_alternative_doc

    raw = {"key": "SPRING-2", **_alt_jira_doc(summary="", description="")}
    assert normalize_alternative_doc(raw, "SpringFramework") is None


def test_alt_normalize_missing_key_returns_none():
    from miner.jira_ingester import normalize_alternative_doc

    assert normalize_alternative_doc(_alt_jira_doc(), "SpringFramework") is None


def test_alt_normalize_none_comments():
    from miner.jira_ingester import normalize_alternative_doc

    raw = {"key": "SPRING-3", **_alt_jira_doc(comments=None)}
    doc = normalize_alternative_doc(raw, "SpringFramework")
    assert doc is not None
    assert doc["comments"] == []


def test_alt_normalize_record_id_unique_per_instance():
    from miner.jira_ingester import normalize_alternative_doc

    # Same issue key in two Jira instances must not collide on record_id.
    raw = {"key": "PROJ-1", **_alt_jira_doc()}
    a = normalize_alternative_doc(raw, "MongoDB")["record_id"]
    b = normalize_alternative_doc(raw, "SpringFramework")["record_id"]
    assert a != b
    assert "MongoDB" in a and "SpringFramework" in b


class _FakeColl:
    def __init__(self):
        self.seen: set[str] = set()

    async def create_index(self, key, unique=False):
        return None


class _FakeBroker:
    def __init__(self):
        self.published: list[dict] = []

    async def publish(self, stream, event):
        self.published.append(event)


class _ProgressRecorder:
    """Stand-in for progress.Progress that records every `add(n)` call."""

    instances: list[_ProgressRecorder] = []

    def __init__(self, label, total=None, log_every_sec=5.0):
        self.adds: list[int] = []
        _ProgressRecorder.instances.append(self)

    def add(self, n):
        self.adds.append(n)

    def maybe_log(self, remaining=None, force=False):
        pass

    def finish(self):
        pass


@pytest.fixture
def _external_services(monkeypatch):
    """Monkeypatch Mongo/Redis/progress so run_external_ingest runs fully offline."""
    import broker as broker_mod
    import progress as progress_mod
    import storage as storage_mod

    _ProgressRecorder.instances.clear()
    coll = _FakeColl()
    broker = _FakeBroker()

    class _DB(dict):
        def __getitem__(self, name):
            return coll

    class _Client:
        def __getitem__(self, name):
            return _DB()

        def close(self):
            pass

    async def _fake_upsert(collection, docs, key_field, use_insert_for_fresh_load=False):
        new = []
        for d in docs:
            if d[key_field] not in coll.seen:
                coll.seen.add(d[key_field])
                new.append({**d, "_id": d[key_field]})
        return new

    async def _get_broker():
        return broker

    monkeypatch.setattr(storage_mod, "make_mongo_client", lambda: _Client())
    monkeypatch.setattr(broker_mod, "get_broker", _get_broker)
    monkeypatch.setattr(storage_mod, "bulk_upsert_on_key", _fake_upsert)
    monkeypatch.setattr(progress_mod, "Progress", _ProgressRecorder)
    return coll, broker


@pytest.mark.asyncio
async def test_run_external_ingest_progress_is_linear(_external_services):
    """Regression for the quadratic progress bug: prog.add() was fed the CUMULATIVE
    kept total, so done grew as 1000*B*(B+1) and the reported rate rose ~linearly.
    Each flush must advance progress by the batch size only."""
    _, broker = _external_services

    docs = [{"record_id": f"r{i}", "text": "t"} for i in range(6)]
    kept = await run_external_ingest(
        docs=iter(docs),
        collection="x",
        key_field="record_id",
        event_for=lambda d, mid: {"item_type": "chat_message", "mongo_id": mid},
        batch_size=2,
    )
    assert kept == 6
    assert len(broker.published) == 6
    rec = _ProgressRecorder.instances[0]
    # Linear accounting: each batch contributes its own size.
    assert rec.adds == [2, 2, 2]


@pytest.mark.asyncio
async def test_run_external_ingest_max_bounds_batch(_external_services):
    """--max smaller than the default batch must shrink the batch, not over-shoot."""
    _, broker = _external_services

    docs = [{"record_id": f"r{i}", "text": "t"} for i in range(5)]
    kept = await run_external_ingest(
        docs=iter(docs),
        collection="x",
        key_field="record_id",
        event_for=lambda d, mid: {"item_type": "chat_message", "mongo_id": mid},
        max_records=2,
        batch_size=2000,
    )
    assert kept == 2
    assert len(broker.published) == 2
    assert _ProgressRecorder.instances[0].adds == [2]


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def _unit(tmp_path: Path) -> Path:
    return tmp_path
