#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import logging
from wechat.parser import WeChatDBParser
from wechat.common.textutil import safe_filename
import argparse
import os
import sys

logger = logging.getLogger("wechat")

if __name__ == '__main__':
    argp = argparse.ArgumentParser(description='Dump WeChat text messages to UTF-8 .txt files.')
    argp.add_argument('db_file', help='path to decoded_database.db')
    argp.add_argument('output_dir', help='directory to write .txt files')
    argp.add_argument('--chat', '-c', help='dump only this chat id / wxid / display name')
    argp.add_argument('--overwrite', action='store_true', help='overwrite existing output file(s)')
    argp.add_argument('--encoding', default='utf-8', help='text output encoding, default: utf-8')
    args = argp.parse_args()

    db_file = args.db_file
    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)
    if not os.path.isdir(output_dir):
        sys.exit("Error creating directory {}".format(output_dir))

    parser = WeChatDBParser(db_file)

    if args.chat:
        chatid = parser.get_chat_id(args.chat)
        if chatid not in parser.msgs_by_chat:
            sys.exit(f"No messages found for chat: {args.chat} ({chatid})")
        chat_items = [(chatid, parser.msgs_by_chat[chatid])]
    else:
        chat_items = parser.msgs_by_chat.items()

    for chatid, msgs in chat_items:
        name = parser.contacts[chatid]
        if len(name) == 0:
            logger.info(f"Chat {chatid} doesn't have a valid display name.")
            name = str(id(chatid))
        logger.info(f"Writing msgs for {name}")
        safe_name = safe_filename(name)
        outf = os.path.join(output_dir, safe_name + '.txt')
        if os.path.isfile(outf) and not args.overwrite:
            logger.info(f"File {outf} exists! Skip contact {name}")
            continue
        with open(outf, 'w', encoding=args.encoding, errors='replace', newline='\n') as f:
            for m in msgs:
                f.write(str(m))
                f.write("\n")
        logger.info(f"Wrote {len(msgs)} messages to {outf}")
