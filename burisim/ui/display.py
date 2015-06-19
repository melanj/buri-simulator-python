# Make py2 like py3
from __future__ import (absolute_import, division, print_function, unicode_literals)
from builtins import (  # pylint: disable=redefined-builtin, unused-import
    bytes, dict, int, list, object, range, str,
    ascii, chr, hex, input, next, oct, open,
    pow, round, super,
    filter, map, zip
)

import struct
import threading

from PySide import QtCore, QtGui
import pyte

class ScreenView(QtGui.QFrame):
    def __init__(self, *args, **kwargs):
        super(ScreenView, self).__init__()
        self.setFrameShape(QtGui.QFrame.StyledPanel)
        self.setFrameShadow(QtGui.QFrame.Sunken)
        self._screen = None
        self._cached_screen_size = None

    @property
    def screen(self):
        return self._screen

    @screen.setter
    def screen(self, v):
        self._screen = v
        self._adjust_to_screen()

    def contents_changed(self):
        self.update()
        if self._cached_screen_size != self.screen.size:
            self._cached_screen_size = self.screen.size
            self.updateGeometry()

    def _adjust_to_screen(self):
        self.updateGeometry()

    def paintEvent(self, event):
        super(ScreenView, self).paintEvent(event)

        fw = self.frameWidth()
        fm = self.fontMetrics()

        p = QtGui.QPainter(self)

        p.fillRect(
            self.frameRect().adjusted(-fw, -fw, -fw, -fw),
            QtGui.qRgb(40, 40, 40)
        )

        if self._screen is None:
            return

        cw, ch = fm.width('X'), fm.lineSpacing()
        x0, y0 = fw, fw
        h, w = self._screen.size

        bg = QtGui.qRgb(0, 0, 0)
        fg = QtGui.qRgb(255, 255, 255)

        cbg = QtGui.qRgb(255, 255, 255)
        cfg = QtGui.qRgb(0, 0, 0)

        p.fillRect(x0, y0, w*cw, h*ch, bg)

        c = self._screen.cursor
        to = fm.ascent()
        for y, line in enumerate(self._screen.buffer):
            py = y * ch + y0
            for x, char in enumerate(line):
                p.setPen(fg)
                px = x * cw + x0

                if (x, y) == (c.x, c.y):
                    if self.hasFocus():
                        p.fillRect(px, py, cw, ch, cbg)
                        p.setPen(cfg)
                    else:
                        p.setPen(cbg)
                        p.drawRect(px, py, cw, ch)
                        p.setPen(fg)

                p.drawText(px, py + to, char.data)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        if self._screen is None:
            return QtCore.QSize(0,0)

        fw = self.frameWidth()
        fm = self.fontMetrics()
        h, w = self._screen.size
        return QtCore.QSize(2*fw + w*fm.width('X'), 2*fw + h*fm.lineSpacing())

class TerminalView(QtGui.QWidget):
    transmitByte = QtCore.Signal(int)

    def __init__(self, *args, **kwargs):
        super(TerminalView, self).__init__()
        self.screen = pyte.DiffScreen(80, 24)
        self.charSize = QtCore.QSize(8, 12)

        self.stream = pyte.ByteStream()
        self.stream.attach(self.screen)

        self._input_buffer_lock = threading.Lock()
        self._input_buffer = QtCore.QBuffer()
        self._input_buffer.bytesWritten.connect(self._have_input)
        self._input_buffer.open(
            QtCore.QIODevice.WriteOnly | QtCore.QIODevice.Unbuffered
        )


        l = QtGui.QVBoxLayout()
        l.setContentsMargins(0, 0, 0, 0)

        self.setLayout(l)
        self._screen_view = ScreenView()
        self._screen_view.screen = self.screen
        self._screen_view.installEventFilter(self)
        self._screen_view.setFont(QtGui.QFont('Monospace'))
        self._screen_view.setFocusPolicy(QtCore.Qt.StrongFocus)
        l.addWidget(self._screen_view)

    def receiveByte(self, b):
        with self._input_buffer_lock:
            self._input_buffer.putChar(b)

    def keyReleaseEvent(self, e):
        t = e.text()
        if t == '':
            return super(TerminalView, self).keyReleaseEvent(e)

        for c in t:
            self.transmitByte.emit(ord(c))

    def _have_input(self):
        with self._input_buffer_lock:
            self._input_buffer.close()
            bs = b''.join(self._input_buffer.data())
            self._input_buffer.setData(b'')
            self._input_buffer.open(
                QtCore.QIODevice.WriteOnly | QtCore.QIODevice.Unbuffered
            )

        self.stream.feed(bs)
        self._screen_view.contents_changed()

class HD44780View(QtGui.QWidget):
    def __init__(self, *args, **kwargs):
        super(HD44780View, self).__init__()
        self.rows = 4
        self.cols = 20
        self._display = None

        # compose font pixmaps
        self._font = []
        self._update_font()

    @property
    def display(self):
        return self._display

    @display.setter
    def display(self, d):
        if self._display is not None:
            self._display.update.disconnect(self._display_update)
        self._display = d
        self._display.update.connect(self._display_update)
        self.update()

    def sizeHint(self):
        if len(self._font) > 0:
            w = self._font[0].size().width()
            h = self._font[0].size().height()
        else:
            w, h = 1, 1
        return QtCore.QSize(self.cols * w, self.rows * h)

    def paintEvent(self, _):
        if len(self._font) == 0 or self._display is None:
            return

        p = QtGui.QPainter()
        assert p.begin(self)

        def paint_row(y, contents):
            for c, v in enumerate(contents):
                im = self._font[v]
                p.drawImage(c*im.width(), y, im)

        rh = self._font[0].height()
        paint_row(0*rh, self._display.ddram[:20])
        paint_row(1*rh, self._display.ddram[64:84])
        paint_row(2*rh, self._display.ddram[20:40])
        paint_row(3*rh, self._display.ddram[84:104])

        p.end()

    def _display_update(self):
        self.update()

    def _update_font(self):
        px_size = 2
        px_space = 2

        lcd_bg = QtGui.qRgb(0, 0, 20)
        lcd_off = QtGui.qRgb(60, 40, 20)
        lcd_on = QtGui.qRgb(250, 220, 20)

        def render_char(c):
            # Create QImage
            im = QtGui.QImage(
                5*(px_size+px_space) + px_space,
                8*(px_size+px_space) + px_space,
                QtGui.QImage.Format_RGB32
            )
            im.fill(lcd_bg)

            p = QtGui.QPainter()
            assert p.begin(im)
            for r_idx, r_def in enumerate((list(c) + [0]*8)[:8]):
                for c_idx in range(5):
                    c = lcd_off if r_def & (1<<(4-c_idx)) == 0 else lcd_on
                    p.fillRect(
                        (px_space+px_size)*c_idx + px_space,
                        (px_space+px_size)*r_idx + px_space,
                        px_size, px_size, c
                    )
            p.end()

            return im

        # render char rom font
        self._font = list(render_char(c) for c in CHAR_ROM)
        self.adjustSize()

CHAR_ROM = [
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [4, 4, 4, 4, 4, 0, 4],
    [10,10,10, 0, 0, 0, 0],
    [10,10,31,10,31,10,10],
    [4,15,20,14, 5,30, 4],
    [24,25, 2, 4, 8,19, 3],
    [12,18,20, 8,21,18,13],
    [12, 4, 8, 0, 0, 0, 0],
    [2, 4, 8, 8, 8, 4, 2],
    [8, 4, 2, 2, 2, 4, 8],
    [0, 4,21,14,21, 4, 0],
    [0, 4, 4,31, 4, 4, 0],
    [0, 0, 0, 0,12, 4, 8],
    [0, 0, 0,31, 0, 0, 0],
    [0, 0, 0, 0, 0,12,12],
    [0, 1, 2, 4, 8,16, 0],
    [14,17,19,21,25,17,14],
    [4,12, 4, 4, 4, 4,14],
    [14,17, 1, 2, 4, 8,31],
    [31, 2, 4, 2, 1,17,14],
    [2, 6,10,18,31, 2, 2],
    [31,16,30, 1, 1,17,14],
    [6, 8,16,30,17,17,14],
    [31, 1, 2, 4, 8, 8, 8],
    [14,17,17,14,17,17,14],
    [14,17,17,15, 1, 2,12],
    [0,12,12, 0,12,12, 0],
    [0,12,12, 0,12, 4, 8],
    [2, 4, 8,16, 8, 4, 2],
    [0, 0,31, 0,31, 0, 0],
    [16, 8, 4, 2, 4, 8,16],
    [14,17, 1, 2, 4, 0, 4],
    [14,17, 1,13,21,21,14],
    [14,17,17,17,31,17,17],
    [30,17,17,30,17,17,30],
    [14,17,16,16,16,17,14],
    [30,17,17,17,17,17,30],
    [31,16,16,30,16,16,31],
    [31,16,16,30,16,16,16],
    [14,17,16,23,17,17,15],
    [17,17,17,31,17,17,17],
    [14, 4, 4, 4, 4, 4,14],
    [7, 2, 2, 2, 2,18,12 ],
    [17,18,20,24,20,18,17],
    [16,16,16,16,16,16,31],
    [17,27,21,21,17,17,17],
    [17,17,25,21,19,17,17],
    [14,17,17,17,17,17,14],
    [30,17,17,30,16,16,16],
    [14,17,17,17,21,18,13],
    [30,17,17,30,20,18,17],
    [15,16,16,14, 1, 1,30],
    [31, 4, 4, 4, 4, 4, 4],
    [17,17,17,17,17,17,14],
    [17,17,17,17,17,10, 4],
    [17,17,17,21,21,21,10],
    [17,17,10, 4,10,17,17],
    [17,17,17,10, 4, 4, 4],
    [31, 1, 2, 4, 8,16,31],
    [14, 8, 8, 8, 8, 8,14],
    [17,10,31, 4,31, 4, 4],
    [14, 2, 2, 2, 2, 2,14],
    [4,10,17, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0,31],
    [8, 4, 2, 0, 0, 0, 0],
    [0, 0,14, 1,15,17,15],
    [16,16,22,25,17,17,30],
    [0, 0,14,16,16,17,14 ],
    [1, 1,13,19,17,17,15],
    [0, 0,14,17,31,16,14],
    [6, 9, 8,28, 8, 8, 8],
    [0, 0,15,17,15, 1,14],
    [16,16,22,25,17,17,17],
    [4, 0,12, 4, 4, 4,14 ],
    [2, 6, 2, 2, 2,18,12],
    [16,16,18,20,24,20,18],
    [12, 4, 4, 4, 4, 4,14],
    [0, 0,26,21,21,17,17],
    [0, 0,22,25,17,17,17],
    [0, 0,14,17,17,17,14],
    [0, 0,30,17,30,16,16],
    [0, 0,13,19,15, 1, 1],
    [0, 0,22,25,16,16,16],
    [0, 0,15,16,14, 1,30],
    [8, 8,28, 8, 8, 9, 6],
    [0, 0,17,17,17,19,13],
    [0, 0,17,17,17,10, 4],
    [0, 0,17,17,21,21,10],
    [0, 0,17,10, 4,10,17],
    [0, 0,17,17,15, 1,14],
    [0, 0,31, 2, 4, 8,31],
    [2, 4, 4, 8, 4, 4, 2],
    [4, 4, 4, 4, 4, 4, 4],
    [8, 4, 4, 2, 4, 4, 8],
    [0, 4, 2,31, 2, 4, 0],
    [0, 4, 8,31, 8, 4, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0,28,20,28],
    [7, 4, 4, 4, 0, 0, 0],
    [0, 0, 0, 4, 4, 4,28],
    [0, 0, 0, 0,16, 8, 4],
    [0, 0, 0,12,12, 0, 0],
    [0,31, 1,31, 1, 2, 4],
    [0, 0,31, 1, 6, 4, 8],
    [0, 0, 2, 4,12,20, 4],
    [0, 0, 4,31,17, 1, 6],
    [0, 0, 0,31, 4, 4,31],
    [0, 0, 2,31, 6,10,18],
    [0, 0, 8,31, 9,10, 8],
    [0, 0, 0,14, 2, 2,31],
    [0, 0,30, 2,30, 2,30],
    [0, 0, 0,21,21, 1, 6],
    [0, 0, 0, 0,31, 0, 0],
    [31, 1, 5, 6, 4, 4, 8],
    [1, 2, 4,12,20, 4, 4],
    [4,31,17,17, 1, 2, 4],
    [0, 0,31, 4, 4, 4,31],
    [2,31, 2, 6,10,18, 2],
    [8,31, 9, 9, 9, 9,18],
    [4,31, 4,31, 4, 4, 4],
    [0,15, 9,17, 1, 2,12],
    [8,15,18, 2, 2, 2, 4],
    [0,31, 1, 1, 1, 1,31],
    [10,31,10,10, 2, 4, 8],
    [0,24, 1,25, 1, 2,28],
    [0,31, 1, 2, 4,10,17],
    [8,31, 9,10, 8, 8, 7],
    [0,17,17, 9, 1, 2,12],
    [0,15, 9,21, 3, 2,12],
    [2,28, 4,31, 4, 4, 8],
    [0,21,21, 1, 1, 2, 4],
    [14, 0,31, 4, 4, 4, 8],
    [8, 8, 8,12,10, 8, 8],
    [4, 4,31, 4, 4, 8,16],
    [0,14, 0, 0, 0, 0,31],
    [0,31, 1,10, 4,10,16],
    [4,31, 2, 4,14,21, 4],
    [2, 2, 2, 2, 2, 4, 8],
    [0, 4, 2,17,17,17,17],
    [16,16,31,16,16,16,15],
    [0,31, 1, 1, 1, 2,12],
    [0, 8,20, 2, 1, 1, 0],
    [4,31, 4, 4,21,21, 4],
    [0,31, 1, 1,10, 4, 2],
    [0,14, 0,14, 0,14, 1],
    [0, 4, 8,16,17,31, 1],
    [0, 1, 1,10, 4,10,16],
    [0,31, 8,31, 8, 8, 7],
    [8, 8,31, 9,10, 8, 8],
    [0,14, 2, 2, 2, 2,31],
    [0,31, 1,31, 1, 1,31],
    [14, 0,31, 1, 1, 2, 4],
    [18,18,18,18, 2, 4, 8],
    [0, 4,20,20,21,21,22],
    [0,16,16,17,18,20,24],
    [0,31,17,17,17,17,31],
    [0,31,17,17, 1, 2, 4],
    [0,24, 0, 1, 1, 2,28],
    [4,18, 8, 0, 0, 0, 0],
    [28,20,28, 0, 0, 0, 0],
    [0, 0, 9,21,18,18,13 ],
    [10, 0,14, 1,15,17,15],
    [0,14,17,30,17,30,16],
    [0, 0,14,16,12,17,14],
    [0,17,17,17,19,29,16],
    [0, 0,15,20,18,17,14],
    [0, 6, 9,17,17,30,16],
    [0,15,17,17,17,15, 1],
    [0, 0, 7, 4, 4,20, 8],
    [2,26, 2, 0, 0, 0, 0],
    [2, 0, 6, 2, 2, 2, 2],
    [0,20, 8,20, 0, 0, 0],
    [4,14,20,21,14, 4, 0],
    [8, 8,28, 8,28, 8,15],
    [14, 0,22,25,17,17,17],
    [10, 0,14,17,17,17,14],
    [0,22,25,17,17,30,16],
    [0,13,19,17,17,15, 1 ],
    [14,17,31,17,17,14, 0],
    [0, 0, 0, 0,11,21,26 ],
    [0,14,17,17,10,27, 0],
    [10, 0,17,17,17,19,13],
    [31,16, 8, 4, 8,16,31],
    [0,31,10,10,10,19, 0 ],
    [31, 0,17,10, 4,10,17],
    [0,17,17,17,17,15, 1],
    [1,30, 4,31, 4, 4, 0],
    [0,31, 8,15, 9,17, 0],
    [0,31,21,31,17,17, 0 ],
    [0, 0, 4, 0,31, 0, 4 ],
    [0, 0, 0, 0, 0, 0, 0 ],
    [31,31,31,31,31,31,31],
]

