# Sum the memory of a browser and all of its child processes.
#
#   python mem_tree.py <root-pid> [<root-pid> ...]
#
# No.VI: the root is the `novi_browser.py _serve` worker of the profile (it owns
# the driver and Chrome). Ego Lite: the root is the ego.exe process without --type.
# Prints {pid: [process count, private MB, working set MB]}.
import json, sys
import psutil

def tree(pid):
    p = psutil.Process(pid)
    procs = [p] + p.children(recursive=True)
    private = ws = 0
    for q in procs:
        try:
            m = q.memory_info()
            private += m.private
            ws += m.rss
        except psutil.Error:
            pass
    return len(procs), private >> 20, ws >> 20

print(json.dumps({a: tree(int(a)) for a in sys.argv[1:]}))
