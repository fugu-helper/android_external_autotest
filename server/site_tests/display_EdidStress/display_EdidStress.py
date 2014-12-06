# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This is a server side stressing DUT by switching Chameleon EDID."""

import glob
import logging
import os

from autotest_lib.client.common_lib import error
from autotest_lib.client.cros.chameleon import edid
from autotest_lib.server.cros.chameleon import chameleon_test


class display_EdidStress(chameleon_test.ChameleonTest):
    """Server side external display test.

    This test switches Chameleon EDID from among a large pool of EDIDs, tests
    DUT recognizes the emulated monitor and emits the correct video signal to
    Chameleon.
    """
    version = 1

    _EDID_TYPES = {'HDMI': {'HDMI', 'MHL', 'DVI'},
                   'DP': {'DP'},
                   'VGA': {'VGA'}}

    def run_once(self, host):
        edid_path = os.path.join(self.bindir, 'test_data', 'edids', '*')
        logging.info('See the display on Chameleon: port %d (%s)',
                     self.chameleon_port.get_connector_id(),
                     self.chameleon_port.get_connector_type())

        connector = self.chameleon_port.get_connector_type()
        supported_types = self._EDID_TYPES[connector]

        def _get_edid_type(s):
            i = s.rfind('_') + 1
            j = len(s) - len('.txt')
            return s[i:j].upper()

        failed_edids = []
        for filepath in glob.glob(edid_path):
            filename = os.path.basename(filepath)
            edid_type = _get_edid_type(filename)
            if edid_type not in supported_types:
                logging.info('Skip EDID: %s...', filename)
                continue

            logging.info('Use EDID: %s...', filename)
            resolution = (0, 0)
            try:
                with self.chameleon_port.use_edid(
                        edid.Edid.from_file(filepath, skip_verify=True)):
                    if not self.chameleon_port.wait_video_input_stable():
                        raise error.TestFail('Failed to wait source stable')
                    resolution = self.display_facade.get_external_resolution()
                    if resolution == (0, 0):
                        raise error.TestFail('Detected resolution 0x0')
                    if self.screen_test.test_resolution(resolution):
                        raise error.TestFail('Resolution test failed')
            except error.TestFail as e:
                logging.warning(e)
                logging.error('EDID not supported: %s', filename)
                failed_edids.append(filename)

        if failed_edids:
            message = ('Total %d EDIDs not supported: ' % len(failed_edids) +
                       ', '.join(failed_edids))
            logging.error(message)
            raise error.TestFail(message)
