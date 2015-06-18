"""
Simulate the buri microcomputer.

Usage:
    burisim (-h | --help)
    burisim [options] [--serial URL] [--load FILE] <rom>

Options:
    -h, --help          Show a brief usage summary.
    -q, --quiet         Decrease verbosity.

    --no-gui            Don't create GUI.

Hardware options:
    --serial URL        Connect ACIA1 to this serial port. [default: loop://]
    --load FILE         Pre-load FILE at location 0x5000 in RAM.

"""
# Make py2 like py3
from __future__ import (absolute_import, division, print_function, unicode_literals)
from builtins import (  # pylint: disable=redefined-builtin, unused-import
    bytes, dict, int, list, object, range, str,
    ascii, chr, hex, input, next, oct, open,
    pow, round, super,
    filter, map, zip
)
from past.builtins import basestring # pylint: disable=redefined-builtin

import cgi
import logging
import signal
import sys
import time

from docopt import docopt
from PySide import QtCore, QtGui

from burisim.sim import BuriSim
from burisim.hw.hd44780 import HD44780View

_LOGGER = logging.getLogger(__name__)

class HexSpinBox(QtGui.QSpinBox):
    def __init__(self, *args, **kwargs):
        super(HexSpinBox, self).__init__(*args, **kwargs)
        self._padding = None

    def padding(self):
        return self._padding

    def setPadding(self, p):
        self._padding = int(p)

    def textFromValue(self, v):
        if self._padding is not None and self._padding > 0:
            f = '{0:0' + str(self._padding) + 'X}'
            return f.format(v)
        return ('{0:X}').format(v)

    def valueFromText(self, t):
        return int(t, 16)

    def validate(self, t, pos):
        if t.startswith(self.prefix()):
            t = t[len(self.prefix()):]
        if t.endswith(self.suffix()) and len(self.suffix()) > 0:
            t = t[:-len(self.suffix())]
        if t == '':
            return QtGui.QValidator.Intermediate
        try:
            int(t, 16)
            return QtGui.QValidator.Acceptable
        except:
            return QtGui.QValidator.Invalid

class MemoryView(QtGui.QWidget):
    def __init__(self, *args, **kwargs):
        super(MemoryView, self).__init__(*args, **kwargs)
        self.simulator = None
        self._page = 0
        self._init_ui()

    def page(self):
        return self._page

    def setPage(self, v):
        self._page = v
        self._refresh_mem()

    @QtCore.Slot(int)
    def _spinValueChanged(self, v):
        self.setPage(v)

    def _init_ui(self):
        l = QtGui.QVBoxLayout()
        self.setLayout(l)
        l.setSpacing(0)
        l.setContentsMargins(0, 0, 0, 0)

        te = QtGui.QTextEdit()
        te.setReadOnly(True)
        te.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        te.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        te.setFrameStyle(QtGui.QFrame.NoFrame)
        l.addWidget(te)
        self._te = te

        h = QtGui.QHBoxLayout()
        h.setSpacing(5)
        h.addWidget(QtGui.QLabel("Page:"))
        sb = HexSpinBox()
        sb.setPrefix('0x')
        sb.setPadding(2)
        sb.setRange(0, 0xff)
        sb.setSizePolicy(
            QtGui.QSizePolicy.MinimumExpanding,
            QtGui.QSizePolicy.Preferred,
        )
        sb.valueChanged.connect(self._spinValueChanged)
        h.addWidget(sb)
        l.addLayout(h)

        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_mem)
        self._refresh_timer.start(66) # run at approx ~15Hz

    def _refresh_mem(self):
        if self.simulator is None:
            return

        def mem_contents():
            m = self.simulator.memory
            start = 0x100 * self._page
            for line_offset in range(0x000, 0x100, 0x010):
                contents = m[start + line_offset:start + line_offset+0x010]
                yield line_offset, contents
            raise StopIteration()

        def render_line(offset, contents):
            hexrepr = '  '.join(
                ' '.join('{0:02X}'.format(b) for b in contents[o:o+8])
                for o in range(0, len(contents), 8)
            )
            asciirepr = ''.join(chr(b) if b>=32 and b<127 else '.' for b  in contents)
            return '{0:04X}  {1:48}  |{2:16}|'.format(
                self._page*0x100 + offset, hexrepr, asciirepr
            )

        dump = ''.join((
            '      {0}  {1}\n'.format(
                ' '.join('{0:02X}'.format(x) for x in range(0, 8)),
                ' '.join('{0:02X}'.format(x) for x in range(8, 16)),
            ),
            '\n'.join(render_line(o, c) for o, c in mem_contents()),
        ))
        self._te.setHtml('<pre><code>' + cgi.escape(dump) + '</code></pre>')

        self._te.setMinimumSize(self._te.document().size().toSize())

class ControlPanel(QtGui.QWidget):
    def __init__(self, *args, **kwargs):
        super(ControlPanel, self).__init__(*args, **kwargs)
        self._reset_action = QtGui.QAction("Reset", self)
        self._init_ui()

    def resetAction(self):
        return self._reset_action

    def _init_ui(self):
        l = QtGui.QHBoxLayout()
        self.setLayout(l)

        self._reset_button = QtGui.QToolButton()
        self._reset_button.setDefaultAction(self._reset_action)
        self._reset_button.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
        l.addWidget(self._reset_button)

class SimulatorUI(object):
    def __init__(self, sim):
        # Assign simulator
        self.sim = sim

        # Create memory view
        self._mv = MemoryView()
        self._mv.simulator = self.sim
        self._mv.setWindowTitle("Memory")
        self._mv.show()

        # Create lcd view
        self._lcd = HD44780View()
        self._lcd.display = self.sim.display
        self._lcd.setWindowTitle("Display")
        self._lcd.show()

        # Create control panel
        self._cp = ControlPanel()
        self._cp.setWindowTitle("Control panel")
        self._cp.resetAction().triggered.connect(sim.reset)
        self._cp.show()

def create_sim(opts):
    # Create simulator
    sim = BuriSim()

    # Create serial port
    sim.acia1.connect_to_file(opts['--serial'])

    # Read ROM
    sim.load_rom(opts['<rom>'])

    if opts['--load'] is not None:
        sim.load_ram(opts['--load'], 0x5000)

    # Reset the simulator
    sim.reset()

    return sim

def main():
    opts = docopt(__doc__)
    logging.basicConfig(
        level=logging.WARN if opts['--quiet'] else logging.INFO,
        stream=sys.stderr, format='%(name)s: %(message)s'
    )

    # Create GUI or non-GUI application as appropriate
    if opts['--no-gui']:
        app = QtCore.QCoreApplication(sys.argv)
    else:
        app = QtGui.QApplication(sys.argv)

    # Wire up Ctrl-C to quit app.
    def interrupt(*args):
        print('received interrupt signal, exitting...')
        app.quit()
    signal.signal(signal.SIGINT, interrupt)

    # Create the main simulator and attach it to application quit events.
    sim = create_sim(opts)

    # Start simulating once event loop is running
    QtCore.QTimer.singleShot(0, sim.start)

    # Stop simulating when app is quitting
    app.aboutToQuit.connect(sim.stop)

    # Create the sim UI if requested
    if not opts['--no-gui']:
        ui = SimulatorUI(sim)

    # Start the application
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
