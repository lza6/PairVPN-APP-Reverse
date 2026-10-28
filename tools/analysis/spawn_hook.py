import sys, time, json, threading
import frida

SCRIPT = open("hook_net.js", "r", encoding="utf-8").read()
LOG = open("frida_net.log", "w", encoding="utf-8", buffering=1)

def out(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    LOG.write(line + "\n")

def on_message(msg, data):
    if msg.get("type") == "send":
        out("[JS]", msg.get("payload"))
    elif msg.get("type") == "error":
        out("[JS-ERR]", msg.get("stack") or msg.get("description"))

dev = frida.get_usb_device(timeout=10)
out("device:", dev)
pid = dev.spawn(["com.pairvpn"])
out("spawned pid", pid)
session = dev.attach(pid)
script = session.create_script(SCRIPT)
script.on("message", on_message)
script.load()
dev.resume(pid)
out("resumed, hooks active")
while True:
    time.sleep(1)
