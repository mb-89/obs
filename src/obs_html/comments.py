from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


class CommentError(ValueError):
    """Raised when returned HTML has an invalid comment island."""


class _CommentIslandParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.islands: list[str] = []
        self._chunks: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "script" and attributes.get("id") == "obs-comments":
            if self._chunks is not None:
                raise CommentError("Comment islands may not be nested.")
            self._chunks = []

    def handle_data(self, data: str) -> None:
        if self._chunks is not None:
            self._chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._chunks is not None:
            self.islands.append("".join(self._chunks))
            self._chunks = None


def extract_comments(report_path: Path) -> str:
    parser = _CommentIslandParser()
    parser.feed(report_path.read_text(encoding="utf-8-sig"))
    parser.close()
    if len(parser.islands) != 1:
        raise CommentError(
            f"Reviewed HTML must contain exactly one obs-comments island; found {len(parser.islands)}."
        )
    try:
        raw = json.loads(parser.islands[0])
    except json.JSONDecodeError as error:
        raise CommentError(f"Invalid obs-comments JSON: {error.msg}.") from error
    annotations = _validate_island(raw)
    return _format_candidates(annotations)


def _validate_island(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict) or raw.get("version") != 2:
        raise CommentError("Comment island must be a version 2 object.")
    annotations = raw.get("annotations")
    if not isinstance(annotations, list):
        raise CommentError("Comment island annotations must be an array.")
    _validate_review_data(raw)
    normalized = []
    seen_ids: set[str] = set()
    for index, annotation in enumerate(annotations, start=1):
        if not isinstance(annotation, dict):
            raise CommentError(f"Comment {index} must be an object.")
        comment_id = _required_string(annotation.get("id"), f"Comment {index} id")
        if comment_id in seen_ids:
            raise CommentError(f"Comment id is duplicated: {comment_id}.")
        seen_ids.add(comment_id)
        target = _validate_target(annotation.get("target"), comment_id)
        node = _validate_node(annotation, f"Comment {comment_id}", seen_ids, known_id=comment_id)
        batch = {"batch": _validate_batch(annotation["batch"])} if "batch" in annotation else {}
        normalized.append({**node, "target": target, **batch})
    return normalized


def _validate_review_data(raw: dict[str, Any]) -> None:
    reviewers = raw.get("reviewers", [])
    if not isinstance(reviewers, list):
        raise CommentError("Comment island reviewers must be an array.")
    normalized_reviewers = []
    for index, reviewer in enumerate(reviewers, start=1):
        normalized_reviewers.append(_required_string(reviewer, f"Reviewer {index}"))
    if len(normalized_reviewers) != len(set(normalized_reviewers)):
        raise CommentError("Comment island reviewers must be unique.")

    reviews = raw.get("reviews", [])
    if not isinstance(reviews, list):
        raise CommentError("Comment island reviews must be an array.")
    seen: set[tuple[str, str, str]] = set()
    for index, review in enumerate(reviews, start=1):
        if not isinstance(review, dict):
            raise CommentError(f"Review {index} must be an object.")
        chapter = _required_string(review.get("chapter"), f"Review {index} chapter")
        item = _required_string(review.get("item"), f"Review {index} item")
        if not _is_review_item(item):
            raise CommentError(f"Review {index} item must be a review item identifier.")
        reviewer = _required_string(review.get("reviewer"), f"Review {index} reviewer")
        state = review.get("state")
        if state not in {"accepted", "rejected"}:
            raise CommentError(f"Review {index} has invalid state: {state}.")
        key = (chapter, item, reviewer)
        if key in seen:
            raise CommentError(f"Review decision is duplicated: {chapter} {item} {reviewer}.")
        seen.add(key)


def _is_review_item(item: str) -> bool:
    return (
        item.startswith("item-") and item.removeprefix("item-").isdigit()
        or item.startswith("row-") and len(item.split(":", 1)) == 2
        and all(item.removeprefix("row-").split(":", 1))
    )


def _validate_batch(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("scope") not in ("section", "chapter", "document"):
        raise CommentError("Comment batch scope must be section, chapter or document.")
    items = raw.get("items")
    if not isinstance(items, list) or not items:
        raise CommentError("Comment batch items must be a non-empty array.")
    normalized = []
    seen = set()
    for identity in items:
        if not isinstance(identity, dict):
            raise CommentError("Comment batch identity must be an object.")
        chapter = _required_string(identity.get("chapter"), "Comment batch chapter")
        item = _required_string(identity.get("item"), "Comment batch item")
        if not _is_review_item(item):
            raise CommentError("Comment batch item must be a review item identifier.")
        if (chapter, item) in seen:
            raise CommentError("Comment batch items must be unique.")
        seen.add((chapter, item))
        normalized.append({"chapter": chapter, "item": item})
    return {"scope": raw["scope"], "items": normalized}


def _validate_node(
    raw: dict[str, Any],
    label: str,
    seen_ids: set[str],
    *,
    known_id: str | None = None,
) -> dict[str, Any]:
    comment_id = known_id or _required_string(raw.get("id"), f"{label} id")
    if known_id is None:
        if comment_id in seen_ids:
            raise CommentError(f"Comment id is duplicated: {comment_id}.")
        seen_ids.add(comment_id)
    status = raw.get("status", "open")
    if status not in {"open", "resolved"}:
        raise CommentError(f"Comment {comment_id} has invalid status: {status}.")
    author = raw.get("author", "")
    if not isinstance(author, str):
        raise CommentError(f"Comment {comment_id} author must be text.")
    text = raw.get("text")
    if not isinstance(text, str):
        raise CommentError(f"Comment {comment_id} text must be text.")
    raw_replies = raw.get("replies", [])
    if not isinstance(raw_replies, list):
        raise CommentError(f"Comment {comment_id} replies must be an array.")
    replies = []
    for index, reply in enumerate(raw_replies, start=1):
        if not isinstance(reply, dict):
            raise CommentError(f"Comment {comment_id} reply {index} must be an object.")
        replies.append(_validate_node(reply, f"Comment {comment_id} reply {index}", seen_ids))
    return {
        "id": comment_id,
        "status": status,
        "author": author.strip(),
        "text": text,
        "replies": replies,
    }


def _validate_target(raw: Any, comment_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CommentError(f"Comment {comment_id} target must be an object.")
    target: dict[str, Any] = {
        "chapter": _required_string(raw.get("chapter"), f"Comment {comment_id} target chapter")
    }
    for key in ("quote", "prefix", "suffix"):
        value = raw.get(key, "")
        if not isinstance(value, str):
            raise CommentError(f"Comment {comment_id} target {key} must be text.")
        if value:
            target[key] = value
    for key in ("start", "end"):
        value = raw.get(key)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CommentError(f"Comment {comment_id} target {key} must be a non-negative integer.")
            target[key] = value
    if "table" in raw or "row" in raw or "detail" in raw or "column" in raw:
        target["table"] = _required_string(raw.get("table"), f"Comment {comment_id} table")
        target["row"] = _required_string(raw.get("row"), f"Comment {comment_id} row")
        if not isinstance(raw.get("detail"), bool):
            raise CommentError(f"Comment {comment_id} detail must be a boolean.")
        target["detail"] = raw["detail"]
        if "column" in raw:
            if not raw["detail"]:
                raise CommentError(f"Comment {comment_id} column requires a detail target.")
            target["column"] = _required_string(raw["column"], f"Comment {comment_id} column")
    if "start" in target or "end" in target:
        if "start" not in target or "end" not in target or target["end"] < target["start"]:
            raise CommentError(f"Comment {comment_id} target positions are invalid.")
    return target


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CommentError(f"{label} must be non-empty text.")
    return value.strip()


def _format_candidates(annotations: list[dict[str, Any]]) -> str:
    roles: dict[str, str] = {}

    def role(author: str) -> str:
        if not author:
            return "reviewer"
        if author not in roles:
            roles[author] = f"reviewer-{len(roles) + 1}"
        return roles[author]

    lines = [f"comment candidates: {len(annotations)}"]

    def append_comment(comment: dict[str, Any], depth: int) -> None:
        marker = "  " * depth
        status = f" [{comment['status']}]" if depth else ""
        lines.append(f"{marker}{role(comment['author'])}{status}: {comment['text']}")
        for reply in comment["replies"]:
            append_comment(reply, depth + 1)

    for annotation in annotations:
        target = annotation["target"]
        lines.append(
            f"--- {annotation['id']} [{annotation['status']}] chapter {target['chapter']}"
        )
        if target.get("quote"):
            lines.append(f"quote: {target['quote']}")
        if batch := annotation.get("batch"):
            lines.append(f"[Full {batch['scope']}]")
            lines.extend(f"item: {item['chapter']} {item['item']}" for item in batch["items"])
        append_comment(annotation, 0)
    return "\n".join(lines) + "\n"