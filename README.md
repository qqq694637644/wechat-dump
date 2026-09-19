## Render WeChat Messages from Android

## 安卓微信消息记录分析工具

WeChat, as the most popular mobile IM app in China, doesn't provide any methods to read its message history.
Customers are not able to analyze their own chat messages or interact with other data analysis tools.

We provide this tool that can parse WeChat messages from a rooted android phone.
This is necessary to provide interoperability between WeChat messages and other message analysis tools.
As examples, we provide sample scripts to obtain statistics of the message history and
render the messages into self-contained html files including voice messages, images, emojis, videos, etc.
Users can also write custom programs based on this tool to manage their chat messages.

The tool is last verified to work with latest version of WeChat on 2025/01/01.
If the tool works for you, please take a moment to add your phone/OS to [the wiki](https://github.com/ppwwyyxx/wechat-dump/wiki).

## How to use:

#### Dependencies:
+ adb and rooted android phone connected to Windows/macOS/Linux.
+ Python >= 3.8
+ sox (command line tools)
+ Silk audio decoder (included; build it with `./third-party/compile_silk.sh` on Unix, or place a compatible `decoder.exe` at `third-party/silk/decoder.exe` on Windows)
+ ffmpeg (optional; to decode WXGF images locally)
+ Other python dependencies: `pip install -r requirements.txt`.

#### Get Necessary Data:

1. Pull database file and (for older WeChat versions) avatar index:
  + Cross-platform automatic helper: `python android_interact.py db --out .`.
    On Windows you can also run `android-interact.cmd db --out .`.
    It may use an incorrect userid if multiple accounts exist; pass `--user <32-hex-dir>` to select one.
  + Legacy Unix helper: `./android-interact.sh db`.
  + Manual:
    + Figure out your `${userid}` by inspecting the contents of `/data/data/com.tencent.mm/MicroMsg` on the __root__ filesystem of the device.
      It should be a 32-character-long name consisting of hexadecimal digits.
    + Get `/data/data/com.tencent.mm/MicroMsg/${userid}/EnMicroMsg.db` from the device.
2. Decode `EnMicroMsg.db`. We do not provide instructions to do that.
3. Copy the unencrypted WeChat user resource directory `/data/data/com.tencent.mm/MicroMsg/${userid}/{avatar,emoji,image2,sfs,video,voice2}` from the phone to the `resource` directory:
	+ Cross-platform: `python android_interact.py res --out resource`
	+ Windows wrapper: `android-interact.cmd res --out resource`
	+ Legacy Unix helper: `./android-interact.sh res`
	+ Pass `--res-dir <remote path>` if the location of these directories is different on your phone.
      For older version of WeChat, the directory may be `/mnt/sdcard/tencent/MicroMsg/`
	  and the Python helper supports `--old-sdcard-layout`.
	+ This can take a while. It can be faster to first archive it with `tar` with or without compression, and then copy the archive,
	  `busybox tar` is recommended as the Android system's `tar` may choke on long paths. The Python helper does this on-device and extracts with Python, so no local bash/tar is required.
	+ In the end, we need a `resource` directory with the following subdir: `avatar,emoji,image2,sfs,video,voice2`.

#### Windows quick start without WSL:

```powershell
git clone https://github.com/qqq694637644/wechat-dump.git
cd wechat-dump
python -m pip install -r requirements.txt

# Pull encrypted DB/resources from rooted Android. adb must be in PATH.
python .\android_interact.py db --out .
python .\android_interact.py res --out resource

# Decrypt EnMicroMsg.db with your own SQLCipher/WCDB key workflow, then parse the decoded DB.
python .\list-chats.py C:\wechat-stage\decoded.db
python .\dump-msg.py C:\wechat-stage\decoded.db output_dir
python .\dump-html.py "<contact_display_name>" --db C:\wechat-stage\decoded.db --res resource --output output.html
python .\count_message.py output_dir
```

The project parses a decoded SQLite database. It does not decrypt `EnMicroMsg.db` by itself.

4. (Optional) Decode WXGF images:
   * If `ffmpeg`/`ffprobe` are available, WXGF images/emojis are decoded locally when possible.
   * Otherwise, you can install and start a WXGF decoder server on an android device and pass `--wxgf-server ws://xx.xx.xx.xx:xxxx`.
     See [WXGFDecoder](WXGFDecoder) for instructions.

5. (Optional) Download the emoji cache from [here](https://github.com/ppwwyyxx/wechat-dump/releases/download/0.1/emoji.cache.tar.bz2)
	and decompress it under `wechat-dump`. This will avoid downloading too many emojis during rendering.

        wget -c https://github.com/ppwwyyxx/wechat-dump/releases/download/0.1/emoji.cache.tar.bz2
        tar xf emoji.cache.tar.bz2

#### Run:
+ Parse and dump text messages of __every__ chat (requires decoded database):

    ```
    python dump-msg.py decoded.db output_dir
    ```

    To dump only one chat by WeChat id or display name:

    ```
    python dump-msg.py decoded.db output_dir --chat wxid_xxxxx --overwrite
    ```

+ List all chats (required decoded database):

    ```
    python list-chats.py decoded.db
    ```

+ Generate statistics report on text messages (requires `output_dir` from `./dump-msg.py`):

    ```
    python count_message.py output_dir
    ```

+ Dump messages of one contact to html, containing voice messages, emojis, and images (requires decoded database and `resource`):

    ```
    python dump-html.py "<contact_display_name>"
    ```

    * The output file is `output.html`. Check `./dump-html.py -h` to use different input/output paths.
    * Add `--wxgf-server ws://xx.xx.xx.xx:xxxx` to use a WXGF decoder server.

### Examples:
Screenshots of generated html:

![byvoid](https://github.com/ppwwyyxx/wechat-dump/raw/master/screenshots/byvoid.jpg)

See [here](http://ppwwyyxx.com/static/wechat/example.html) for an example html.

### TODO List (help needed!)
* After chat history migration, some emojis in the `EmojiInfo` table don't have corresponding URLs but only a md5 -
  they are not downloaded by WeChat until the message needs to be displayed. We don't know how to manually download these emojis.
* Verify/improve host-side WXGF decoding coverage.
* Fix rare unhandled message types: > 10000 and < 0
* Better user experiences... see `grep 'TODO' wechat -R`

### Donate!
<a href="https://www.paypal.com/cgi-bin/webscr?cmd=_donations&business=7BC299GRDLEDU&lc=US&item_name=wechat%2ddump&item_number=wechat%2ddump&currency_code=USD&bn=PP%2dDonationsBF%3abtn_donate_SM%2egif%3aNonHosted">
<img src="https://img.shields.io/badge/Paypal-Buy%20a%20Drink-blue.svg" alt="[paypal]" />
</a>
