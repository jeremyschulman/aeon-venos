from collections import namedtuple
import time
import logging
from functools import partial
from aosxtools.proxyagents.nxos.exceptions import *


class Guestshell(object):
    GUESTSHELL_CPU = 6
    GUESTSHELL_DISK = 1024
    GUESTSHELL_MEMORY = 3072

    Resources = namedtuple('Resources', 'cpu memory disk')

    def __init__(self, device,
                 cpu=GUESTSHELL_CPU, memory=GUESTSHELL_MEMORY,
                 disk=GUESTSHELL_DISK, log=None):

        self.device = device
        self.guestshell = partial(self.device.api.exec_opcmd, msg_type='cli_show_ascii')
        self.cli = self.device.api.exec_opcmd
        self.log = log or logging.getLogger()

        self.sz_has = None
        self.sz_need = Guestshell.Resources(
            cpu=cpu, memory=memory, disk=disk)

        self._state = None
        self.exists = False

    # ---------------------------------------------------------------
    # -----
    # -----                     PROPERTIES
    # -----
    # ---------------------------------------------------------------

    @property
    def state(self):
        cmd = 'show virtual-service detail name guestshell+'
        try:
            got = self.cli(cmd)
        except CommandError:
            # means there is no guestshell
            self.exists = False
            self._state = 'None'
            return self._state

        try:
            self._state = got['TABLE_detail']['ROW_detail']['state']
            return self._state
        except TypeError:
            # means there is no guestshell
            self.exists = False
            self._state = 'None'
            return self._state

    @property
    def size(self):
        self._get_sz_info()
        return self.sz_has

    # ---------------------------------------------------------------
    # -----
    # -----                     PUBLIC METHODS
    # -----
    # ---------------------------------------------------------------

    def setup(self):
        self.log.info("/START(guestshell): setup")

        state = self.state
        self.log.info("/INFO(guestshell): current state: %s" % state)

        if 'Activated' == state:
            self._get_sz_info()
            if self.sz_need != self.sz_has:
                self.log.info("/INFO(guestshell): need to resize, please wait...")
                self.resize()
                self.reboot()
        else:
            self.log.info(
                "/INFO(guestshell): not activated, enabling with proper size, "
                "please wait ...")
            self.resize()
            self.enable()

        self._get_sz_info()
        self.log.info("/END(guestshell): setup")

    def reboot(self):
        self.guestshell('guestshell reboot')
        self._wait_state('Activated')

    def enable(self):
        self.guestshell('guestshell enable')
        self._wait_state('Activated')

    def destroy(self):
        self.guestshell('guestshell destroy')
        self._wait_state('None')

    def disable(self):
        self.guestshell('guestshell disable')
        self._wait_state('Deactivated')

    def resize(self):
        self.guestshell('guestshell resize cpu {}'.format(self.sz_need.cpu))
        self.guestshell('guestshell resize memory {}'.format(self.sz_need.memory))
        self.guestshell('guestshell resize rootfs {}'.format(self.sz_need.disk))

    def run(self, command):
        self.guestshell('guestshell run sudo %s' % command)

    # ---------------------------------------------------------------
    # -----
    # -----                     PRIVATE METHODS
    # -----
    # ---------------------------------------------------------------

    def _get_sz_info(self):
        """
        Obtains the current resource allocations, assumes that the
        guestshell is in an 'Activated' state
        """
        if 'None' == self._state:
            return None

        cmd = 'show virtual-service detail name guestshell+'
        got = self.cli(cmd)
        got = got['TABLE_detail']['ROW_detail']

        sz_cpu = int(got['cpu_reservation'])
        sz_disk = int(got['disk_reservation'])
        sz_memory = int(got['memory_reservation'])

        self.sz_has = Guestshell.Resources(
            cpu=sz_cpu, memory=sz_memory, disk=sz_disk)

    def _wait_state(self, state, timeout=60, interval=1, retry=0):
        now_state = None
        time.sleep(interval)

        while timeout:
            now_state = self.state
            if now_state == state:
                return
            time.sleep(interval)
            timeout -= 1

        if state == 'Activated' and now_state == 'Activating':
            # maybe give it some more time ...

            if retry > 2:
                msg = '/INFO(guestshell): waiting too long for Activated state'
                self.log.critical(msg)
                raise RuntimeError(msg)

            self.log.info('/INFO(guestshell): still Activating ... giving it some more time')
            self._wait_state(state, retry + 1)

        else:
            msg = '/INFO(guestshell): state %s never happened, still %s' % (state, now_state)
            self.log.critical(msg)
            raise RuntimeError(msg)