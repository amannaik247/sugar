# Copyright (C) 2007 Red Hat, Inc.
# Copyright (C) 2008 One Laptop Per Child
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

from numpy import array
import random

import gobject
import gtk

_PLACE_TRIALS = 20
_MAX_WEIGHT = 255
_REFRESH_RATE = 200
_MAX_COLLISIONS_PER_REFRESH = 20

class Grid(gobject.GObject):
    __gsignals__ = {
        'child-changed' : (gobject.SIGNAL_RUN_FIRST,
                           gobject.TYPE_NONE,
                           ([gobject.TYPE_PYOBJECT]))
    }
    def __init__(self, width, height):
        gobject.GObject.__init__(self)

        self.width = width
        self.height = height
        self._children = []
        self._child_rects = {}
        self._locked_children = set()
        self._collisions = []
        self._collisions_sid = 0

        self._array = array([0], dtype='b')
        self._array.resize(width * height)

    def add(self, child, width, height, x=None, y=None, locked=False):
        if x is not None and y is not None:
            rect = gtk.gdk.Rectangle(x, y, width, height)
            weight = self._compute_weight(rect)
        else:
            trials = _PLACE_TRIALS
            weight = _MAX_WEIGHT
            while trials > 0 and weight:
                x = int(random.random() * (self.width - width))
                y = int(random.random() * (self.height - height))

                rect = gtk.gdk.Rectangle(x, y, width, height)
                new_weight = self._compute_weight(rect)
                if weight > new_weight:
                    weight = new_weight

                trials -= 1

        self._child_rects[child] = rect
        self._children.append(child)
        self._add_weight(self._child_rects[child])
        if locked:
            self._locked_children.add(child)

        if weight > 0:
            self._detect_collisions(child)

    def remove(self, child):
        self._children.remove(child)
        self._remove_weight(self._child_rects[child])
        self._locked_children.discard(child)
        del self._child_rects[child]

    def move(self, child, x, y, locked=False):
        self._remove_weight(self._child_rects[child])

        rect = self._child_rects[child]
        rect.x = x
        rect.y = y

        weight = self._compute_weight(rect)
        self._add_weight(self._child_rects[child])

        if locked:
            self._locked_children.add(child)
        else:
            self._locked_children.discard(child)

        if weight > 0:
            self._detect_collisions(child)
        
    def _shift_child(self, child, weight):
        rect = self._child_rects[child]
        
        new_rects = []

        # Get rects right, left, bottom and top
        if (rect.x + rect.width < self.width - 1):
            new_rects.append(gtk.gdk.Rectangle(rect.x + 1, rect.y,
                                               rect.width, rect.height))

        if (rect.x - 1 > 0):
            new_rects.append(gtk.gdk.Rectangle(rect.x - 1, rect.y,
                                               rect.width, rect.height))

        if (rect.y + rect.height < self.height - 1):
            new_rects.append(gtk.gdk.Rectangle(rect.x, rect.y + 1,
                                               rect.width, rect.height))

        if (rect.y - 1 > 0):
            new_rects.append(gtk.gdk.Rectangle(rect.x, rect.y - 1,
                                               rect.width, rect.height))

        # Get diagonal rects
        if rect.x + rect.width < self.width - 1 and \
                rect.y + rect.height < self.height - 1:
            new_rects.append(gtk.gdk.Rectangle(rect.x + 1, rect.y + 1,
                                               rect.width, rect.height))

        if rect.x - 1 > 0 and rect.y + rect.height < self.height - 1:
            new_rects.append(gtk.gdk.Rectangle(rect.x - 1, rect.y + 1,
                                               rect.width, rect.height))

        if rect.x + rect.width < self.width - 1 and rect.y - 1 > 0:
            new_rects.append(gtk.gdk.Rectangle(rect.x + 1, rect.y - 1,
                                               rect.width, rect.height))

        if rect.x - 1 > 0 and rect.y - 1 > 0:
            new_rects.append(gtk.gdk.Rectangle(rect.x - 1, rect.y - 1,
                                               rect.width, rect.height))

        random.shuffle(new_rects)

        best_rect = None
        for new_rect in new_rects:
            new_weight = self._compute_weight(new_rect)
            if new_weight < weight:
                best_rect = new_rect
                weight = new_weight
        
        if best_rect:
            self._child_rects[child] = best_rect
            weight = self._shift_child(child, weight)

        return weight

    def __solve_collisions_cb(self):
        for i in range(_MAX_COLLISIONS_PER_REFRESH):
            collision = self._collisions.pop(0)

            old_rect = self._child_rects[collision]
            self._remove_weight(old_rect)
            weight = self._compute_weight(old_rect)
            weight = self._shift_child(collision, weight)
            self._add_weight(self._child_rects[collision])

            # TODO: we shouldn't give up the first time we failed to find a
            # better position.
            if old_rect != self._child_rects[collision]:
                self._detect_collisions(collision)
                self.emit('child-changed', collision)
                if weight > 0:
                    self._collisions.append(collision)

            if not self._collisions:
                self._collisions_sid = 0
                return False

        return True

    def _detect_collisions(self, child):
        collision_found = False
        child_rect = self._child_rects[child]
        for c in self._children:
            intersection = child_rect.intersect(self._child_rects[c])
            if c != child and intersection.width > 0:
                if c not in self._locked_children and c not in self._collisions:
                    collision_found = True
                    self._collisions.append(c)

        if collision_found:
            if child not in self._collisions:
                self._collisions.append(child)

        if len(self._collisions) and not self._collisions_sid:
            self._collisions_sid = gobject.timeout_add(_REFRESH_RATE,
                    self.__solve_collisions_cb, priority=gobject.PRIORITY_LOW)

    def _add_weight(self, rect):
        for i in range(rect.x, rect.x + rect.width):
            for j in range(rect.y, rect.y + rect.height):
                self[j, i] += 1

    def _remove_weight(self, rect):
        for i in range(rect.x, rect.x + rect.width):
            for j in range(rect.y, rect.y + rect.height):
                self[j, i] -= 1

    def _compute_weight(self, rect):
        weight = 0

        for i in range(rect.x, rect.x + rect.width):
            for j in range(rect.y, rect.y + rect.height):
                weight += self[j, i]

        return weight
    
    def __getitem__(self, (row, col)):
        return self._array[col + row * self.width]

    def __setitem__(self, (row, col), value):
        self._array[col + row * self.width] = value

    def get_child_rect(self, child):
        return self._child_rects[child]
