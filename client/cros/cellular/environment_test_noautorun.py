#!/usr/bin/python
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import mock
import sys
import unittest

# Import common to set the path to find autotest_lib
import common
from autotest_lib.client.bin import utils
utils.system = mock.MagicMock()

from autotest_lib.client.cros.cellular import ether_io_rf_switch
ether_io_rf_switch.RfSwitch = mock.MagicMock()

# Mock the local modem
sys.modules['flimflam'] = mock.MagicMock()

from autotest_lib.client.cros.cellular import labconfig
config = labconfig.Configuration(['--cell', 'mtv', '--technology', 'CDMA'])
# Mock out the get_interface_ip and have it return a real DUT.
# otherwise is looks up the IP of this machine and tries to find it
# in the DUTs section of the lab config. Not useful if this test file
# is run on a workstation.
dut1_ip = config.cell['duts'][0]['address']

labconfig.get_interface_ip = mock.Mock(return_value = dut1_ip)

# Must import after the mocks.
import environment

log = logging.getLogger('environment_test')
log.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter(' %(name)s - %(message)s' )
ch.setFormatter(formatter)
log.addHandler(ch)

class EnvTest(unittest.TestCase):

  def test_Env(self):
    """
    make an environment
    """
    with environment.DefaultCellularTestContext(config) as c:
      env = c.env
      env.StartDefault('Technology:HSDPA')
      log.debug('Starting')

if __name__ == '__main__':
  unittest.main()
