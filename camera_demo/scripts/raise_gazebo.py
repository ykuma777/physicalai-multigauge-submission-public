#!/usr/bin/env python3
"""Bring only the task's existing Gazebo GUI window to the VNC foreground."""
import ctypes
import os
import re
import subprocess

os.environ.setdefault('DISPLAY', ':0')
os.environ.setdefault('XAUTHORITY', '/home/ubuntu/.Xauthority')
tree = subprocess.check_output(['xwininfo', '-root', '-tree'], text=True)
matches = re.findall(r'(0x[0-9a-f]+) "Gazebo": \("ign-gazebo-gui" "Gazebo GUI"\)', tree)
if len(matches) != 1:
    raise RuntimeError(f'expected exactly one Gazebo GUI; found {len(matches)}')
lib = ctypes.CDLL('libX11.so.6')
lib.XOpenDisplay.restype = ctypes.c_void_p
lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
display = lib.XOpenDisplay(os.environ['DISPLAY'].encode())
if not display:
    raise RuntimeError('cannot open X display')
window = int(matches[0], 16)
lib.XRaiseWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
lib.XRaiseWindow(display, window)
lib.XDefaultRootWindow.restype = ctypes.c_ulong
lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
root = lib.XDefaultRootWindow(display)
lib.XInternAtom.restype = ctypes.c_ulong
lib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
atom = lib.XInternAtom(display, b'_NET_ACTIVE_WINDOW', 0)

class ClientMessage(ctypes.Structure):
    _fields_ = [('type', ctypes.c_int), ('serial', ctypes.c_ulong),
                ('send_event', ctypes.c_int), ('display', ctypes.c_void_p),
                ('window', ctypes.c_ulong), ('message_type', ctypes.c_ulong),
                ('format', ctypes.c_int), ('data', ctypes.c_long * 5)]

message = ClientMessage(33, 0, 1, display, window, atom, 32, (ctypes.c_long * 5)(2, 0, 0, 0, 0))
lib.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
                           ctypes.c_long, ctypes.c_void_p]
lib.XSendEvent(display, root, 0, (1 << 19) | (1 << 20), ctypes.byref(message))
lib.XFlush.argtypes = [ctypes.c_void_p]
lib.XFlush(display)
lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
lib.XCloseDisplay(display)
print(f'raised Gazebo GUI window {matches[0]}')
