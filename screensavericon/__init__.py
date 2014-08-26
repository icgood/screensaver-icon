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

_VERSION = '1.2'

# {{{ class State
class State(object):

    def __init__(self, args):
        self.icon = Icon(self, args)
        self.screensaver = XScreensaver(self, args)
        self.pidgin = Pidgin(self, args)

    def main(self):
        gobject.timeout_add(2500, self.screensaver.refresh_on_status)
        try:
            gtk.main()
        finally:
            self.screensaver.kill_watch_process()

    def on_status_changed(self, new):
        self.icon.set_status(new)

    def refresh_on_status(self, *args):
        self.screensaver.refresh_on_status()

    def got_blank_trigger(self):
        if self.icon.get_away_on_lock():
            self.pidgin.set_away()

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
        def load_default(name):
            from pkg_resources import Requirement, resource_filename
            resource_name = 'icons/{0}.png'.format(name)
            fn = resource_filename(__name__, resource_name)
            return gtk.gdk.pixbuf_new_from_file(fn)

        if args.onicon:
            self._on_icon = gtk.gdk.pixbuf_new_from_file(args.onicon)
        else:
            self._on_icon = load_default('on')

        if args.officon:
            self._off_icon = gtk.gdk.pixbuf_new_from_file(args.officon)
        else:
            self._off_icon = load_default('off')

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

def main():
    args = _parse_args()

    state = State(args)
    if not args.foreground:
        _daemonize()

    state.main()

if __name__ == '__main__':
    main()

# vim:et:fdm=marker:sts=4:sw=4:ts=4
