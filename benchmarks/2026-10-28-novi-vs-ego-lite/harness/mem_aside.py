"""Measure an isolated Aside instance (own temp user-data-dir, never the Owner's profiles)."""
import subprocess, time, json, sys, tempfile, urllib.request, urllib.parse, psutil, shutil

EXE = r"C:\Program Files\Aside\Application\Aside.exe"
PAGES = ["https://en.wikipedia.org/wiki/Web_browser", "https://www.bbc.com/news", "https://github.com/explore"]


def tree(pid):
    try:
        p = psutil.Process(pid)
        ps = [p] + p.children(recursive=True)
    except psutil.Error:
        return 0, 0
    pv = 0
    for q in ps:
        try:
            pv += q.memory_info().private
        except psutil.Error:
            pass
    return len(ps), pv >> 20


def cdp(port, path, method="GET"):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method)
    return json.loads(urllib.request.urlopen(req, timeout=5).read())


def run(headless, port):
    d = tempfile.mkdtemp(prefix="asidemem_")
    args = [EXE, f"--user-data-dir={d}", f"--remote-debugging-port={port}",
            "--no-first-run", "--no-default-browser-check"]
    if headless:
        args.append("--headless=new")
    args.append("https://en.wikipedia.org/wiki/Web_browser")
    pr = subprocess.Popen(args)
    out = {"headless": headless}
    for _ in range(30):
        try:
            out["version"] = cdp(port, "/json/version").get("Browser")
            break
        except Exception:
            time.sleep(1)
    else:
        out["error"] = "no CDP"
        out["alive"] = pr.poll() is None
        out["tree"] = tree(pr.pid)
        pr.kill()
        return out
    time.sleep(3)
    first = [t for t in cdp(port, "/json/list") if t.get("type") == "page"]
    for i, u in enumerate(PAGES, start=1):
        cdp(port, "/json/new?" + urllib.parse.quote(u, safe=":/"), "PUT")
        if i == 1:
            for t in first:
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/json/close/{t['id']}", timeout=5)
                except Exception:
                    pass
        time.sleep(15)
        out[f"pages_{i}"] = tree(pr.pid)
    out["titles"] = [t["title"][:40] for t in cdp(port, "/json/list") if t.get("type") == "page"]
    try:
        for c in psutil.Process(pr.pid).children(recursive=True):
            c.kill()
    except psutil.Error:
        pass
    pr.kill()
    time.sleep(2)
    shutil.rmtree(d, ignore_errors=True)
    return out


print(json.dumps(run(sys.argv[1] == "headless", int(sys.argv[2])), ensure_ascii=False))
