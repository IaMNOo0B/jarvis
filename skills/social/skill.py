"""Social reading — YouTube (transcripts!), Instagram, X, Snapchat.

APIs verified against the actual packages (Oct 2026):
- youtube-transcript-api 1.2.4: YouTubeTranscriptApi().fetch(video_id)
- yt-dlp: metadata + subtitle/audio fallback
- instaloader 4.15.4: session-file login
- twifork 2.4.0 (imports as twikit): password login is DEAD (X retired the
  flow) — cookies file only
- snapchat-dlp 1.5.13: public stories only

Lazy imports throughout (project convention). Auth lives in
secrets.local.yaml / the user data dir — never in code.
"""

import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SKILL_NAME = "social"
SKILL_DESCRIPTION = ("Read social platforms: YouTube video transcripts and "
                     "info, Instagram profiles/posts, X search and timelines, "
                     "Snapchat public stories.")

_YT_ID = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/|v/)|youtu\.be/)"
    r"([A-Za-z0-9_-]{11})")


def _video_id(url_or_id: str) -> str | None:
    s = (url_or_id or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", s):
        return s
    m = _YT_ID.search(s)
    return m.group(1) if m else None


def _user_file(name: str) -> str:
    from paths import user_file
    return user_file(name)


def _secrets() -> dict:
    try:
        import yaml
        with open(_user_file("secrets.local.yaml"), encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


# ------------------------------------------------------------- YouTube
def _youtube_transcript(args):
    vid = _video_id(str(args.get("url_or_id", "")))
    if not vid:
        return "Give me a YouTube link or video ID, sir."
    # Tier 1: caption API (fast, no download)
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        try:
            ft = api.fetch(vid, languages=["en"])
        except Exception:
            ft = api.fetch(vid)  # whatever language exists
        text = " ".join(s.text.strip() for s in ft.snippets)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            return _cap(f"[YouTube transcript — {vid}]\n{text}")
    except Exception as e:
        tier1_err = str(e)[:120]
    else:
        tier1_err = "no captions"
    # Tier 2: yt-dlp subtitles
    try:
        text = _ytdlp_subs(vid)
        if text:
            return _cap(f"[YouTube transcript via subtitles — {vid}]\n{text}")
    except Exception:
        pass
    # Tier 3: download audio, transcribe with our own whisper
    try:
        text = _whisper_transcribe(vid)
        if text:
            return _cap(f"[YouTube transcript via audio — {vid}]\n{text}")
    except Exception as e:
        return (f"Couldn't get a transcript for that video, sir "
                f"(captions: {tier1_err}; audio fallback also failed: "
                f"{str(e)[:120]}).")
    return f"No transcript available for that video, sir (tried captions, subtitles, audio)."


def _ytdlp_subs(vid: str) -> str | None:
    from yt_dlp import YoutubeDL
    tmp = tempfile.mkdtemp(prefix="jarvis_subs_")
    try:
        with YoutubeDL({"writesubtitles": True, "writeautomaticsub": True,
                        "subtitleslangs": ["en.*", "en"],
                        "subtitlesformat": "vtt", "skip_download": True,
                        "outtmpl": os.path.join(tmp, "%(id)s"),
                        "quiet": True, "no_warnings": True}) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={vid}"])
        for f in os.listdir(tmp):
            if f.endswith(".vtt"):
                return _parse_vtt(os.path.join(tmp, f))
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return None


def _parse_vtt(path: str) -> str | None:
    lines = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("WEBVTT") or "-->" in line \
                    or line.startswith("NOTE") or line[0].isdigit() and ":" in line[:9]:
                continue
            line = re.sub(r"<[^>]+>", "", line)
            if not lines or lines[-1] != line:
                lines.append(line)
    text = re.sub(r"\s+", " ", " ".join(lines)).strip()
    return text or None


def _whisper_transcribe(vid: str) -> str | None:
    from yt_dlp import YoutubeDL
    tmp = tempfile.mkdtemp(prefix="jarvis_audio_")
    audio = os.path.join(tmp, "audio.m4a")
    try:
        with YoutubeDL({"format": "bestaudio", "outtmpl": audio,
                        "quiet": True, "no_warnings": True}) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={vid}"])
        if not os.path.isfile(audio):
            got = os.listdir(tmp)
            audio = os.path.join(tmp, got[0]) if got else None
            if not audio:
                return None
        from faster_whisper import WhisperModel
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(audio)
        text = re.sub(r"\s+", " ", " ".join(s.text for s in segments)).strip()
        return text or None
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _youtube_info(args):
    vid = _video_id(str(args.get("url_or_id", "")))
    if not vid:
        return "Give me a YouTube link or video ID, sir."
    try:
        from yt_dlp import YoutubeDL
        with YoutubeDL({"quiet": True, "no_warnings": True,
                        "skip_download": True}) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={vid}", download=False)
        dur = info.get("duration") or 0
        return (f"{info.get('title')}\nChannel: {info.get('channel')} | "
                f"Duration: {dur // 60}:{dur % 60:02d} | "
                f"Views: {info.get('view_count')} | "
                f"Uploaded: {info.get('upload_date')}\n"
                f"{(info.get('description') or '')[:400]}")
    except Exception as e:
        return f"Couldn't read that video, sir: {str(e)[:150]}"


def _cap(text: str, limit: int = 9000) -> str:
    if len(text) > limit:
        return text[:limit] + "\n…[transcript truncated]"
    return text


# ------------------------------------------------------------- Instagram
def _ig_client():
    import instaloader
    L = instaloader.Instaloader(
        download_pictures=False, download_videos=False,
        download_video_thumbnails=False, download_geotags=False,
        download_comments=False, save_metadata=False,
        quiet=True)
    secrets = _secrets()
    user = (secrets.get("instagram_username") or "").strip()
    pw = secrets.get("instagram_password") or ""
    sess = _user_file("instagram.session")
    try:
        if user and pw:
            L.login(user, pw)
            L.save_session_to_file(sess)
        elif user and os.path.isfile(sess):
            L.load_session_from_file(user, sess)
    except Exception:
        pass  # fall through to anonymous; may be rate-limited
    return L


def _instagram_profile(args):
    username = str(args.get("username", "")).strip().lstrip("@")
    if not username:
        return "Whose Instagram, sir?"
    try:
        import instaloader
        L = _ig_client()
        p = instaloader.Profile.from_username(L.context, username)
        posts = []
        for post in p.get_posts():
            posts.append(
                f"— {post.date_local:%Y-%m-%d}: {post.caption[:120] if post.caption else ''} "
                f"({post.likes} likes)")
            if len(posts) >= 5:
                break
        recent = "\n".join(posts) if posts else "no recent posts visible"
        return (f"@{p.username} — {p.full_name}\n"
                f"Followers: {p.followers} | Following: {p.followees} | "
                f"Posts: {p.mediacount}\nBio: {(p.biography or '')[:300]}\n"
                f"Recent:\n{recent}")
    except Exception as e:
        msg = str(e)
        if "401" in msg or "login" in msg.lower():
            return ("Instagram wants a login, sir — add your username and "
                    "password in Settings → API Keys, then ask again.")
        return f"Couldn't read @{username}, sir: {msg[:150]}"


def _instagram_post(args):
    url = str(args.get("url", "")).strip()
    m = re.search(r"instagram\.com/(?:p|reel|reels)/([A-Za-z0-9_-]+)", url)
    if not m:
        return "Give me an Instagram post or reel link, sir."
    try:
        import instaloader
        L = _ig_client()
        post = instaloader.Post.from_shortcode(L.context, m.group(1))
        return (f"@{post.owner_username} — {post.date_local:%Y-%m-%d}\n"
                f"Likes: {post.likes} | Comments: {post.comments}\n"
                f"{(post.caption or '')[:1500]}")
    except Exception as e:
        return f"Couldn't read that post, sir: {str(e)[:150]}"


# ------------------------------------------------------------------- X
_X_COOKIE_HELP = ("X needs your login cookies, sir — one-time setup: while "
                  "logged in to x.com in your browser, export cookies with an "
                  "extension like 'Get cookies.txt LOCALLY', save the JSON as "
                  "x_cookies.json in your JARVIS data folder, then ask again.")


def _x_client():
    # Cookies first (cheap, no import) so a missing setup gives the
    # helpful message instead of an import error.
    cookies = _user_file("x_cookies.json")
    if not os.path.isfile(cookies):
        return None
    from twikit import Client  # twifork ships under the twikit import name
    import asyncio

    async def _build():
        c = Client("en-US")
        c.load_cookies(cookies)
        return c

    # normalize browser-export format [{name,value,domain}...] → {name: value}
    try:
        import json
        with open(cookies, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            d = {c["name"]: c["value"] for c in data
                 if isinstance(c, dict) and "x.com" in str(c.get("domain", ""))}
            with open(cookies, "w", encoding="utf-8") as f:
                json.dump(d, f)
    except Exception:
        pass
    try:
        return asyncio.run(_build())
    except Exception as e:
        raise RuntimeError(str(e))


def _fmt_tweets(tweets, limit=8):
    lines = []
    for t in tweets[:limit]:
        user = getattr(getattr(t, "user", None), "screen_name", "?")
        text = re.sub(r"\s+", " ", getattr(t, "text", "") or "")[:280]
        lines.append(f"@{user}: {text}")
    return "\n".join(lines) if lines else "nothing found"


def _x_search(args):
    q = str(args.get("query", "")).strip()
    if not q:
        return "What should I search X for, sir?"
    try:
        import asyncio
        c = _x_client()
        if c is None:
            return _X_COOKIE_HELP

        async def _go():
            return await c.search_tweet(q, "Latest", count=15)
        return f"Latest on X for '{q}', sir:\n" + _fmt_tweets(asyncio.run(_go()))
    except Exception as e:
        return (f"X didn't cooperate, sir: {str(e)[:150]} "
                f"(the free route breaks whenever X rotates things).")


def _x_user_tweets(args):
    username = str(args.get("username", "")).strip().lstrip("@")
    if not username:
        return "Whose X timeline, sir?"
    try:
        import asyncio
        c = _x_client()
        if c is None:
            return _X_COOKIE_HELP

        async def _go():
            u = await c.get_user_by_screen_name(username)
            return await u.get_tweets("Tweets", count=10)
        return f"@{username} on X, sir:\n" + _fmt_tweets(asyncio.run(_go()))
    except Exception as e:
        return f"Couldn't read @{username} on X, sir: {str(e)[:150]}"


# -------------------------------------------------------------- Snapchat
def _snapchat_story(args):
    username = str(args.get("username", "")).strip().lstrip("@")
    if not username:
        return "Whose Snapchat story, sir?"
    try:
        from snapchat_dlp import SnapchatDL
        tmp = tempfile.mkdtemp(prefix="jarvis_snap_")
        dl = SnapchatDL(directory_prefix=tmp, limit_story=10,
                       dump_json=True, quiet=True)
        ok = dl.download(username)
        files = []
        for root, _, fs in os.walk(tmp):
            files.extend(f for f in fs if not f.endswith(".json"))
        if not ok or not files:
            return (f"No public story found for @{username}, sir. "
                    f"(Only public stories are readable — DMs and private "
                    f"stories aren't accessible to anyone's code.)")
        return (f"@{username}'s public story, sir — {len(files)} item(s), "
                f"saved to {tmp}:\n" + "\n".join(files[:10]))
    except Exception as e:
        return f"Couldn't fetch that story, sir: {str(e)[:150]}"


# ------------------------------------------------------------------ contract
TOOL_DEFINITIONS = [
    {"type": "function", "function": {
        "name": "youtube_transcript",
        "description": ("Read a YouTube video's transcript/captions from its "
                        "URL. Falls back to subtitles, then audio "
                        "transcription. This is how you 'watch' videos."),
        "parameters": {"type": "object",
                       "properties": {"url_or_id": {"type": "string"}},
                       "required": ["url_or_id"]}}},
    {"type": "function", "function": {
        "name": "youtube_info",
        "description": "Get a YouTube video's title, channel, duration, views, upload date.",
        "parameters": {"type": "object",
                       "properties": {"url_or_id": {"type": "string"}},
                       "required": ["url_or_id"]}}},
    {"type": "function", "function": {
        "name": "instagram_profile",
        "description": "Read an Instagram profile: bio, follower counts, recent posts.",
        "parameters": {"type": "object",
                       "properties": {"username": {"type": "string"}},
                       "required": ["username"]}}},
    {"type": "function", "function": {
        "name": "instagram_post",
        "description": "Read an Instagram post or reel from its URL: caption, likes, comments.",
        "parameters": {"type": "object",
                       "properties": {"url": {"type": "string"}},
                       "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "x_search",
        "description": ("Search X/Twitter for the latest posts on a topic. "
                        "Needs the one-time cookie setup."),
        "parameters": {"type": "object",
                       "properties": {"query": {"type": "string"}},
                       "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "x_user_tweets",
        "description": ("Read someone's recent X/Twitter timeline. "
                        "Needs the one-time cookie setup."),
        "parameters": {"type": "object",
                       "properties": {"username": {"type": "string"}},
                       "required": ["username"]}}},
    {"type": "function", "function": {
        "name": "snapchat_story",
        "description": ("Fetch someone's PUBLIC Snapchat story "
                        "(public stories only — DMs and private stories are "
                        "not accessible)."),
        "parameters": {"type": "object",
                       "properties": {"username": {"type": "string"}},
                       "required": ["username"]}}},
]


def handle(tool_name, args, services=None):
    args = args or {}
    try:
        fn = {"youtube_transcript": _youtube_transcript,
              "youtube_info": _youtube_info,
              "instagram_profile": _instagram_profile,
              "instagram_post": _instagram_post,
              "x_search": _x_search,
              "x_user_tweets": _x_user_tweets,
              "snapchat_story": _snapchat_story}.get(tool_name)
        if fn is None:
            return None
        return fn(args)
    except Exception as e:
        return f"Sorry, sir — that hit a snag: {e}"
