import os, json, asyncio, subprocess, pathlib, datetime, random
import requests
import edge_tts

GEMINI_KEY = os.environ["GEMINI_API_KEY"]
PEXELS_KEY = os.environ["PEXELS_API_KEY"]
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
NICHE = os.environ.get("NICHE", "মজার তথ্য, মোটিভেশন, প্রযুক্তি, বিস্ময়কর ফ্যাক্ট, জীবনের শিক্ষা")
VOICE = os.environ.get("VOICE", "bn-BD-NabanitaNeural")  # ছেলের কণ্ঠ: bn-BD-PradeepNeural
PRIVACY = os.environ.get("YT_PRIVACY", "private")  # প্রথমে private, পরে public করো

WORK = pathlib.Path("work")
WORK.mkdir(exist_ok=True)


def sh(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------- ১. আইডিয়া + স্ক্রিপ্ট ----------
def make_idea():
    today = datetime.date.today().isoformat()
    prompt = f"""আজকের তারিখ {today}। তুমি বাংলাদেশি দর্শকদের জন্য ভাইরাল শর্ট ভিডিওর কনটেন্ট ক্রিয়েটর।
বিষয়ের ক্ষেত্র: {NICHE}
এমন একটি নতুন ও আকর্ষণীয় ভিডিও আইডিয়া বাছাই করো যা মানুষ শেষ পর্যন্ত দেখবে।
শুধু JSON দাও, এই ফিল্ডগুলো সহ:
- title: বাংলা টাইটেল (সর্বোচ্চ ৬০ অক্ষর, কৌতূহল জাগানো)
- script: বাংলা ভয়েসওভার স্ক্রিপ্ট, ১০০-১২০ শব্দ। প্রথম লাইনে জোরালো হুক, শেষে ছোট CTA। শুধু যা পড়া হবে তাই লেখো, কোনো ব্র্যাকেট বা ইমোজি নয়।
- description: বাংলা ডেসক্রিপশন (২ লাইন)
- hashtags: ৫টি হ্যাশট্যাগের তালিকা
- keywords: ইংরেজিতে ৪টি আলাদা ভিজ্যুয়াল সার্চ শব্দ (স্টক ফুটেজ খোঁজার জন্য, যেমন "city night", "brain")"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}"
    r = requests.post(url, json={
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 1.0},
    }, timeout=120)
    r.raise_for_status()
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


# ---------- ২. ভয়েসওভার ----------
async def _tts(text, path):
    await edge_tts.Communicate(text, VOICE).save(path)


def make_voice(script):
    path = str(WORK / "voice.mp3")
    asyncio.run(_tts(script, path))
    return path


def duration(path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", path])
    return float(out.strip())


# ---------- ৩. স্টক ফুটেজ ----------
def fetch_clips(keywords):
    clips = []
    for i, kw in enumerate(keywords[:4]):
        r = requests.get("https://api.pexels.com/videos/search",
                         headers={"Authorization": PEXELS_KEY},
                         params={"query": kw, "orientation": "portrait", "per_page": 8}, timeout=60)
        vids = r.json().get("videos", [])
        if not vids:
            continue
        v = random.choice(vids)
        files = [f for f in v["video_files"] if f.get("height", 0) >= 720]
        files.sort(key=lambda f: f.get("height", 0))
        f = files[0] if files else v["video_files"][0]
        p = WORK / f"clip{i}.mp4"
        p.write_bytes(requests.get(f["link"], timeout=120).content)
        clips.append(p)
    if not clips:
        raise RuntimeError("কোনো ফুটেজ পাওয়া যায়নি")
    return clips


# ---------- ৪. ভিডিও জোড়া ----------
def build_video(clips, voice_path):
    total = duration(voice_path) + 0.5
    seg = total / len(clips)
    parts = []
    for i, c in enumerate(clips):
        out = WORK / f"part{i}.mp4"
        sh(["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(c), "-t", f"{seg:.2f}",
            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30",
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out)])
        parts.append(out)
    lst = WORK / "list.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts))
    joined = WORK / "joined.mp4"
    sh(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)])
    final = WORK / "final.mp4"
    sh(["ffmpeg", "-y", "-i", str(joined), "-i", voice_path, "-map", "0:v", "-map", "1:a",
        "-c:v", "copy", "-c:a", "aac", "-shortest", str(final)])
    return final


# ---------- ৫. আপলোড ----------
def upload_youtube(video, idea):
    need = ["YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"]
    if not all(os.environ.get(k) for k in need):
        print("YouTube সিক্রেট নেই, স্কিপ করা হলো")
        return
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    creds = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"],
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=os.environ["YT_CLIENT_ID"],
                        client_secret=os.environ["YT_CLIENT_SECRET"])
    yt = build("youtube", "v3", credentials=creds)
    tags = " ".join(idea.get("hashtags", []))
    body = {
        "snippet": {
            "title": (idea["title"] + " #Shorts")[:100],
            "description": f'{idea.get("description", "")}\n\n{tags} #Shorts',
            "categoryId": "22",
            "defaultLanguage": "bn",
        },
        "status": {"privacyStatus": PRIVACY, "selfDeclaredMadeForKids": False},
    }
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(video), resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    print("YouTube আপলোড হয়েছে:", resp["id"])


def upload_facebook(video, idea):
    page_id, token = os.environ.get("FB_PAGE_ID"), os.environ.get("FB_PAGE_TOKEN")
    if not (page_id and token):
        print("Facebook সিক্রেট নেই, স্কিপ করা হলো")
        return
    tags = " ".join(idea.get("hashtags", []))
    with open(video, "rb") as f:
        r = requests.post(f"https://graph-video.facebook.com/v21.0/{page_id}/videos",
                          data={"description": f'{idea["title"]}\n\n{idea.get("description", "")}\n{tags}',
                                "access_token": token},
                          files={"source": f}, timeout=600)
    print("Facebook:", r.status_code, r.text[:200])


if __name__ == "__main__":
    idea = make_idea()
    print("আইডিয়া:", idea["title"])
    voice = make_voice(idea["script"])
    clips = fetch_clips(idea["keywords"])
    video = build_video(clips, voice)
    for fn in (upload_youtube, upload_facebook):
        try:
            fn(video, idea)
        except Exception as e:
            print(fn.__name__, "ব্যর্থ:", e)
