#!/usr/bin/env nix-shell
# coding=utf-8
#! nix-shell -i python -p pythonPackages.attrs pythonPackages.urwid pythonPackages.twisted pythonPackages.treq

# PromQueen: A simple Prometheus query visualizer.
# © 2017 Corbin Simpson

from __future__ import division

import math
import sys
import time
import urllib

import attr

from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks
from twisted.internet.task import LoopingCall, deferLater
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

def clamp(x, low, high):
    return min(max(x, low), high)

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
        if top == bottom:
            # Add just a little bit of breathing room.
            top += 1
            bottom -= 1
        # Our projection will generally prevent points from occurring in the
        # first or last row, for aethetics. We borrow both rows here, and then
        # put one back when doing the offset fixup.
        scale = (maxrow - 2) / (top - bottom)
        rv = []
        for p in ps:
            p *= scale
            # "Put it back", but upside-down.
            fixed = maxrow - int(p) - 1
            rv.append(clamp(fixed, 0, maxrow))
        return rv

    def selectable(self):
        return False

    def render(self, size, focus=False):
        maxcol, maxrow = size
        # Fill out the points to full rank, times two, in order to get better
        # inter-character edges. Add a fencepost.
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
            p = min(p, maxrow - 1)
            s = ' ' * p + edge + ':' * (maxrow - p - 1)
            cols.append(s)
        # Transpose.
        rows = ["".join(rs) for rs in zip(*cols)]
        canvas = urwid.TextCanvas(rows, maxcol=maxcol)
        return canvas

class PromPane(urwid.WidgetWrap):
    @classmethod
    def new(cls, graph, status):
        header = urwid.Text(u"Graph Pane")
        footer = urwid.Text(status)
        frame = urwid.Frame(graph, header=header, footer=footer)
        self = cls(frame)
        return self

class PaneFlipper(urwid.WidgetWrap):
    @classmethod
    def new(cls, listWalker):
        self = cls(listWalker[0])
        self.listWalker = listWalker
        self.index = 0
        return self

    def next(self):
        self.index += 1
        self.index %= len(self.listWalker)
        self.update()

    def previous(self):
        self.index -= 1
        self.index %= len(self.listWalker)
        self.update()

    def update(self):
        self._w = self.listWalker[self.index]

class PromQuery(urwid.WidgetWrap):
    @classmethod
    def new(cls, query):
        status = urwid.Text(u"Starting up…")
        widget = urwid.SolidFill(' ')
        header = urwid.Text(u"PromQueen ♛")
        frame = urwid.Frame(widget, header=header, footer=status)
        self = cls(frame)
        self.query = query
        return self

    def start(self, loop, user_data):
        self.changeStatus(u"Starting query loop…", loop)
        self.lc = LoopingCall(self.fetch, loop)
        d = self.lc.start(15)

        @d.addErrback
        def loopFailed(failure):
            return self.changeStatus(u"Loop failed: %s" % failure, loop)

        return d

    @inlineCallbacks
    def fetch(self, loop):
        end = int(time.time())
        start = end - 15 * 60
        params = {
            "start": start,
            "end": end,
            "step": "1m",
            "query": self.query,
        }
        args = urllib.urlencode(params)
        url = "http://localhost:9090/api/v1/query_range?" + args

        # Enqueue the request before yielding our status change. This ensures
        # that the user will see that we're fetching the query, but also that
        # we start fetching the query before we wait for the screen redraw.
        request = treq.get(url)
        yield self.changeStatus(u"Fetching query %r…" % self.query, loop)
        response = yield request

        # Ditto here.
        d = response.json()
        yield self.changeStatus(u"Got response…", loop)
        json = yield d
        panes = []
        for i, data in enumerate(json["data"]["result"]):
            yield self.changeStatus(u"Drawing graph %d…" % i, loop)
            info = repr(data["metric"]).decode("utf-8")
            points = tuple([float(x) for _, x in data["values"]])
            status = u"Viewing query %s: %s" % (self.query, info)
            graph = urwid.AttrMap(PromWidget(points), "graph%d" % (i % 6))
            pane = PromPane.new(graph=graph, status=status)
            panes.append(pane)

        yield self.changeStatus(u"Idle", loop)

        # Assign the panes.
        self._w.contents["body"] = (PaneFlipper.new(urwid.SimpleFocusListWalker(panes)),
                                    self._w.options())

        # And queue a redraw.
        yield loop.redraw()

    def changeStatus(self, newStatus, loop):
        self._w.contents["footer"] = urwid.Text(newStatus), self._w.options()
        return loop.redraw()

    _selectable = True

    def keypress(self, size, key):
        pane = self._w.contents["body"][0]
        if key == "up":
            pane.previous()
        elif key == "down":
            pane.next()
        else:
            return pane.keypress(size, key)

def main(argv):
    query = argv[-1]
    prom = PromQuery.new(query)

    palette = [
        ("graph0", "light blue", "black"),
        ("graph1", "light cyan", "black"),
        ("graph2", "light gray", "black"),
        ("graph3", "light green", "black"),
        ("graph4", "light magenta", "black"),
        ("graph5", "light red", "black"),
    ]
    tloop = urwid.TwistedEventLoop()
    loop = urwid.MainLoop(prom, palette, event_loop=tloop)

    # Patch a very useful redraw combinator onto the loop.
    loop.redraw = lambda: deferLater(reactor, 0, loop.draw_screen)

    # Reset the screen's color palette. This is necessary if we want colors to
    # work?
    loop.screen.set_terminal_properties()
    loop.screen.reset_default_terminal_palette()

    # Queue the first turn.
    loop.set_alarm_in(0, prom.start)
    loop.run()

if __name__ == "__main__":
    main(sys.argv)
