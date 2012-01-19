#!/usr/bin/env python2.7
LICENSE = """\
Copyright (c) 2012 Ian Good <ian.good@rackspace.com>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import os
import sys
import subprocess
import base64
import zlib
import argparse

import dbus
import gobject
import pygtk
import gtk

_VERSION = '0.0'

# {{{ class State
class State(object):

    def __init__(self, args):
        self.icon = Icon(self, args)
        self.screensaver = XScreensaver(self, args)
        self.pidgin = Pidgin(self, args)

    def main(self):
        try:
            gtk.main()
        finally:
            self.screensaver.kill_watch_process()

    def on_status_changed(self, new):
        self.icon.set_status(new)

    def refresh_on_status(self, *args):
        self.screensaver.refresh_on_status()

    def got_blank_trigger(self):
        pass

    def got_unblank_trigger(self):
        if self.icon.get_away_on_lock():
            self.pidgin.remove_away()

    def got_lock_trigger(self):
        if self.icon.get_away_on_lock():
            self.pidgin.set_away()

    def icon_clicked(self):
        self.screensaver.toggle_on()

# }}}

# {{{ class Pidgin
class Pidgin(object):

    def __init__(self, state, args):
        self.state = state
        self.prev = None

    def _set_status(self, to_away):
        purple = self._get_purple()
        if not purple:
            return

        away = purple.PurpleSavedstatusGetIdleaway()
        current = purple.PurpleSavedstatusGetCurrent()

        if to_away:
            self.prev = current
            purple.PurpleSavedstatusActivate(away)
        else:
            purple.PurpleSavedstatusActivate(self.prev)
            self.prev = None

    def set_away(self):
        self._set_status(True)

    def remove_away(self):
        if self.prev:
            gobject.timeout_add(1000, self._set_status, False)

    def _get_purple(self):
        try:
            bus = dbus.SessionBus()
            dbus_obj = bus.get_object('im.pidgin.purple.PurpleService',
                                      '/im/pidgin/purple/PurpleObject')
            p = dbus.Interface(dbus_obj, 'im.pidgin.purple.PurpleInterface')
            return p
        except dbus.exceptions.DBusException:
            return None

# }}}

# {{{ class XScreensaver
class XScreensaver(object):

    def __init__(self, state, args):
        self.state = state

        self._toggling = False
        self._on_status_process = None
        self._watch_process = None
        self._start_watch()
        self.refresh_on_status()

    def kill_watch_process(self):
        try:
            self._watch_process.terminate()
        except OSError:
            pass

    def toggle_on(self):
        self._toggling = True
        self.refresh_on_status()

    def refresh_on_status(self):
        if self._on_status_process:
            return

        p = subprocess.Popen(['xscreensaver-command', '-version'],
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
        p.stdin.close()
        gobject.io_add_watch(p.stdout, gobject.IO_HUP, self._on_status_finished)
        self._on_status_process = p

    def _start_watch(self, *extras):
        if self._watch_process and not self._watch_process.poll():
            self._watch_process.wait()
        p = subprocess.Popen(['xscreensaver-command', '-watch'],
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE)
        p.stdin.close()
        self._watch_process = p
        gobject.io_add_watch(p.stdout, gobject.IO_IN, self._get_watch_data)
        gobject.io_add_watch(p.stdout, gobject.IO_HUP, self._start_watch)
        return False

    def _on_status_finished(self, f, cond):
        p = self._on_status_process
        if p:
            self._on_status_process = None
            p.wait()
            self.state.on_status_changed(p.returncode == 0)
            if self._toggling:
                self._toggling = False
                if p.returncode == 0:
                    self._turn_off()
                else:
                    self._turn_on()
        return False

    def _turn_on(self):
        devnull = open('/dev/null', 'w')
        p = subprocess.Popen(['xscreensaver', '-nosplash'],
                             stdin=subprocess.PIPE,
                             stdout=devnull, stderr=devnull)
        p.stdin.close()
        gobject.timeout_add(1000, self.refresh_on_status)

    def _turn_off(self):
        p = subprocess.Popen(['xscreensaver-command', '-exit'],
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
        p.communicate()
        gobject.timeout_add(500, self.refresh_on_status)

    def _get_watch_data(self, f, cond):
        line = f.readline()
        if line.startswith("BLANK"):
            self.state.got_blank_trigger()
        elif line.startswith("UNBLANK"):
            self.state.got_unblank_trigger()
        elif line.startswith("LOCK"):
            self.state.got_lock_trigger()
        return True

# }}}

# {{{ class Icon
class Icon(object):

    def __init__(self, state, args):
        self.state = state
        self.icon = None
        self.status = None
        self._away_on_lock = True
        self._load_icons(args)

    def _load_icons(self, args):
        if args.onicon:
            self._on_icon = gtk.gdk.pixbuf_new_from_file(args.onicon)
        else:
            self._on_icon = ON_ICON_PIXBUF

        if args.officon:
            self._off_icon = gtk.gdk.pixbuf_new_from_file(args.officon)
        else:
            self._off_icon = OFF_ICON_PIXBUF

    def _set_icon_pixbuf(self, icon):
        pixbuf = self._on_icon if self.status else self._off_icon
        icon.set_from_pixbuf(pixbuf)

    def _create_icon(self):
        self.icon = gtk.StatusIcon()
        self._set_icon_pixbuf(self.icon)
        self.icon.connect('popup-menu', self._right_click)
        self.icon.connect('activate', self._left_click)
        self.icon.set_tooltip("Screensaver Icon")

    def _change_away_on_lock(self, item):
        self._away_on_lock = item.get_active()

    def get_away_on_lock(self):
        return self._away_on_lock

    def set_status(self, status):
        self.status = status
        if not self.icon:
            self._create_icon()
        else:
            self._set_icon_pixbuf(self.icon)

    def _right_click(self, icon, button, timestamp):
        menu = gtk.Menu()

        if self.status:
            status = gtk.MenuItem("Running")
        else:
            status = gtk.MenuItem("Stopped")
        status.set_sensitive(False)

        aol = gtk.CheckMenuItem("Away On Lock")
        aol.set_active(self._away_on_lock)

        separator = gtk.SeparatorMenuItem()
        refresh = gtk.ImageMenuItem("Refresh")
        about = gtk.ImageMenuItem("About")
        quit = gtk.ImageMenuItem("Quit")

        img = gtk.image_new_from_stock(gtk.STOCK_REFRESH, gtk.ICON_SIZE_MENU)
        img.show()
        refresh.set_image(img)

        img = gtk.image_new_from_stock(gtk.STOCK_ABOUT, gtk.ICON_SIZE_MENU)
        img.show()
        about.set_image(img)

        img = gtk.image_new_from_stock(gtk.STOCK_QUIT, gtk.ICON_SIZE_MENU)
        img.show()
        quit.set_image(img)

        aol.connect("toggled", self._change_away_on_lock)
        refresh.connect("activate", self.state.refresh_on_status)
        about.connect("activate", self._show_about_dialog)
        quit.connect("activate", gtk.main_quit)

        menu.append(status)
        menu.append(gtk.SeparatorMenuItem())
        menu.append(aol)
        menu.append(refresh)
        menu.append(about)
        menu.append(gtk.SeparatorMenuItem())
        menu.append(quit)

        menu.show_all()

        menu.popup(None, None, gtk.status_icon_position_menu,
                               button, timestamp, icon)

    def _left_click(self, icon):
        self.state.icon_clicked()

    def _show_about_dialog(self, widget):
        about = gtk.AboutDialog()

        about.set_destroy_with_parent(True)
        about.set_name("Screensaver Icon")
        about.set_version(_VERSION)
        about.set_authors(["Ian Good <ian.good@rackspace.com>"])
        about.set_license(LICENSE)

        about.set_comments("""Provides a status-bar icon letting single-click \
enabling a disabling of the xscreensaver daemon. Also, pidgin sessions will be \
marked "Away" while the screensaver is engaged.""")

        about.run()
        about.destroy()

# }}}

# {{{ ON_ICON_PIXBUF
ON_ICON_PIXBUF = gtk.gdk.pixbuf_new_from_data(zlib.decompress(base64.b64decode(
'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'
'JmM6ps'
    )), gtk.gdk.COLORSPACE_RGB, True, 8, 48, 48, 192)
# }}}

# {{{ OFF_ICON_PIXBUF
OFF_ICON_PIXBUF = gtk.gdk.pixbuf_new_from_data(zlib.decompress(base64.b64decode(
'eNrtmc2u20QUx2kvFFragiiCBQ8Au1YgHgCpG3YgHgCJF2DVTdnyJCzvjb/jr8R24uRGvAcPQEtV2k'
'a3lfmf+fLM2E6ccq/aSl385MSe8fzO8fFM7DRN807zlre85Y2lqsr7ZVVuQcMoC0UhKYi5Yi6Z9zFT'
'zCSznJHr5H1kikySpYqUb7fY3pf+5H56etqMYbPhjG1/erpu1sRasmpWqz7qpibqJWO5tFkoFouqSd'
'N02/oXbKyl3q/m1LU4L+gfdyXG5ch+feMvJAvuUEkqHVEDDO36C2g/nQv+jfIvuf/JxH0joHwM+Tuu'
'vwevl4nT4nqBgaPg59DbErTP88MBAoM+/2KkP/U344CLEYfPHL2Aj2vHQdjuBHcbdmaIc5Ij3R9pmh'
'zsPwYaPwinjR9E7LPuHkaxyL/Proe8NvtzH2K+mrMt969N/8L0p3bDjsHwZ7iQd4X7k/tHcAwF/PiE'
'XTMOjZPlM9yTVZOk2WAMroiBzkGONFeZ/nPNX9SqG7SfPWvfEMLfR/49mX+f+3N3HX4NqB25y3lK9p'
'O4Osp/hT62/5r7e6azp/nYxzqxifaezD2Dj931D9hxakd1NcO6R17LZW06G/5h65+Y/rS2dP1Dls/N'
'ZsO2jshjP6HycXuYkL/E5e1lW4o3xdpL8zrVQZrlRuzSfch/vsOf5T+Q+Q8HYsA9ixxSmz53vc9EbO'
'02cZqztWyzoTVxbRxT5xX+tIYnSWz4r7CP+4cdWoddiHGCIX+zbdc/Y+sv+a9xDeR+yh3PzZR95/5r'
'01/U3pC/HNMen+8T+MLdisFoo+XDJtHyTzUURgnLRxDGrH5pq/xxr8Y7/aMOFL/+meckVvuYB+VI4n'
'M65+pxp/OkmEdp/tls1tx/mqpjfhir8cmRjg/7RzshJ1/kxGc54edt3Xlc9Nnp8ZdxqfgAuc7mBZvX'
'6bct1Y/jm/HK/so/3uHva1i5o/HanMTc0efeLtuf4NqkbNvxt7zluZJspmqf/On+7Yy903/GYmf+og'
'7aHLbeOq7m7vixyju5s2uDrWO0mYrvLdRnmuR4Dioxfls7aT7/H/7cPZ8VRn53InLP8g9visFj+Tdj'
'1P3pOM2Zs3nJfo/J3C/rlXnul/Bva9j2j3txgy5GG3yP4pxBsdGWcjwvKzz7LNWcw9y1Mfn80MYwGf'
'CfWf67XDsEPQy0Je+iomcwPNfhfqN1iO7VFeZzXjNxe808Hdt/3fGvDf/9vm6QaM6JRTyMFgvRPw73'
'nhi0/rR+xfG09Z/lmv/+HHtByurcC1PD24vSnlgG2HNdJ0RPDPL3wyj/3hxyz2qxZFs30J3tzxxqQ7'
'GabbW4KQ+2O/PnOFos8vfb1PavLX/Ks5wDrTqh8TyV//24aJfmBds6AzE4ftIbA6u1JFcxKP9p65/b'
'/j05t3GDce7cP2Pubm+8uv9wDPxajPTvraG+Ok7Pgd35n2jupn/U+ufC3znwXYwzkvN8/+Pw59+o4y'
'/f0ZnvzeT7PPkebqVYvQS19p6Qvytc7nhXqL+rW2jv6qiv5b9tXWvLdXXB2DHVWs44lN8oitiW4qW4'
'4L/V/O+Bx+CMkykySZYqUkmqeA5etCSKRJJIYkbMOcM6OsCUgXnyjNzpfRtt4X2G2n8M7p3X+3ec9w'
'l4fiDPwO3X4f8DeDyl3yOHgD4PwZ3XxT/T/ncYA+rgtfFHnT5l/7sU40HtP0S/V+6P++oy7vlnbP7C'
'HNKdC+35mP/HgTXzIa7Dt6/CuSiKW2VZflNWxS9VVf6JuflfemYk9v//xNshji36/lVW5a9lWdzG+W'
'6cl9/x8fElcBkcgXfBe+AacvYbntX+Rq1sUQOPEMdjWk/kuqevNbuQ14L6FmXxBOd7xM45nz/AGL9j'
'rOvgfTH2kXC5dID7keh/DdwAn4OvUbMPqM5P2TPTalS97K+nJVvH2PMjvtMacXJy8h3G+wLcBB+CD0'
'Qsl0b4Xxb5vgo+Ap+CL8FPnuf9EUbhP5g3XlwM4RM/8GuM9TO4DW6Bj0UMV8jtgPxfETFQ30/AV+Au'
'+IFiuSB+BN+DO+AzUUdXRS0cja2hnntA1tN1kY+L5KZWL6r2D3F/k/gPRgc8EA=='
    )), gtk.gdk.COLORSPACE_RGB, True, 8, 48, 48, 192)
# }}}

# {{{ _parse_args()
def _parse_args():
    parser = argparse.ArgumentParser(description='Adds a GTK status-bar icon allowing one-click control of the screensaver.')
    parser.add_argument('-v', '--version', action='version', version='%(prog)s '+_VERSION)
    parser.add_argument('-f', '--foreground', action='store_true', dest='foreground',
                        help='Run in the foreground, do not daemonize.')
    parser.add_argument('--on-icon', dest='onicon', metavar='FILE',
                        help='Use FILE icon indicating screensaver is on and activated.')
    parser.add_argument('--off-icon', dest='officon', metavar='FILE',
                        help='Use FILE icon indicating screensaver is off and disabled.')
    return parser.parse_args()
# }}}

# {{{ _daemonize()
# Daemonize the current process.
def _daemonize():

    # Fork once.
    try:
        pid = os.fork()
        if pid > 0:
            os._exit(0)
    except OSError:
        return

    # Set some options to detach from the terminal.
    os.chdir('/')
    os.setsid()
    os.umask(0)

    # Fork again.
    try:
        pid = os.fork()
        if pid > 0:
            os._exit(0)
    except OSError:
        return

    # Find the OS /dev/null equivalent.
    nullfile = getattr(os, 'devnull', '/dev/null')

    # Redirect all standard I/O to /dev/null.
    sys.stdout.flush()
    sys.stderr.flush()
    si = file(nullfile, 'r')
    so = file(nullfile, 'a+')
    se = file(nullfile, 'a+', 0)
    os.dup2(si.fileno(), sys.stdin.fileno())
    os.dup2(so.fileno(), sys.stdout.fileno())
    os.dup2(se.fileno(), sys.stderr.fileno())
# }}}

if __name__ == '__main__':
    args = _parse_args()

    state = State(args)
    if not args.foreground:
        _daemonize()

    state.main()

# vim:et:fdm=marker:sts=4:sw=4:ts=4
