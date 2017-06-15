#!/usr/bin/env nix-shell
# coding=utf-8
#! nix-shell -i python -p pythonPackages.attrs pythonPackages.urwid pythonPackages.twisted pythonPackages.treq

from __future__ import division

import math
import time
import urllib

import attr

from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks
from twisted.internet.task import LoopingCall
import treq

import urwid

def lerp(x, y, t):
    return y * t + x * (1 - t)

def pickEdge(l, c, r):
    "Choose an edge character which looks good."

    if l == c == r:
        return '-'
    elif l > c and r > c:
        return '^'
    elif l < c and r < c:
        return 'v'
    elif l > r:
        return '/'
    elif l < r:
        return '\\'

@attr.s
class PromWidget(urwid.Widget):
    _sizing = frozenset(["box"])

    points = attr.ib()

    def lerpPoints(self, maxcol):
        ps = self.points
        l = len(ps) - 1
        scale = l / maxcol
        rv = []
        for i in range(maxcol):
            t, fpos = math.modf(i * scale)
            pos = int(fpos)
            rv.append(lerp(ps[pos], ps[pos + 1], t))
        return rv

    def fixPoints(self, ps, maxrow):
        bottom = min(ps)
        top = max(ps)
        # Our projection will prevent points from occurring in the first or
        # last row, for aethetics. We borrow both rows here, and then put one
        # back when doing the offset fixup.
        scale = (maxrow - 2) / (top - bottom)
        rv = []
        for p in ps:
            p *= scale
            fixed = maxrow - int(p) - 1
            rv.append(fixed)
        return rv

    def selectable(self):
        return False

    def render(self, size, focus=False):
        maxcol, maxrow = size
        # Fill out the points to full rank, times two, in order to get better
        # inter-character edges.. Add a fencepost.
        fullPoints = self.lerpPoints(maxcol * 2 + 1)
        # Fix them on the right rows.
        absPoints = self.fixPoints(fullPoints, maxrow)
        # Do the draw, per-column.
        cols = []
        for i in range(maxcol):
            left = absPoints[i * 2]
            center = absPoints[i * 2 + 1]
            right = absPoints[i * 2 + 2]
            # Pick the edge, center the "cursor", and "draw" the column.
            edge = pickEdge(left, center, right)
            p = (left + center + right) // 3
            s = ' ' * p + edge + ':' * (maxrow - p - 1)
            cols.append(s)
        # Transpose.
        rows = ["".join(rs) for rs in zip(*cols)]
        canvas = urwid.TextCanvas(rows, maxcol=maxcol)
        return canvas

@attr.s
class Prom(object):
    loop = attr.ib()
    status = attr.ib()
    frame = attr.ib()

    @classmethod
    def new(cls, loop, widget):
        status = u"No status reported yet!"
        center = urwid.AttrMap(widget, "graph")
        header = urwid.Text(u"PromQueen ♛")
        frame = urwid.Frame(center, header=header)
        self = cls(loop=loop, status=status, frame=frame)
        return self

    def changeStatus(self, newStatus):
        self.status = newStatus
        self.frame.contents["footer"] = (urwid.Text(self.status),
                                         self.frame.options())
        self.draw()

    def changePoints(self, newPoints):
        graph = PromWidget(newPoints)
        graph = urwid.AttrMap(graph, "graph")
        self.frame.contents["body"] = (graph, self.frame.options())
        self.draw()

    def draw(self):
        reactor.callLater(0, self.loop.draw_screen)

    def start(self, loop, user_data):
        self.lc = LoopingCall(self.fetch)
        self.lc.start(15)

    @inlineCallbacks
    def fetch(self):
        end = int(time.time())
        start = end - 15 * 60
        params = {
            "start": start,
            "end": end,
            "step": "1m",
            "query": "probe_duration_seconds{instance=\"matador.cloud\"}",
        }
        args = urllib.urlencode(params)
        url = "http://localhost:9090/api/v1/query_range?" + args
        self.changeStatus(u"Fetching fresh data…")
        response = yield treq.get(url)
        self.changeStatus(u"Got response…")
        json = yield response.json()
        self.changeStatus(u"Response has JSON; drawing graph…")
        data = json["data"]["result"][0]
        info = repr(data["metric"]).decode("utf-8")
        self.changePoints(tuple([float(x) for _, x in data["values"]]))
        self.changeStatus(u"Viewing %s" % info)

def main():
    palette = [
        ("graph", "light green", "black"),
    ]
    tloop = urwid.TwistedEventLoop()
    widget = urwid.SolidFill(' ')
    loop = urwid.MainLoop(widget, palette, event_loop=tloop)
    loop.screen.set_terminal_properties()
    loop.screen.reset_default_terminal_palette()

    prom = Prom.new(loop, widget)
    loop.widget = prom.frame

    # Queue the first turn.
    loop.set_alarm_in(0, prom.start)
    loop.run()

if __name__ == "__main__":
    main()
