#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Dump WeChat messages as structured JSON/JSONL.

This is meant to be easier to inspect/process than dump-msg.py's line-oriented
text format.  By default it avoids embedding huge raw XML payloads in the main
`content` field and instead extracts common metadata into `payload`.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import sys
from typing import Any, Dict, Iterable, List, Optional

from pyquery import PyQuery

from wechat.common.textutil import safe_filename
from wechat.msg import (
    TYPE_APP_MSG,
    TYPE_CUSTOM_EMOJI,
    TYPE_EMOJI,
    TYPE_FILE,
    TYPE_IMG,
    TYPE_LINK,
    TYPE_LOCATION,
    TYPE_LOCATION_SHARING,
    TYPE_MONEY_TRANSFER,
    TYPE_NAMECARD,
    TYPE_QQMUSIC,
    TYPE_REDENVELOPE,
    TYPE_REPLY,
    TYPE_SPEAK,
    TYPE_VIDEO_FILE,
    TYPE_VOIP,
    TYPE_WX_VIDEO,
)
from wechat.parser import WeChatDBParser

logger = logging.getLogger("wechat")

TYPE_NAMES = {
    1: "text",
    TYPE_IMG: "image",
    TYPE_SPEAK: "voice",
    TYPE_NAMECARD: "namecard",
    TYPE_VIDEO_FILE: "video_file",
    TYPE_EMOJI: "emoji",
    TYPE_LOCATION: "location",
    TYPE_LINK: "link_or_appmsg",
    TYPE_VOIP: "voip",
    TYPE_WX_VIDEO: "wechat_video",
    TYPE_CUSTOM_EMOJI: "custom_emoji",
    TYPE_REDENVELOPE: "red_envelope",
    TYPE_MONEY_TRANSFER: "money_transfer",
    TYPE_LOCATION_SHARING: "location_sharing",
    TYPE_REPLY: "reply",
    TYPE_FILE: "file",
    TYPE_QQMUSIC: "qqmusic",
    TYPE_APP_MSG: "app_msg",
}

ATTR_KEEP = {
    "emoji": [
        "md5",
        "productid",
        "cdnurl",
        "thumburl",
        "encrypturl",
        "aeskey",
        "externurl",
        "externmd5",
        "width",
        "height",
        "desc",
    ],
    "location": ["x", "y", "label", "poiname", "scale"],
    "msg": ["username", "nickname", "alias", "certflag"],
}


def one_line(text: str, max_len: int = 300) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text


def xml_query(xml: str, *, parser: str = "xml") -> Optional[PyQuery]:
    if not xml:
        return None
    try:
        return PyQuery(xml, parser=parser)
    except Exception:
        return None


def first_text(pq: PyQuery, selectors: Iterable[str]) -> str:
    for selector in selectors:
        try:
            text = pq(selector).eq(0).text()
        except Exception:
            text = ""
        if text:
            return html.unescape(text)
    return ""


def attrs_of(pq: PyQuery, selector: str, keep: Optional[List[str]] = None) -> Dict[str, str]:
    try:
        node = pq(selector)
        if not node:
            return {}
        attrs = dict(node.attr or {})
    except Exception:
        return {}
    if keep is None:
        return attrs
    return {k: html.unescape(str(attrs[k])) for k in keep if k in attrs and attrs[k] not in (None, "")}


def parse_xml_payload(msg) -> Dict[str, Any]:
    xml = msg.content_xml_ready
    payload: Dict[str, Any] = {}

    if msg.type in (TYPE_EMOJI, TYPE_CUSTOM_EMOJI):
        pq = xml_query(xml)
        attrs = attrs_of(pq, "emoji", ATTR_KEEP["emoji"]) if pq else {}
        payload.update(attrs)
        payload["summary"] = "[emoji]"
        return payload

    if msg.type == TYPE_LOCATION:
        pq = xml_query(xml)
        attrs = attrs_of(pq, "location", ATTR_KEEP["location"]) if pq else {}
        payload.update(attrs)
        label = attrs.get("poiname") or attrs.get("label") or ""
        payload["summary"] = f"[location] {label}".strip()
        return payload

    if msg.type == TYPE_NAMECARD:
        pq = xml_query(xml)
        attrs = attrs_of(pq, "msg", ATTR_KEEP["msg"]) if pq else {}
        payload.update(attrs)
        name = attrs.get("nickname") or attrs.get("alias") or attrs.get("username") or ""
        payload["summary"] = f"[namecard] {name}".strip()
        return payload

    if msg.type in (TYPE_LINK, TYPE_APP_MSG, TYPE_FILE, TYPE_REPLY, TYPE_QQMUSIC, TYPE_REDENVELOPE, TYPE_MONEY_TRANSFER):
        pq = xml_query(xml, parser="html") or xml_query(xml, parser="xml")
        if pq:
            payload["title"] = first_text(pq, ["appmsg > title", "title"])
            payload["description"] = first_text(pq, ["appmsg > des", "des", "description"])
            payload["url"] = first_text(pq, ["appmsg > url", "url"])
            payload["app_name"] = first_text(pq, ["appmsg > appname", "appname"])
            payload["type"] = first_text(pq, ["appmsg > type", "type"])
            payload = {k: v for k, v in payload.items() if v not in (None, "")}
        if msg.type == TYPE_REPLY:
            info = msg.reply_info()
            if info:
                payload["reply"] = info
        if msg.type == TYPE_FILE and not payload.get("title"):
            payload["title"] = one_line(xml)
        payload["summary"] = one_line(payload.get("title") or payload.get("description") or msg.msg_str())
        return payload

    return payload


def message_to_dict(msg, *, include_raw: bool = False) -> Dict[str, Any]:
    kind = TYPE_NAMES.get(msg.type, "unknown")
    sender_id = msg.talker if not msg.isSend else "me"
    sender_name = "me" if msg.isSend else getattr(msg, "talker_nickname", msg.talker)

    content = msg.msg_str()
    payload = parse_xml_payload(msg)
    if payload.get("summary"):
        content = payload["summary"]
    elif msg.type == TYPE_IMG:
        content = "[image]"
    elif msg.type == TYPE_SPEAK:
        content = "[voice]"
    elif msg.type == TYPE_VIDEO_FILE:
        content = "[video_file]"
    elif msg.type == TYPE_WX_VIDEO:
        content = "[wechat_video]"
    elif msg.type == TYPE_VOIP:
        content = "[voip]"
    elif msg.type == TYPE_LOCATION_SHARING:
        content = "[location_sharing]"

    item: Dict[str, Any] = {
        "msgSvrId": getattr(msg, "msgSvrId", None),
        "type": msg.type,
        "kind": kind,
        "known_type": bool(getattr(msg, "known_type", False)),
        "time": msg.createTime.isoformat(sep=" "),
        "timestamp_ms": int(msg.createTime.timestamp() * 1000),
        "is_send": bool(msg.isSend),
        "sender_id": sender_id,
        "sender_name": sender_name,
        "chat_id": msg.chat,
        "chat_name": getattr(msg, "chat_nickname", msg.chat),
        "content": content,
    }

    if getattr(msg, "imgPath", ""):
        item["img_path"] = msg.imgPath
    if payload:
        item["payload"] = {k: v for k, v in payload.items() if k != "summary"}
    if include_raw:
        item["raw_content"] = msg.content
    return item


def chat_to_obj(parser: WeChatDBParser, chatid: str, msgs, *, include_raw: bool = False) -> Dict[str, Any]:
    return {
        "chat_id": chatid,
        "chat_name": parser.contacts.get(chatid, chatid),
        "message_count": len(msgs),
        "messages": [message_to_dict(m, include_raw=include_raw) for m in msgs],
    }


def write_json(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def write_jsonl(path: str, msgs, *, include_raw: bool = False) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for m in msgs:
            f.write(json.dumps(message_to_dict(m, include_raw=include_raw), ensure_ascii=False))
            f.write("\n")


def main() -> int:
    argp = argparse.ArgumentParser(description="Dump WeChat messages as structured JSON/JSONL.")
    argp.add_argument("db_file", help="path to decoded_database.db")
    argp.add_argument("output", help="output file for --chat, or output directory for all chats")
    argp.add_argument("--chat", "-c", help="dump only this chat id / wxid / display name")
    argp.add_argument("--jsonl", action="store_true", help="write JSON Lines instead of one pretty JSON document")
    argp.add_argument("--include-raw", action="store_true", help="include original raw message content/XML")
    argp.add_argument("--overwrite", action="store_true", help="overwrite existing output file(s)")
    args = argp.parse_args()

    parser = WeChatDBParser(args.db_file)

    if args.chat:
        chatid = parser.get_chat_id(args.chat)
        if chatid not in parser.msgs_by_chat:
            sys.exit(f"No messages found for chat: {args.chat} ({chatid})")
        msgs = parser.msgs_by_chat[chatid]
        output = args.output
        if os.path.isdir(output):
            suffix = ".jsonl" if args.jsonl else ".json"
            output = os.path.join(output, safe_filename(parser.contacts.get(chatid, chatid)) + suffix)
        elif not output.lower().endswith((".json", ".jsonl")):
            output += ".jsonl" if args.jsonl else ".json"
        os.makedirs(os.path.dirname(os.path.abspath(output)) or ".", exist_ok=True)
        if os.path.exists(output) and not args.overwrite:
            sys.exit(f"Output exists, pass --overwrite to replace: {output}")
        if args.jsonl:
            write_jsonl(output, msgs, include_raw=args.include_raw)
        else:
            write_json(output, chat_to_obj(parser, chatid, msgs, include_raw=args.include_raw))
        logger.info("Wrote %s messages to %s", len(msgs), output)
        return 0

    out_dir = args.output
    os.makedirs(out_dir, exist_ok=True)
    if not os.path.isdir(out_dir):
        sys.exit(f"Error creating directory {out_dir}")

    for chatid, msgs in parser.msgs_by_chat.items():
        name = parser.contacts.get(chatid, chatid) or str(id(chatid))
        suffix = ".jsonl" if args.jsonl else ".json"
        output = os.path.join(out_dir, safe_filename(name) + suffix)
        if os.path.exists(output) and not args.overwrite:
            logger.info("File %s exists! Skip contact %s", output, name)
            continue
        if args.jsonl:
            write_jsonl(output, msgs, include_raw=args.include_raw)
        else:
            write_json(output, chat_to_obj(parser, chatid, msgs, include_raw=args.include_raw))
        logger.info("Wrote %s messages to %s", len(msgs), output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
